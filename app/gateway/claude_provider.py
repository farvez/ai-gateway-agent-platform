import os
from collections.abc import Iterator

import anthropic

from app.config import default_model, request_timeout

from .base import LLMProvider


class ClaudeProvider(LLMProvider):
    def __init__(self):
        # max_retries=0: the gateway handles retries, so the SDK must not retry too.
        self.client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            timeout=request_timeout(),
            max_retries=0,
        )

    def _model(self, model: str | None) -> str:
        return model or default_model("anthropic", "claude-sonnet-5")

    def generate(self, message: str, model: str | None = None) -> dict:

        model = self._model(model)

        response = self.client.messages.create(
            model=model, max_tokens=1024, messages=[{"role": "user", "content": message}]
        )

        return {
            "provider": "anthropic",
            "model": model,
            "content": response.content[0].text,
            "usage": _usage(response.usage),
        }

    def stream(self, message: str, model: str | None = None) -> Iterator[dict]:

        model = self._model(model)

        with self.client.messages.stream(
            model=model, max_tokens=1024, messages=[{"role": "user", "content": message}]
        ) as stream:
            for text in stream.text_stream:
                yield {"type": "delta", "text": text}
            final = stream.get_final_message()

        yield {
            "type": "done",
            "provider": "anthropic",
            "model": model,
            "usage": _usage(final.usage),
        }


def _usage(usage) -> dict:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.input_tokens + usage.output_tokens,
    }
