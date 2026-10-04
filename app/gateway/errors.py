import anthropic
import openai

# Status codes that usually mean "try again later" rather than "your request is wrong".
RETRYABLE_STATUS_CODES = {408, 409, 429}


class UnsupportedProviderError(ValueError):
    """The client asked for a provider the gateway doesn't know."""


class RetryableProviderError(Exception):
    """A temporary failure. Raise this from a provider to request a retry."""


class AllProvidersFailedError(Exception):
    """Every provider in the chain failed, including all retries."""

    def __init__(self, attempts: list[dict]):
        self.attempts = attempts
        summary = "; ".join(f"{a['provider']}: {a['error']}" for a in attempts)
        super().__init__(f"All providers failed: {summary}")


def is_retryable(exc: Exception) -> bool:
    """Decide whether an error is temporary (retry) or permanent (give up)."""

    # Network problems and timeouts. The SDK timeout errors subclass APIConnectionError.
    if isinstance(
        exc,
        RetryableProviderError
        | TimeoutError
        | ConnectionError
        | openai.APIConnectionError
        | anthropic.APIConnectionError,
    ):
        return True

    # HTTP errors from the provider: 429 rate limit and 5xx server errors are temporary,
    # 400/401/403/404 mean the request itself is wrong and will fail again.
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in RETRYABLE_STATUS_CODES or status >= 500

    return False
