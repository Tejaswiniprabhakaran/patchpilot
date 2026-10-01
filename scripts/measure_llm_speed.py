"""Measure local LLM speed on agent-sized prompts.

Sends prompts of roughly 1k, 4k and 8k tokens, built from real QuixBugs source code, to a local
Ollama server and records Ollama's own timings (prompt processing and generation). The numbers
decide whether the reported experiments can run on this machine (docs/decisions.md D7).

Usage:
    python scripts/measure_llm_speed.py --model gemma4:e4b
Appends one JSON line per prompt to results/llm_speed_cpu.jsonl.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

OUTPUT = Path("results/llm_speed_cpu.jsonl")
QUIXBUGS = Path("data/raw/QuixBugs/python_programs")
# Rough characters-per-token for source code; the true count comes back from Ollama.
CHARS_PER_TOKEN = 3.5
TARGET_TOKENS = [1000, 4000, 8000]
INSTRUCTION = (
    "You are fixing a bug. Below is source code from the repository. The failing test is "
    "python_testcases/test_gcd.py. Identify the buggy function and reply with a minimal unified "
    "diff that fixes it.\n\n"
)


def build_prompt(target_tokens: int) -> str:
    files = sorted(QUIXBUGS.glob("*.py"))
    parts: list[str] = []
    size = len(INSTRUCTION)
    budget = int(target_tokens * CHARS_PER_TOKEN)
    while size < budget:
        for path in files:
            text = f"### {path.name}\n{path.read_text(encoding='utf-8')}\n"
            parts.append(text)
            size += len(text)
            if size >= budget:
                break
    return INSTRUCTION + "".join(parts)[: budget - len(INSTRUCTION)]


def running_sandboxes() -> int:
    """Other Docker work competing for the CPU during the measurement."""
    try:
        out = subprocess.run(
            ["docker", "ps", "-q"], capture_output=True, text=True, timeout=20, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return -1
    return len(out.split())


def chat(base_url: str, model: str, prompt: str, max_tokens: int) -> dict[str, float]:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_ctx": 16384, "num_predict": max_tokens, "temperature": 0},
        }
    ).encode()
    request = urllib.request.Request(
        f"{base_url}/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=3600) as response:
        payload = json.loads(response.read())
    wall = time.monotonic() - started
    ns = 1e9
    prompt_s = payload.get("prompt_eval_duration", 0) / ns
    gen_s = payload.get("eval_duration", 0) / ns
    return {
        "prompt_tokens": payload.get("prompt_eval_count", 0),
        "output_tokens": payload.get("eval_count", 0),
        "load_s": round(payload.get("load_duration", 0) / ns, 2),
        "prompt_s": round(prompt_s, 2),
        "generation_s": round(gen_s, 2),
        "wall_s": round(wall, 2),
        "prompt_tok_per_s": round(payload.get("prompt_eval_count", 0) / prompt_s, 2)
        if prompt_s
        else 0.0,
        "gen_tok_per_s": round(payload.get("eval_count", 0) / gen_s, 2) if gen_s else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    # Warm-up so model loading is not counted in the first measurement.
    chat(args.base_url, args.model, "Say OK.", 4)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8", newline="\n") as out:
        for target in TARGET_TOKENS:
            busy = running_sandboxes()
            timings = chat(args.base_url, args.model, build_prompt(target), args.max_tokens)
            record = {
                "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
                "model": args.model,
                "machine": platform.processor() or platform.machine(),
                "target_prompt_tokens": target,
                "max_output_tokens": args.max_tokens,
                "docker_containers_running": busy,
                **timings,
            }
            out.write(json.dumps(record) + "\n")
            out.flush()
            print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
