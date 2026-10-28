"""Model client abstraction.

Every model PatchPilot uses (Gemma via Ollama on the laptop, Gemma via vLLM on a GPU, the optional
Gemini reference) is reached through one OpenAI-compatible chat API, so swapping models is a
config change. Each call's token counts and latency are recorded for the evaluation (A4).
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    finish_reason: str = "stop"
    # Hidden "thinking" text some models (e.g. Gemma 4) return separately from the answer.
    reasoning: str = ""


class LLMConfig(BaseModel):
    """Which model to call and how. Loaded from the experiment YAML."""

    base_url: str = "http://localhost:11434/v1"
    model: str = "gemma4:e4b"
    # Name of the environment variable holding the key; never the key itself.
    api_key_env: str = "PATCHPILOT_LLM_API_KEY"
    temperature: float = 0.0
    max_tokens: int = 2048
    seed: int | None = 42
    # A call taking longer than this is treated as an infrastructure stall (decisions D13).
    timeout_s: float = 1800.0
    # Context window the run needs. Ollama's OpenAI-compatible API cannot set it per request, so
    # the Ollama model itself is created with it (configs/ollama/); `patchpilot eval` refuses to
    # start when the server's window is smaller (decisions D17).
    context_tokens: int | None = 16384
    # Passed to the server as `reasoning_effort` when set, e.g. "none" to switch thinking off.
    reasoning_effort: str | None = None


class LLMClient(Protocol):
    def complete(self, messages: list[Message], *, max_tokens: int | None = None) -> Completion: ...


@dataclass
class UsageLog:
    """Running totals over every model call of one agent run."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    history: list[dict[str, Any]] = field(default_factory=list)

    def record(self, completion: Completion) -> None:
        self.calls += 1
        self.prompt_tokens += completion.prompt_tokens
        self.completion_tokens += completion.completion_tokens
        self.latency_s += completion.latency_s
        # The reply text is kept in the trajectory, not duplicated here.
        self.history.append(
            {k: v for k, v in asdict(completion).items() if k not in ("text", "reasoning")}
        )

    def totals(self) -> dict[str, float]:
        return {
            "llm_calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "llm_latency_s": round(self.latency_s, 2),
        }


class OpenAICompatibleClient:
    """Chat client for any OpenAI-compatible server (Ollama, vLLM, llama.cpp, Gemini)."""

    def __init__(self, config: LLMConfig, usage: UsageLog | None = None, client: Any = None):
        self.config = config
        self.usage = usage or UsageLog()
        if client is None:
            from openai import OpenAI

            client = OpenAI(
                base_url=config.base_url,
                api_key=os.environ.get(config.api_key_env) or "not-needed",
                timeout=config.timeout_s,
                max_retries=0,  # a stall must surface as an error, not be retried silently
            )
        self._client = client

    def complete(self, messages: list[Message], *, max_tokens: int | None = None) -> Completion:
        extra: dict[str, Any] = {}
        if self.config.reasoning_effort:
            extra["reasoning_effort"] = self.config.reasoning_effort
        started = time.monotonic()
        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=self.config.temperature,
            max_tokens=max_tokens or self.config.max_tokens,
            seed=self.config.seed,
            extra_body=extra or None,
        )
        latency = time.monotonic() - started
        choice = response.choices[0]
        usage = response.usage
        completion = Completion(
            text=choice.message.content or "",
            model=response.model or self.config.model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_s=round(latency, 3),
            finish_reason=choice.finish_reason or "stop",
            reasoning=_reasoning_text(choice.message),
        )
        self.usage.record(completion)
        return completion


OLLAMA_DEFAULT_CONTEXT = 4096


class ContextWindowError(RuntimeError):
    """The model server would silently cut prompts that the experiment needs to send whole."""


def ollama_context_window(base_url: str, model: str, timeout_s: float = 10.0) -> int | None:
    """Context window an Ollama server runs ``model`` with; None if the server is not Ollama.

    Ollama uses the model's ``num_ctx`` parameter, or its 4,096-token default when the model does
    not set one; requests through the OpenAI-compatible API cannot change it (decisions D17).
    """
    import httpx

    root = base_url.rstrip("/").removesuffix("/v1")
    try:
        response = httpx.post(f"{root}/api/show", json={"model": model}, timeout=timeout_s)
        data = response.json() if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(data, dict) or "modelfile" not in data:
        return None
    for line in str(data.get("parameters", "")).splitlines():
        name, _, value = line.strip().partition(" ")
        if name == "num_ctx" and value.strip().isdigit():
            return int(value.strip())
    return OLLAMA_DEFAULT_CONTEXT


def check_context_window(config: LLMConfig, window_of: Any = ollama_context_window) -> None:
    """Refuse to run when the server's context window is smaller than the run needs."""
    if not config.context_tokens:
        return
    window = window_of(config.base_url, config.model)
    if window is not None and window < config.context_tokens:
        raise ContextWindowError(
            f"{config.model} runs with a {window}-token context window, but the config needs "
            f"{config.context_tokens}. Create the model from configs/ollama/ (decisions D17)."
        )


def _reasoning_text(message: Any) -> str:
    """Servers expose thinking as `reasoning` or `reasoning_content`; either may be missing."""
    for name in ("reasoning", "reasoning_content"):
        value = getattr(message, name, None)
        if value is None:
            extra = getattr(message, "model_extra", None) or {}
            value = extra.get(name)
        if isinstance(value, str) and value:
            return value
    return ""


class ScriptedClient:
    """Returns pre-written replies in order. Used in tests and for dry runs without a model."""

    def __init__(self, replies: list[str], usage: UsageLog | None = None) -> None:
        self.replies = list(replies)
        self.usage = usage or UsageLog()
        self.prompts: list[list[Message]] = []

    def complete(self, messages: list[Message], *, max_tokens: int | None = None) -> Completion:
        self.prompts.append(messages)
        if not self.replies:
            raise RuntimeError("ScriptedClient ran out of replies")
        text = self.replies.pop(0)
        completion = Completion(
            text=text,
            model="scripted",
            prompt_tokens=sum(len(m.content) for m in messages) // 4,
            completion_tokens=len(text) // 4,
            latency_s=0.0,
        )
        self.usage.record(completion)
        return completion
