from app.gateway.base import LLMProvider
from app.gateway.errors import RetryableProviderError


class FakeProvider(LLMProvider):
    """Always succeeds and echoes the message back."""

    def generate(self, message: str, model: str | None = None) -> dict:
        return {
            "provider": "fake",
            "model": model or "fake-model",
            "content": f"echo: {message}",
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        }


class BrokenProvider(LLMProvider):
    """Always fails permanently, like a provider with a bad request."""

    def __init__(self):
        self.calls = 0

    def generate(self, message: str, model: str | None = None) -> dict:
        self.calls += 1
        raise RuntimeError("upstream is down")


class FlakyProvider(FakeProvider):
    """Fails with a temporary error a few times, then succeeds."""

    failures_before_success = 2

    def __init__(self):
        self.calls = 0

    def generate(self, message: str, model: str | None = None) -> dict:
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise RetryableProviderError(f"temporary failure #{self.calls}")
        return super().generate(message, model)


class AlwaysRetryableProvider(LLMProvider):
    """Always fails with a temporary error, so it uses up every retry."""

    def __init__(self):
        self.calls = 0

    def generate(self, message: str, model: str | None = None) -> dict:
        self.calls += 1
        raise RetryableProviderError("rate limited")


class MissingKeyProvider(LLMProvider):
    """Fails while being created, like an SDK client with no API key."""

    def __init__(self):
        raise RuntimeError("missing API key")

    def generate(self, message: str, model: str | None = None) -> dict:
        raise AssertionError("never reached")
