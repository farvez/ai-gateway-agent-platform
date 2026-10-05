import os
from collections.abc import Iterator

from openai import OpenAI

from app.config import default_model, max_output_tokens, request_timeout

from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    # Subclasses for OpenAI-compatible APIs (e.g. Groq) override these.
    name = "openai"
    api_key_env = "OPENAI_API_KEY"
    base_url: str | None = None
    fallback_model = "gpt-4o-mini"

    def __init__(self):
        # max_retries=0: the gateway handles retries, so the SDK must not retry too.
        self.client = OpenAI(
            api_key=os.getenv(self.api_key_env),
            base_url=self.base_url,
            timeout=request_timeout(),
            max_retries=0,
        )

    def _model(self, model: str | None) -> str:
        return model or default_model(self.name, self.fallback_model)

    def generate(self, message: str, model: str | None = None) -> dict:

        model = self._model(model)

        response = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": message}],
            max_completion_tokens=max_output_tokens(),
        )

        return {
            "provider": self.name,
            "model": model,
            "content": response.choices[0].message.content,
            "usage": _usage(response.usage),
        }

    def stream(self, message: str, model: str | None = None) -> Iterator[dict]:

        model = self._model(model)

        chunks = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": message}],
            max_completion_tokens=max_output_tokens(),
            stream=True,
            # Ask for token usage in the final chunk (it's not sent by default when streaming).
            stream_options={"include_usage": True},
        )

        usage = None
        for chunk in chunks:
            if chunk.choices and chunk.choices[0].delta.content:
                yield {"type": "delta", "text": chunk.choices[0].delta.content}
            if chunk.usage:
                usage = chunk.usage

        yield {"type": "done", "provider": self.name, "model": model, "usage": _usage(usage)}


def _usage(usage) -> dict:
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    return {
        "input_tokens": usage.prompt_tokens,
        "output_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }
