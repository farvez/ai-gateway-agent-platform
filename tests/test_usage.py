from datetime import UTC, datetime, timedelta

import pytest

from app import usage
from app.db import SessionLocal
from app.models import RequestLog
from app.pricing import cost_usd
from tests.test_streaming import parse_sse

# FakeProvider reports 1 input + 2 output tokens. Passing a real model name makes it
# echo that name back, so the price table applies.
PRICED = {"provider": "fake", "message": "hi", "model": "gpt-4o-mini"}
GPT_4O_MINI_COST = 1 * 0.15 / 1_000_000 + 2 * 0.60 / 1_000_000


def recent(client) -> list[dict]:
    return client.get("/usage/recent").json()


# ---------- pricing ----------


def test_cost_for_known_model():
    # 1M input + 1M output tokens of gpt-4o-mini = $0.15 + $0.60
    assert cost_usd("gpt-4o-mini", 1_000_000, 1_000_000) == pytest.approx(0.75)


def test_cost_for_unknown_model_is_none():
    assert cost_usd("some-new-model", 100, 100) is None


# ---------- /chat ----------


def test_chat_response_includes_cost_and_latency(client):
    body = client.post("/chat", json=PRICED).json()

    assert body["usage"]["cost_usd"] == pytest.approx(GPT_4O_MINI_COST)
    assert body["latency_ms"] >= 0


def test_chat_success_is_recorded(client):
    client.post("/chat", json=PRICED)

    [row] = recent(client)
    assert row["endpoint"] == "chat"
    assert row["status"] == "success"
    assert row["served_by"] == "fake"
    assert row["model"] == "gpt-4o-mini"
    assert row["total_tokens"] == 3
    assert row["cost_usd"] == pytest.approx(GPT_4O_MINI_COST)
    assert row["error"] is None


def test_message_text_is_never_stored(client):
    client.post("/chat", json={"provider": "fake", "message": "my secret password"})

    [row] = recent(client)
    assert not any("secret" in str(value) for value in row.values())


def test_chat_failure_is_recorded(client):
    client.post("/chat", json={"provider": "broken", "message": "hi"})

    [row] = recent(client)
    assert row["status"] == "error"
    assert row["requested_provider"] == "broken"
    assert row["served_by"] is None
    assert "upstream is down" in row["error"]


def test_unknown_provider_is_not_recorded(client):
    client.post("/chat", json={"provider": "banana", "message": "hi"})

    assert recent(client) == []


def test_fallback_is_recorded(client):
    client.post("/chat", json={"provider": "broken", "message": "hi", "fallbacks": ["fake"]})

    [row] = recent(client)
    assert row["status"] == "success"
    assert row["requested_provider"] == "broken"
    assert row["served_by"] == "fake"
    assert row["fallback_used"] is True
    assert row["attempts"] == 2


def test_recording_failure_does_not_break_the_request(client, monkeypatch):
    def broken_session():
        raise RuntimeError("database is down")

    monkeypatch.setattr(usage, "SessionLocal", broken_session)

    response = client.post("/chat", json=PRICED)

    assert response.status_code == 200


# ---------- /chat/stream ----------


def test_stream_success_is_recorded_with_ttft(client):
    response = client.post("/chat/stream", json=PRICED)

    done = parse_sse(response.text)[-1]
    assert done["usage"]["cost_usd"] == pytest.approx(GPT_4O_MINI_COST)

    [row] = recent(client)
    assert row["endpoint"] == "stream"
    assert row["status"] == "success"
    assert row["ttft_ms"] is not None
    assert row["total_tokens"] == 3


def test_mid_stream_failure_is_recorded(client):
    client.post("/chat/stream", json={"provider": "midfail", "message": "hi"})

    [row] = recent(client)
    assert row["status"] == "stream_error"
    assert row["served_by"] == "midfail"
    assert "connection dropped" in row["error"]


def test_stream_that_never_starts_is_recorded(client):
    client.post("/chat/stream", json={"provider": "broken", "message": "hi"})

    [row] = recent(client)
    assert row["endpoint"] == "stream"
    assert row["status"] == "error"


# ---------- /usage ----------


def test_usage_summary(client):
    client.post("/chat", json=PRICED)
    client.post("/chat", json=PRICED)
    client.post("/chat", json={"provider": "broken", "message": "hi", "fallbacks": ["fake"]})
    client.post("/chat", json={"provider": "broken", "message": "hi"})

    summary = client.get("/usage").json()
    totals = summary["totals"]

    assert totals["requests"] == 4
    assert totals["failures"] == 1
    assert totals["success_rate"] == 0.75
    assert totals["fallbacks"] == 1
    assert totals["total_tokens"] == 9  # 3 successful requests x 3 tokens
    assert totals["cost_usd"] == pytest.approx(2 * GPT_4O_MINI_COST)  # fake-model has no price
    assert totals["latency_ms"]["p50"] is not None

    by_provider = {row["provider"]: row for row in summary["by_provider"]}
    assert by_provider["fake"]["requests"] == 3
    assert by_provider["broken"]["failures"] == 1

    by_model = {row["model"]: row for row in summary["by_model"]}
    assert by_model["gpt-4o-mini"]["requests"] == 2


def test_usage_summary_when_empty(client):
    totals = client.get("/usage").json()["totals"]

    assert totals["requests"] == 0
    assert totals["success_rate"] is None
    assert totals["latency_ms"] == {"p50": None, "p95": None}


def test_usage_hours_filter(client):
    with SessionLocal() as session:
        session.add(
            RequestLog(
                endpoint="chat",
                status="success",
                requested_provider="fake",
                served_by="fake",
                latency_ms=100,
                created_at=datetime.now(UTC) - timedelta(hours=48),
            )
        )
        session.commit()
    client.post("/chat", json=PRICED)

    assert client.get("/usage").json()["totals"]["requests"] == 2
    assert client.get("/usage?hours=24").json()["totals"]["requests"] == 1


def test_percentiles():
    values = list(range(1, 101))  # 1..100

    assert usage._percentiles(values) == {"p50": 50, "p95": 95}
    assert usage._percentiles([7]) == {"p50": 7, "p95": 7}
