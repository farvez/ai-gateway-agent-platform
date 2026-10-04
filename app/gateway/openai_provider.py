import os

from openai import OpenAI

from app.config import request_timeout

from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    def __init__(self):
        # max_retries=0: the gateway handles retries, so the SDK must not retry too.
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            timeout=request_timeout(),
            max_retries=0,
        )

    def generate(self, message: str, model: str | None = None) -> dict:

        model = model or "gpt-4o-mini"

        response = self.client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": message}]
        )

        return {
            "provider": "openai",
            "model": model,
            "content": response.choices[0].message.content,
            "usage": {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }
