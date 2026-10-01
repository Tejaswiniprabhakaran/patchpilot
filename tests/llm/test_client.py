from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from patchpilot.llm import LLMConfig, Message, OpenAICompatibleClient, ScriptedClient, UsageLog


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
    assert kwargs["extra_body"] == {"options": {"num_ctx": 16384}}
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
