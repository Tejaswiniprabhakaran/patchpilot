"""Capture the report's screenshots and diagrams with Microsoft Edge in headless mode (Issue #17).

  diagrams   the three Mermaid diagrams in docs/architecture.md, rendered by mermaid.js
  dashboard  the dashboard (started here on 127.0.0.1:8765 over results/): runs, a trajectory,
             metrics and the Try-it page
  cli        `patchpilot show <run_id>` in a terminal (recorded by Rich as SVG, then rendered)
  bot        the GitHub bot's comment on the public demo pull request, plus its text and run
             metadata saved to results/bot_demo/ (read with the GitHub CLI)

Edge runs with a throw-away profile, so the user's own browser profile is never touched. Run it
from the repository root, where results/ holds the experiment results.

Usage:
    python scripts/capture_figures.py [--only diagrams dashboard cli bot] [--out-root .]
Writes report/figures/{diagram_*,dashboard_*,cli_show,bot_comment}.png
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

OUT = Path("report/figures")  # under --out-root
DEMO_REPO = "Tejaswiniprabhakaran/patchpilot-demo"
DEMO_PR = 1
DASHBOARD_PORT = 8765
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"
DIAGRAM_NAMES = ["diagram_architecture", "diagram_agent_loop", "diagram_experiments"]


def edge() -> Path:
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES")):
        path = Path(base or "") / "Microsoft/Edge/Application/msedge.exe"
        if base and path.exists():
            return path
    raise SystemExit("Microsoft Edge was not found; it renders the screenshots")


def screenshot(url: str, out: Path, width: int, height: int, wait_ms: int = 4000) -> None:
    profile = Path(tempfile.mkdtemp(prefix="patchpilot-edge-"))
    out.unlink(missing_ok=True)
    try:
        subprocess.run(
            [
                str(edge()),
                "--headless",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-first-run",
                "--no-default-browser-check",
                "--force-device-scale-factor=1",
                f"--user-data-dir={profile}",
                f"--window-size={width},{height}",
                # Lets scripts finish (mermaid); 0 for pages that poll, which would never settle.
                *([f"--virtual-time-budget={wait_ms}"] if wait_ms else []),
                f"--screenshot={out.resolve()}",
                url,
            ],
            check=True,
            timeout=180,
            capture_output=True,
        )
        # msedge.exe hands the work to a browser process and returns before the file is written.
        deadline = time.monotonic() + 120
        size = -1
        while time.monotonic() < deadline:
            if out.exists() and out.stat().st_size == size > 0:
                break
            size = out.stat().st_size if out.exists() else -1
            time.sleep(2)
        else:
            raise SystemExit(f"Edge did not write {out}")
        time.sleep(2)  # let the browser process exit before its profile is deleted
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    trim(out)
    print(f"wrote {out}  ({url})")


def trim(path: Path, margin: int = 12) -> None:
    """Cut empty background: the sides and top against the top-left pixel's colour, the bottom
    against the bottom-left pixel's (a page's header and body often differ)."""
    from PIL import Image, ImageChops

    image = Image.open(path).convert("RGB")

    def content_box(corner: tuple[int, int]) -> tuple[int, int, int, int] | None:
        background = Image.new("RGB", image.size, image.getpixel(corner))
        return ImageChops.difference(image, background).getbbox()

    top_box = content_box((0, 0)) or (0, 0, image.width, image.height)
    bottom_box = content_box((0, image.height - 1)) or top_box
    left, top, right, _ = top_box
    image = image.crop(
        (
            max(0, left - margin),
            max(0, top - margin),
            min(image.width, right + margin),
            min(image.height, bottom_box[3] + margin),
        )
    )
    image.save(path)


def page_file(content: str, name: str, folder: Path) -> str:
    path = folder / name
    path.write_text(content, encoding="utf-8")
    return path.resolve().as_uri()


# ---------------------------------------------------------------------- captures


def capture_diagrams(folder: Path) -> None:
    text = Path("docs/architecture.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```mermaid\n(.*?)```", text, flags=re.S)
    for name, block in zip(DIAGRAM_NAMES, blocks, strict=False):
        page = (
            '<!doctype html><html><head><meta charset="utf-8">'
            f'<script src="{MERMAID}"></script>'
            "<style>body{margin:24px;background:#ffffff}</style></head><body>"
            f'<pre class="mermaid">{html.escape(block)}</pre>'
            '<script>mermaid.initialize({startOnLoad: true, theme: "neutral"});</script>'
            "</body></html>"
        )
        screenshot(page_file(page, f"{name}.html", folder), OUT / f"{name}.png", 1500, 1400, 8000)


def a_resolved_run() -> str:
    """A short, resolved B0 QuixBugs run (fewest attempts, then fewest model calls)."""
    rows = [
        json.loads(line)
        for line in Path("results/B0/quixbugs.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    resolved = [r for r in rows if r["resolved"]]
    return str(min(resolved, key=lambda r: (r["attempts_used"], r["llm_calls"]))["run_id"])


def capture_dashboard() -> None:
    server = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from patchpilot.cli import app; app()",
            "dashboard",
            "--port",
            str(DASHBOARD_PORT),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{DASHBOARD_PORT}"
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # no system proxy
    try:
        for _ in range(30):
            try:
                direct.open(f"{base}/", timeout=30)  # /api/health is slow: it pings Docker
                break
            except OSError:
                time.sleep(1)
        else:
            raise SystemExit("the dashboard did not start")
        pages = {
            "dashboard_runs": "/",
            "dashboard_trajectory": f"/runs/B0/{a_resolved_run()}",
            "dashboard_metrics": "/metrics",
            "dashboard_try": "/try",
        }
        for name, path in pages.items():
            # The Try-it page polls the server, so it is captured at load without a time budget.
            screenshot(
                base + path, OUT / f"{name}.png", 1366, 2200, 0 if name.endswith("try") else 4000
            )
    finally:
        server.terminate()
        server.wait(timeout=30)


def capture_cli(folder: Path) -> None:
    from rich.console import Console

    import patchpilot.cli as cli

    run_id = a_resolved_run()
    cli.console = Console(record=True, width=112, force_terminal=True, color_system="truecolor")
    cli.show(run_id, full=False)
    svg = cli.console.export_svg(title=f"patchpilot show {run_id}")
    height = int(float(re.search(r'viewBox="0 0 [\d.]+ ([\d.]+)"', svg).group(1)))  # type: ignore[union-attr]
    url = page_file(
        f'<!doctype html><html><body style="margin:0;background:#ffffff">{svg}</body></html>',
        "cli_show.html",
        folder,
    )
    screenshot(url, OUT / "cli_show.png", 1400, min(height + 40, 6000))


def capture_bot() -> None:
    def gh(*args: str) -> object:
        result = subprocess.run(["gh", *args], check=True, capture_output=True, encoding="utf-8")
        return json.loads(result.stdout)

    comments = gh("api", f"repos/{DEMO_REPO}/issues/{DEMO_PR}/comments")
    bot = next(c for c in comments if "patchpilot-bot" in c["body"])  # type: ignore[union-attr]
    runs = gh("run", "list", "--repo", DEMO_REPO, "--limit", "20", "--json",
              "databaseId,headBranch,event,conclusion,createdAt,updatedAt,url")  # fmt: skip
    pr = gh("pr", "view", str(DEMO_PR), "--repo", DEMO_REPO, "--json", "headRefName,url,title")
    run = next(r for r in runs if r["headBranch"] == pr["headRefName"])  # type: ignore[index,union-attr]
    jobs = gh("api", f"repos/{DEMO_REPO}/actions/runs/{run['databaseId']}/jobs")["jobs"]  # type: ignore[index]
    record = {
        "pull_request": pr,
        "comment": {"created_at": bot["created_at"], "url": bot["html_url"], "body": bot["body"]},
        "workflow_run": run,
        "jobs": [
            {k: j[k] for k in ("name", "conclusion", "started_at", "completed_at")} for j in jobs
        ],
    }
    folder = OUT.parent.parent / "results/bot_demo"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{DEMO_REPO.split('/')[1]}-pr{DEMO_PR}.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    screenshot(pr["url"], OUT / "bot_comment.png", 1280, 2600, 6000)  # type: ignore[index]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", nargs="+", default=["diagrams", "dashboard", "cli", "bot"], help="what to capture"
    )
    parser.add_argument(
        "--out-root", type=Path, default=Path("."), help="repository to write figures into"
    )
    args = parser.parse_args()
    global OUT
    OUT = args.out_root / "report/figures"
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="patchpilot-pages-") as tmp:
        folder = Path(tmp)
        if "diagrams" in args.only:
            capture_diagrams(folder)
        if "dashboard" in args.only:
            capture_dashboard()
        if "cli" in args.only:
            capture_cli(folder)
        if "bot" in args.only:
            capture_bot()


if __name__ == "__main__":
    main()
