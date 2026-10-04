import random
import time
from collections.abc import Callable, Iterator
from typing import TypeVar

from app import config

from .base import LLMProvider
from .claude_provider import ClaudeProvider
from .errors import AllProvidersFailedError, UnsupportedProviderError, is_retryable
from .groq_provider import GroqProvider
from .openai_provider import OpenAIProvider

T = TypeVar("T")


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

        chain = self._resolve_chain(provider, fallbacks)
        attempts: list[dict] = []

        for index, name in enumerate(chain):
            provider_model = _model_for(index, model)

            def call(name=name, provider_model=provider_model):
                return self.get_provider(name).generate(message=message, model=provider_model)

            try:
                response = self._with_retries(name, attempts, call)
            except Exception:
                # This provider is out of retries (or failed permanently); try the next one.
                continue

            response["routing"] = _routing(provider, name, index, attempts)
            return response

        raise AllProvidersFailedError(attempts)

    def stream(
        self,
        provider: str,
        message: str,
        model: str | None = None,
        fallbacks: list[str] | None = None,
    ) -> Iterator[dict]:
        """Stream events from the first provider that manages to start answering.

        Retries and fallback only happen *before* the first event arrives. Once text
        has been sent to the client, switching provider would glue two different
        answers together, so a mid-stream failure ends the stream with an error event.
        """

        chain = self._resolve_chain(provider, fallbacks)
        attempts: list[dict] = []

        for index, name in enumerate(chain):
            provider_model = _model_for(index, model)

            def open_stream(name=name, provider_model=provider_model):
                events = iter(self.get_provider(name).stream(message=message, model=provider_model))
                # Pull the first event now: this is when the provider is actually called,
                # so connection errors, bad keys and rate limits surface here.
                first = next(events, None)
                if first is None:
                    raise RuntimeError("provider returned an empty stream")
                return first, events

            try:
                first, events = self._with_retries(name, attempts, open_stream)
            except Exception:
                continue

            routing = _routing(provider, name, index, attempts)
            yield _attach_routing(first, routing)

            try:
                for event in events:
                    yield _attach_routing(event, routing)
            except Exception as e:
                yield {"type": "error", "error": str(e), "routing": routing}
            return

        raise AllProvidersFailedError(attempts)

    def _resolve_chain(self, provider: str, fallbacks: list[str] | None) -> list[str]:

        chain = [provider, *(fallbacks or [])]

        # Validate the whole chain up front, so a typo is a 400 before any call is made.
        unknown = [name for name in chain if name not in self.provider_classes]
        if unknown:
            raise UnsupportedProviderError(
                f"Unsupported provider: {', '.join(unknown)}. "
                f"Choose from: {', '.join(self.provider_classes)}"
            )

        return chain

    def _with_retries(self, name: str, attempts: list[dict], call: Callable[[], T]) -> T:

        for attempt in range(self.max_retries + 1):
            try:
                return call()
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


def _model_for(index: int, model: str | None) -> str | None:
    # Model names are provider-specific, so an override only applies to the
    # primary provider. Fallbacks use their own default model.
    return model if index == 0 else None


def _routing(requested: str, served_by: str, index: int, attempts: list[dict]) -> dict:
    return {
        "requested": requested,
        "served_by": served_by,
        "fallback_used": index > 0,
        "attempts": len(attempts) + 1,
        "failures": attempts,
    }


def _attach_routing(event: dict, routing: dict) -> dict:
    # Routing info rides along on the final event only, to keep deltas small.
    if event.get("type") == "done":
        return {**event, "routing": routing}
    return event
