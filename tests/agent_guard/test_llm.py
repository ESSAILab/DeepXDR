from __future__ import annotations

from ai_agent.agent_guard.llm import OpenAICompletionLLM


class Message:
    content = '{"verdict":"allow"}'


class Choice:
    message = Message()


class CompletionResponse:
    choices = [Choice()]


class CompletionStub:
    def __init__(self, fail_json_mode: bool = False):
        self.fail_json_mode = fail_json_mode
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_json_mode and "response_format" in kwargs:
            raise TypeError("response_format is not supported")
        return CompletionResponse()


class ChatStub:
    def __init__(self, completion):
        self.completions = completion


class ClientStub:
    def __init__(self, completion):
        self.chat = ChatStub(completion)


def test_openai_completion_llm_requests_json_object_response(monkeypatch):
    completion = CompletionStub()

    monkeypatch.setattr(
        "ai_agent.agent_guard.llm.OpenAI",
        lambda **_kwargs: ClientStub(completion),
    )

    llm = OpenAICompletionLLM(
        api_key="test",
        base_url="http://example.test",
        model="model",
        request_timeout_seconds=120,
    )

    assert llm.complete("prompt") == '{"verdict":"allow"}'
    assert completion.calls[0]["response_format"] == {"type": "json_object"}
    assert completion.calls[0]["timeout"] == 120


def test_openai_completion_llm_falls_back_when_json_mode_is_unsupported(monkeypatch):
    completion = CompletionStub(fail_json_mode=True)

    monkeypatch.setattr(
        "ai_agent.agent_guard.llm.OpenAI",
        lambda **_kwargs: ClientStub(completion),
    )

    llm = OpenAICompletionLLM(
        api_key="test",
        base_url="http://example.test",
        model="model",
        request_timeout_seconds=45,
    )

    assert llm.complete("prompt") == '{"verdict":"allow"}'
    assert len(completion.calls) == 2
    assert "response_format" not in completion.calls[1]
    assert completion.calls[1]["timeout"] == 45
