from __future__ import annotations

from openai import OpenAI


class OpenAICompletionLLM:
    """Synchronous LLM adapter for agent-guard adjudication."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        model: str,
        request_timeout_seconds: int = 15 * 60,
    ):
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model = model
        self.request_timeout_seconds = request_timeout_seconds

    def complete(self, prompt: str) -> str:
        request = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "timeout": self.request_timeout_seconds,
        }
        try:
            response = self.client.chat.completions.create(**request)
        except (TypeError, ValueError):
            request.pop("response_format", None)
            response = self.client.chat.completions.create(**request)
        return response.choices[0].message.content or "{}"
