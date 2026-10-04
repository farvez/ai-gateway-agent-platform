import os

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

    def generate(self, message: str, model: str | None = None) -> dict:

        model = model or default_model("anthropic", "claude-sonnet-5")

        response = self.client.messages.create(
            model=model, max_tokens=1024, messages=[{"role": "user", "content": message}]
        )

        return {
            "provider": "anthropic",
            "model": model,
            "content": response.content[0].text,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": (response.usage.input_tokens + response.usage.output_tokens),
            },
        }
