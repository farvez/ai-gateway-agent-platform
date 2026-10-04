import os

from openai import OpenAI

from app.config import request_timeout

from .base import LLMProvider


class GroqProvider(LLMProvider):
    def __init__(self):
        # Groq exposes an OpenAI-compatible API, so the OpenAI SDK works
        # by pointing it at Groq's base URL.
        # max_retries=0: the gateway handles retries, so the SDK must not retry too.
        self.client = OpenAI(
            api_key=os.getenv("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
            timeout=request_timeout(),
            max_retries=0,
        )

    def generate(self, message: str, model: str | None = None) -> dict:

        model = model or "llama-3.3-70b-versatile"

        response = self.client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": message}]
        )

        return {
            "provider": "groq",
            "model": model,
            "content": response.choices[0].message.content,
            "usage": {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }
