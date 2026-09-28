import os

import anthropic

from .base import LLMProvider


class ClaudeProvider(LLMProvider):

    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )

    def generate(
        self,
        message: str,
        model: str | None = None
    ) -> dict:

        model = model or "claude-sonnet-5"

        response = self.client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": message
                }
            ]
        )

        return {
            "provider": "anthropic",
            "model": model,
            "content": response.content[0].text,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": (
                    response.usage.input_tokens
                    + response.usage.output_tokens
                ),
            }
        }