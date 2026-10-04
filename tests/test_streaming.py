import json

import pytest

from app.gateway.errors import AllProvidersFailedError, UnsupportedProviderError


def text_of(events: list[dict]) -> str:
    return "".join(e["text"] for e in events if e["type"] == "delta")


def parse_sse(body: str) -> list[dict]:
    """Turn an SSE response body back into a list of event dicts."""
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        event = json.loads(lines["data"])
        assert lines["event"] == event["type"]
        events.append(event)
    return events


# ---------- gateway.stream() ----------


def test_stream_yields_deltas_then_done(make_gateway):
    gw = make_gateway()

    events = list(gw.stream("fake", "hi"))

    assert [e["type"] for e in events] == ["delta", "delta", "delta", "done"]
    assert text_of(events) == "echo: hi"
    assert events[-1]["usage"]["total_tokens"] == 3
    assert events[-1]["routing"]["served_by"] == "fake"


def test_stream_retries_before_first_token(make_gateway, sleeps):
    gw = make_gateway(max_retries=2)

    events = list(gw.stream("flaky", "hi"))

    assert text_of(events) == "echo: hi"
    assert gw._instances["flaky"].calls == 3
    assert len(sleeps) == 2
    assert events[-1]["routing"]["attempts"] == 3


def test_stream_falls_back_before_first_token(make_gateway):
    gw = make_gateway()

    events = list(gw.stream("broken", "hi", fallbacks=["fake"]))

    assert text_of(events) == "echo: hi"
    assert events[-1]["routing"]["served_by"] == "fake"
    assert events[-1]["routing"]["fallback_used"] is True


def test_mid_stream_failure_does_not_fall_back(make_gateway):
    gw = make_gateway(max_retries=2)

    events = list(gw.stream("midfail", "hi", fallbacks=["fake"]))

    # The client already received "partial ", so switching to "fake" would mix two answers.
    assert [e["type"] for e in events] == ["delta", "error"]
    assert events[0]["text"] == "partial "
    assert "connection dropped" in events[1]["error"]
    assert events[1]["routing"]["served_by"] == "midfail"
    assert gw._instances["midfail"].calls == 1  # not retried either
    assert "fake" not in gw._instances


def test_stream_all_providers_fail(make_gateway):
    gw = make_gateway(max_retries=0)

    with pytest.raises(AllProvidersFailedError):
        list(gw.stream("broken", "hi", fallbacks=["nokey"]))


def test_stream_unknown_provider(make_gateway):
    gw = make_gateway()

    with pytest.raises(UnsupportedProviderError):
        list(gw.stream("banana", "hi"))


# ---------- POST /chat/stream ----------


def test_stream_endpoint_sends_sse(client):
    response = client.post("/chat/stream", json={"provider": "fake", "message": "hi"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(response.text)
    assert text_of(events) == "echo: hi"
    assert events[-1]["type"] == "done"
    assert events[-1]["routing"]["served_by"] == "fake"


def test_stream_endpoint_fallback(client):
    payload = {"provider": "broken", "message": "hi", "fallbacks": ["fake"]}

    response = client.post("/chat/stream", json=payload)

    assert response.status_code == 200
    assert parse_sse(response.text)[-1]["routing"]["fallback_used"] is True


def test_stream_endpoint_returns_502_when_nothing_starts(client):
    response = client.post("/chat/stream", json={"provider": "broken", "message": "hi"})

    # A real error status, not a 200 with an error hidden in the stream.
    assert response.status_code == 502
    assert "upstream is down" in response.json()["detail"]


def test_stream_endpoint_unknown_provider_returns_400(client):
    response = client.post("/chat/stream", json={"provider": "banana", "message": "hi"})

    assert response.status_code == 400


def test_stream_endpoint_mid_stream_error_event(client):
    response = client.post("/chat/stream", json={"provider": "midfail", "message": "hi"})

    # Headers were already sent with 200, so the failure arrives as an error event.
    assert response.status_code == 200
    events = parse_sse(response.text)
    assert events[-1]["type"] == "error"


def test_demo_page(client):
    response = client.get("/demo")

    assert response.status_code == 200
    assert "/chat/stream" in response.text
