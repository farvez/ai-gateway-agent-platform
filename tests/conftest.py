import pytest
from fastapi.testclient import TestClient

from app import auth, db, limits
from app.db import SessionLocal
from app.gateway.gateway import LLMGateway
from app.main import app, gateway
from app.models import Team
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
def database():
    """A fresh, empty in-memory database for each test."""
    engine = db.configure("sqlite://")
    yield engine
    engine.dispose()


ADMIN_KEY = "test-admin-key"
ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_KEY}"}


def create_team(name: str = "test-team", **limits_) -> int:
    with SessionLocal() as session:
        team = Team(name=name, **limits_)
        session.add(team)
        session.commit()
        return team.id


def key_headers(team_id: int) -> dict:
    _, plain = auth.issue_key(team_id)
    return {"Authorization": f"Bearer {plain}"}


@pytest.fixture
def team_id(database) -> int:
    """A team with no budget or rate limit."""
    return create_team()


@pytest.fixture
def anon_client(monkeypatch, database):
    """A test client that sends no API key."""
    # Replace the real providers with fakes for this test only.
    monkeypatch.setattr(gateway, "provider_classes", dict(FAKE_PROVIDERS))
    monkeypatch.setattr(gateway, "_instances", {})
    # Don't really wait between retries.
    monkeypatch.setattr(gateway, "_sleep", lambda seconds: None)
    # Fresh rate-limit counters, and a known admin key.
    monkeypatch.setattr(limits, "limiter", limits.RateLimiter())
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    return TestClient(app)


@pytest.fixture
def client(anon_client, team_id):
    """A test client that sends a valid key for `team_id` on every request."""
    anon_client.headers.update(key_headers(team_id))
    return anon_client


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
