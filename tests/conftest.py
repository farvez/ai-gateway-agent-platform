import pytest
from fastapi.testclient import TestClient

from app.gateway.base import LLMProvider
from app.main import app, gateway


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
    """Always fails, like a provider that is down."""

    def generate(self, message: str, model: str | None = None) -> dict:
        raise RuntimeError("upstream is down")


@pytest.fixture
def client(monkeypatch):
    # Replace the real providers with fakes for this test only.
    monkeypatch.setattr(gateway, "provider_classes", {
        "fake": FakeProvider,
        "broken": BrokenProvider,
    })
    monkeypatch.setattr(gateway, "_instances", {})
    return TestClient(app)
