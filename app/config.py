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
