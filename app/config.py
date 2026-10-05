import os

# Settings are read from the environment at call time (not import time),
# so values from .env are picked up after load_dotenv() runs.


def request_timeout() -> float:
    """Seconds to wait for a single provider call before giving up."""
    return float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))


def max_retries() -> int:
    """Extra attempts per provider after the first one fails with a retryable error."""
    return int(os.getenv("LLM_MAX_RETRIES", "2"))


def retry_base_delay() -> float:
    """Delay before the first retry; doubles on every following retry."""
    return float(os.getenv("LLM_RETRY_BASE_DELAY", "0.5"))


def default_model(provider: str, fallback: str) -> str:
    """Default model for a provider, overridable with e.g. GROQ_MODEL=... in .env.

    Providers retire models regularly; this lets you switch without a code change.
    """
    return os.getenv(f"{provider.upper()}_MODEL") or fallback


def max_output_tokens() -> int:
    """Upper limit on the length of every answer, so one request can't run up a big bill."""
    return int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "1024"))


def max_input_chars() -> int:
    """Longest message accepted, in characters (roughly 4 characters per token)."""
    return int(os.getenv("MAX_INPUT_CHARS", "20000"))
