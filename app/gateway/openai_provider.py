import os
from openai import OpenAI
from .base import LLMProvider

class OpenAIProvider(LLMProvider):

    def __init__(self):
        self.client = OpenAI(
            api_key = os.getenv("OPENAI_API_KEY")
        )

    def generate(
            self,
            message: str,
            model: str | None = None
    ) -> dict:

        model = model or "gpt-4o-mini"

        response = self.client.chat.completions.create(
            model = model,
            messages=[
                {
                    "role": "user",
                    "content": message
                }
            ]
        )

        return{
            "provider": "openai",
            "model": model,
            "content": response.choices[0].message.content,
            "usage":{
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        }