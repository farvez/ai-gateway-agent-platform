import anthropic
import httpx
import openai
import pytest

from app.gateway.errors import (
    AllProvidersFailedError,
    RetryableProviderError,
    UnsupportedProviderError,
    is_retryable,
)

# ---------- retries ----------


def test_retries_until_success(make_gateway, sleeps):
    gw = make_gateway(max_retries=2)

    response = gw.generate("flaky", "hi")

    assert response["content"] == "echo: hi"
    assert gw._instances["flaky"].calls == 3  # 2 failures + 1 success
    assert response["routing"]["attempts"] == 3
    assert response["routing"]["fallback_used"] is False


def test_backoff_delays_grow_exponentially(make_gateway, sleeps):
    gw = make_gateway(max_retries=2, base_delay=0.5)

    gw.generate("flaky", "hi")

    # Two retries: ~0.5s then ~1.0s (each +/-10% jitter).
    assert len(sleeps) == 2
    assert 0.45 <= sleeps[0] <= 0.55
    assert 0.9 <= sleeps[1] <= 1.1


def test_gives_up_after_max_retries(make_gateway, sleeps):
    gw = make_gateway(max_retries=2)

    with pytest.raises(AllProvidersFailedError) as exc_info:
        gw.generate("retryable", "hi")

    assert gw._instances["retryable"].calls == 3  # first try + 2 retries
    assert len(exc_info.value.attempts) == 3


def test_permanent_error_is_not_retried(make_gateway, sleeps):
    gw = make_gateway(max_retries=2)

    with pytest.raises(AllProvidersFailedError):
        gw.generate("broken", "hi")

    assert gw._instances["broken"].calls == 1
    assert sleeps == []


# ---------- fallback ----------


def test_falls_back_to_next_provider(make_gateway):
    gw = make_gateway()

    response = gw.generate("broken", "hi", fallbacks=["fake"])

    assert response["content"] == "echo: hi"
    assert response["routing"]["requested"] == "broken"
    assert response["routing"]["served_by"] == "fake"
    assert response["routing"]["fallback_used"] is True
    assert response["routing"]["failures"] == [{"provider": "broken", "error": "upstream is down"}]


def test_falls_back_when_provider_cannot_be_created(make_gateway):
    gw = make_gateway()

    response = gw.generate("nokey", "hi", fallbacks=["fake"])

    assert response["routing"]["served_by"] == "fake"
    assert "missing API key" in response["routing"]["failures"][0]["error"]


def test_model_override_only_applies_to_primary(make_gateway):
    gw = make_gateway()

    response = gw.generate("broken", "hi", model="gpt-x", fallbacks=["fake"])

    # The fallback must use its own default, not another provider's model name.
    assert response["model"] == "fake-model"


def test_all_providers_fail(make_gateway):
    gw = make_gateway(max_retries=1)

    with pytest.raises(AllProvidersFailedError) as exc_info:
        gw.generate("broken", "hi", fallbacks=["retryable"])

    providers_tried = [a["provider"] for a in exc_info.value.attempts]
    assert providers_tried == ["broken", "retryable", "retryable"]


def test_unknown_fallback_is_rejected_before_any_call(make_gateway):
    gw = make_gateway()

    with pytest.raises(UnsupportedProviderError, match="banana"):
        gw.generate("fake", "hi", fallbacks=["banana"])

    assert gw._instances == {}


# ---------- error classification ----------


def _status_error(sdk, status: int) -> Exception:
    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(status, request=request)
    return sdk.APIStatusError("error", response=response, body=None)


@pytest.mark.parametrize("sdk", [openai, anthropic])
@pytest.mark.parametrize(
    ("status", "expected"),
    [(429, True), (500, True), (503, True), (400, False), (401, False), (404, False)],
)
def test_status_codes(sdk, status, expected):
    assert is_retryable(_status_error(sdk, status)) is expected


@pytest.mark.parametrize("sdk", [openai, anthropic])
def test_timeouts_and_connection_errors_are_retryable(sdk):
    request = httpx.Request("POST", "https://example.com")

    assert is_retryable(sdk.APITimeoutError(request=request))
    assert is_retryable(sdk.APIConnectionError(request=request))


def test_other_errors():
    assert is_retryable(RetryableProviderError("x"))
    assert is_retryable(TimeoutError())
    assert not is_retryable(RuntimeError("bug"))


# ---------- config ----------


def test_default_model_can_be_overridden_by_env(monkeypatch):
    from app.config import default_model

    assert default_model("groq", "built-in") == "built-in"

    monkeypatch.setenv("GROQ_MODEL", "from-env")
    assert default_model("groq", "built-in") == "from-env"
