import pytest
from fastapi.testclient import TestClient

from app.gateway.gateway import LLMGateway
from app.main import app, gateway
from tests.fakes import (
    AlwaysRetryableProvider,
    BrokenProvider,
    FakeProvider,
    FlakyProvider,
    MidStreamFailProvider,
    MissingKeyProvider,
)

FAKE_PROVIDERS = {
    "fake": FakeProvider,
    "broken": BrokenProvider,
    "flaky": FlakyProvider,
    "retryable": AlwaysRetryableProvider,
    "nokey": MissingKeyProvider,
    "midfail": MidStreamFailProvider,
}


@pytest.fixture
def client(monkeypatch):
    # Replace the real providers with fakes for this test only.
    monkeypatch.setattr(gateway, "provider_classes", dict(FAKE_PROVIDERS))
    monkeypatch.setattr(gateway, "_instances", {})
    # Don't really wait between retries.
    monkeypatch.setattr(gateway, "_sleep", lambda seconds: None)
    return TestClient(app)


@pytest.fixture
def sleeps():
    """Collects every backoff delay instead of sleeping."""
    return []


@pytest.fixture
def make_gateway(sleeps):
    """Builds a fresh LLMGateway wired to the fake providers, for testing without HTTP."""

    def _make(max_retries: int = 2, base_delay: float = 0.5) -> LLMGateway:
        gw = LLMGateway()
        gw.provider_classes = dict(FAKE_PROVIDERS)
        gw.max_retries = max_retries
        gw.retry_base_delay = base_delay
        gw._sleep = sleeps.append
        return gw

    return _make
