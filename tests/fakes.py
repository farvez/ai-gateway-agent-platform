from app.gateway.base import LLMProvider
from app.gateway.errors import RetryableProviderError

FAKE_USAGE = {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}


class FakeProvider(LLMProvider):
    """Always succeeds and echoes the message back."""

    def generate(self, message: str, model: str | None = None) -> dict:
        return {
            "provider": "fake",
            "model": model or "fake-model",
            "content": f"echo: {message}",
            "usage": FAKE_USAGE,
        }

    def stream(self, message: str, model: str | None = None):
        # Streams "echo: <message>" in three pieces.
        for piece in ["echo", ": ", message]:
            yield {"type": "delta", "text": piece}
        yield {
            "type": "done",
            "provider": "fake",
            "model": model or "fake-model",
            "usage": FAKE_USAGE,
        }


class BrokenProvider(LLMProvider):
    """Always fails permanently, like a provider with a bad request."""

    def __init__(self):
        self.calls = 0

    def generate(self, message: str, model: str | None = None) -> dict:
        self.calls += 1
        raise RuntimeError("upstream is down")

    def stream(self, message: str, model: str | None = None):
        self.calls += 1
        raise RuntimeError("upstream is down")
        yield  # makes this a generator, like a real provider's stream()


class FlakyProvider(FakeProvider):
    """Fails with a temporary error a few times, then succeeds."""

    failures_before_success = 2

    def __init__(self):
        self.calls = 0

    def _maybe_fail(self):
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise RetryableProviderError(f"temporary failure #{self.calls}")

    def generate(self, message: str, model: str | None = None) -> dict:
        self._maybe_fail()
        return super().generate(message, model)

    def stream(self, message: str, model: str | None = None):
        self._maybe_fail()
        yield from super().stream(message, model)


class AlwaysRetryableProvider(LLMProvider):
    """Always fails with a temporary error, so it uses up every retry."""

    def __init__(self):
        self.calls = 0

    def generate(self, message: str, model: str | None = None) -> dict:
        self.calls += 1
        raise RetryableProviderError("rate limited")

    def stream(self, message: str, model: str | None = None):
        self.calls += 1
        raise RetryableProviderError("rate limited")
        yield


class MissingKeyProvider(LLMProvider):
    """Fails while being created, like an SDK client with no API key."""

    def __init__(self):
        raise RuntimeError("missing API key")

    def generate(self, message: str, model: str | None = None) -> dict:
        raise AssertionError("never reached")

    def stream(self, message: str, model: str | None = None):
        raise AssertionError("never reached")


class MidStreamFailProvider(LLMProvider):
    """Starts answering, then the connection drops halfway through."""

    def __init__(self):
        self.calls = 0

    def generate(self, message: str, model: str | None = None) -> dict:
        raise AssertionError("streaming only")

    def stream(self, message: str, model: str | None = None):
        self.calls += 1
        yield {"type": "delta", "text": "partial "}
        raise RetryableProviderError("connection dropped")
