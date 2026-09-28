from .base import LLMProvider
from .claude_provider import ClaudeProvider
from .groq_provider import GroqProvider
from .openai_provider import OpenAIProvider

class LLMGateway:

    def __init__(self):

        # Store classes, not instances: a provider is only created the first
        # time it is requested, so a missing API key for one provider
        # doesn't stop the whole app from starting.
        self.provider_classes: dict[str, type[LLMProvider]] = {
            "openai": OpenAIProvider,
            "claude": ClaudeProvider,
            "groq": GroqProvider
        }
        self._instances: dict[str, LLMProvider] = {}

    def get_provider(self, provider: str) -> LLMProvider:

        if provider not in self.provider_classes:
            raise ValueError(
                f"Unsupported provider: {provider}. "
                f"Choose from: {', '.join(self.provider_classes)}"
            )

        if provider not in self._instances:
            self._instances[provider] = self.provider_classes[provider]()

        return self._instances[provider]

    def generate(
            self,
            provider:str,
            message:str,
            model: str | None = None
    ) -> dict:

        return self.get_provider(provider).generate(
            message= message,
            model = model
        )
