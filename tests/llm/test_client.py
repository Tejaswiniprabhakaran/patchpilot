from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from patchpilot.llm import LLMConfig, Message, OpenAICompatibleClient, ScriptedClient, UsageLog
from patchpilot.llm.client import (
    OLLAMA_DEFAULT_CONTEXT,
    ContextWindowError,
    check_context_window,
    ollama_context_window,
)


def fake_response(text: str, prompt: int, completion: int) -> SimpleNamespace:
    return SimpleNamespace(
        model="gemma4:12b",
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


def test_openai_client_sends_config_and_records_usage() -> None:
    raw = MagicMock()
    raw.chat.completions.create.return_value = fake_response("fixed", 100, 7)
    config = LLMConfig(model="gemma4:12b", temperature=0.2, max_tokens=99, seed=3)
    client = OpenAICompatibleClient(config, client=raw)

    completion = client.complete([Message("system", "be brief"), Message("user", "fix it")])

    kwargs = raw.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gemma4:12b"
    assert kwargs["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "fix it"},
    ]
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 99
    assert kwargs["seed"] == 3
    assert kwargs["extra_body"] is None  # Ollama ignores a per-request num_ctx (D17)
    assert completion.text == "fixed"
    assert client.usage.totals()["prompt_tokens"] == 100
    assert client.usage.totals()["completion_tokens"] == 7
    assert client.usage.calls == 1


def test_max_tokens_can_be_overridden_per_call() -> None:
    raw = MagicMock()
    raw.chat.completions.create.return_value = fake_response("x", 1, 1)
    client = OpenAICompatibleClient(LLMConfig(context_tokens=None), client=raw)

    client.complete([Message("user", "hi")], max_tokens=5)

    kwargs = raw.chat.completions.create.call_args.kwargs
    assert kwargs["max_tokens"] == 5
    assert kwargs["extra_body"] is None


def test_missing_usage_and_content_do_not_crash() -> None:
    raw = MagicMock()
    raw.chat.completions.create.return_value = SimpleNamespace(
        model=None,
        choices=[SimpleNamespace(message=SimpleNamespace(content=None), finish_reason=None)],
        usage=None,
    )
    client = OpenAICompatibleClient(LLMConfig(model="m"), client=raw)

    completion = client.complete([Message("user", "hi")])

    assert completion.text == ""
    assert completion.model == "m"
    assert completion.prompt_tokens == 0


def test_usage_log_accumulates_and_keeps_text_out_of_history() -> None:
    usage = UsageLog()
    client = ScriptedClient(["one", "two"], usage=usage)

    client.complete([Message("user", "a")])
    client.complete([Message("user", "b")])

    assert usage.calls == 2
    assert all("text" not in entry for entry in usage.history)
    expected = {"llm_calls", "prompt_tokens", "completion_tokens", "llm_latency_s"}
    assert set(usage.totals()) == expected


def test_scripted_client_raises_when_out_of_replies() -> None:
    client = ScriptedClient([])

    with pytest.raises(RuntimeError):
        client.complete([Message("user", "a")])


def test_reasoning_is_captured_and_effort_is_sent() -> None:
    raw = MagicMock()
    response = fake_response("", 10, 2048)
    response.choices[0].message.reasoning = "thinking..."
    response.choices[0].finish_reason = "length"
    raw.chat.completions.create.return_value = response
    client = OpenAICompatibleClient(LLMConfig(reasoning_effort="none"), client=raw)

    completion = client.complete([Message("user", "fix")])

    assert raw.chat.completions.create.call_args.kwargs["extra_body"]["reasoning_effort"] == "none"
    assert completion.reasoning == "thinking..."
    assert completion.finish_reason == "length"
    assert "reasoning" not in client.usage.history[0]


def test_ollama_context_window_reads_the_models_num_ctx(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, json: dict, timeout: float) -> SimpleNamespace:  # type: ignore[type-arg]
        assert url == "http://localhost:11434/api/show"
        params = (
            'num_ctx                        16384\nstop "<eos>"' if json["model"] == "big" else ""
        )
        body = {"modelfile": "FROM gemma4:e4b", "parameters": params}
        return SimpleNamespace(status_code=200, json=lambda: body)

    monkeypatch.setattr("httpx.post", fake_post)

    assert ollama_context_window("http://localhost:11434/v1", "big") == 16384
    assert ollama_context_window("http://localhost:11434/v1", "small") == OLLAMA_DEFAULT_CONTEXT


def test_ollama_context_window_is_none_without_an_ollama_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(url: str, json: dict, timeout: float) -> None:  # type: ignore[type-arg]
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("httpx.post", refused)

    assert ollama_context_window("http://localhost:8000/v1", "any") is None


def test_check_context_window_refuses_a_smaller_window() -> None:
    config = LLMConfig(model="gemma4:e4b", context_tokens=16384)

    with pytest.raises(ContextWindowError, match="4096-token"):
        check_context_window(config, window_of=lambda url, model: 4096)
    check_context_window(config, window_of=lambda url, model: 16384)
    check_context_window(config, window_of=lambda url, model: None)  # not an Ollama server
    check_context_window(LLMConfig(context_tokens=None), window_of=lambda url, model: 4096)
