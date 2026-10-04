import random
import time

from app import config

from .base import LLMProvider
from .claude_provider import ClaudeProvider
from .errors import AllProvidersFailedError, UnsupportedProviderError, is_retryable
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
            "groq": GroqProvider,
        }
        self._instances: dict[str, LLMProvider] = {}

        self.max_retries = config.max_retries()
        self.retry_base_delay = config.retry_base_delay()
        # Swappable so tests can skip real waiting.
        self._sleep = time.sleep

    def get_provider(self, provider: str) -> LLMProvider:

        if provider not in self._instances:
            self._instances[provider] = self.provider_classes[provider]()

        return self._instances[provider]

    def generate(
        self,
        provider: str,
        message: str,
        model: str | None = None,
        fallbacks: list[str] | None = None,
    ) -> dict:

        chain = [provider, *(fallbacks or [])]

        # Validate the whole chain up front, so a typo is a 400 before any call is made.
        unknown = [name for name in chain if name not in self.provider_classes]
        if unknown:
            raise UnsupportedProviderError(
                f"Unsupported provider: {', '.join(unknown)}. "
                f"Choose from: {', '.join(self.provider_classes)}"
            )

        attempts: list[dict] = []

        for index, name in enumerate(chain):
            # Model names are provider-specific, so an override only applies to the
            # primary provider. Fallbacks use their own default model.
            provider_model = model if index == 0 else None

            try:
                response = self._generate_with_retries(name, message, provider_model, attempts)
            except Exception:
                # This provider is out of retries (or failed permanently); try the next one.
                continue

            response["routing"] = {
                "requested": provider,
                "served_by": name,
                "fallback_used": index > 0,
                "attempts": len(attempts) + 1,
                "failures": attempts,
            }
            return response

        raise AllProvidersFailedError(attempts)

    def _generate_with_retries(
        self, name: str, message: str, model: str | None, attempts: list[dict]
    ) -> dict:

        for attempt in range(self.max_retries + 1):
            try:
                return self.get_provider(name).generate(message=message, model=model)
            except Exception as e:
                attempts.append({"provider": name, "error": str(e)})

                last_attempt = attempt == self.max_retries
                if not is_retryable(e) or last_attempt:
                    raise

                self._sleep(self._backoff_delay(attempt))

        raise AssertionError("unreachable")

    def _backoff_delay(self, attempt: int) -> float:
        # Exponential backoff: base, 2x base, 4x base, ... with +/-10% jitter so that
        # many clients retrying at once don't all hit the provider at the same moment.
        delay = self.retry_base_delay * (2**attempt)
        return delay * random.uniform(0.9, 1.1)
