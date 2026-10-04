import itertools
import json
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import db, usage
from app.gateway.errors import AllProvidersFailedError, UnsupportedProviderError
from app.gateway.gateway import LLMGateway
from app.pricing import cost_usd

# Providers read their API keys lazily (on first request), so loading
# .env here, after the imports, is early enough.
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once when the server starts: connect to the database, create tables.
    db.configure()
    yield


app = FastAPI(title="AI Gateway Agent Platform", version="0.1.0", lifespan=lifespan)

gateway = LLMGateway()


class ChatRequest(BaseModel):
    provider: str = Field(examples=["groq"])
    message: str = Field(examples=["Explain vector databases in one sentence."])
    # Leave out to use the provider's default model.
    model: str | None = Field(default=None, examples=[None])
    # Providers to try, in order, if the main one fails, e.g. ["claude", "groq"].
    fallbacks: list[str] = Field(default=[], examples=[["openai"]])

    # Shown as the pre-filled request in Swagger UI (/docs) instead of "string" placeholders.
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "provider": "groq",
                    "message": "Explain vector databases in one sentence.",
                    "fallbacks": ["openai"],
                }
            ]
        }
    }


@app.get("/")
def root():
    return {"message": "Ai gateway Agent Platform is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/chat")
def chat(request: ChatRequest):

    started = time.perf_counter()

    try:
        response = gateway.generate(
            provider=request.provider,
            message=request.message,
            model=request.model,
            fallbacks=request.fallbacks,
        )
    except UnsupportedProviderError as e:
        # Client asked for a provider we don't support. No provider was called,
        # so there's nothing to record.
        raise HTTPException(status_code=400, detail=str(e)) from e
    except AllProvidersFailedError as e:
        # Every provider failed after retries: missing key, bad model, outage, etc.
        _record_failure("chat", request, started, e)
        raise HTTPException(status_code=502, detail=f"Provider error: {e}") from e

    _add_cost(response)
    response["latency_ms"] = _ms_since(started)
    _record_success("chat", response, started)
    return response


@app.post("/chat/stream")
def chat_stream(request: ChatRequest):
    """Stream the answer as Server-Sent Events: `delta` events with text, then one
    `done` event with usage and routing (or an `error` event if it fails mid-stream)."""

    started = time.perf_counter()

    events = gateway.stream(
        provider=request.provider,
        message=request.message,
        model=request.model,
        fallbacks=request.fallbacks,
    )

    # Wait for the first event before sending any response. Until then retries and
    # fallback are still possible, and if everything fails we can return a real
    # 400/502 status instead of a 200 with an error hidden inside the stream.
    try:
        first = next(events)
    except UnsupportedProviderError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except AllProvidersFailedError as e:
        _record_failure("stream", request, started, e)
        raise HTTPException(status_code=502, detail=f"Provider error: {e}") from e

    return StreamingResponse(
        _sse(_track_stream(itertools.chain([first], events), request, started)),
        media_type="text/event-stream",
        # Stop proxies (e.g. nginx) from buffering the stream and caches from storing it.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _track_stream(events: Iterator[dict], request: ChatRequest, started: float) -> Iterator[dict]:
    """Pass events through unchanged (plus cost on `done`) and record the request
    once the stream ends, however it ends."""

    ttft_ms = None
    # If the loop never sees `done` or `error`, the client disconnected mid-stream.
    outcome = {"status": "cancelled", "routing": None, "error": "client disconnected"}

    try:
        for event in events:
            if event["type"] == "delta" and ttft_ms is None:
                ttft_ms = _ms_since(started)
            elif event["type"] == "done":
                _add_cost(event)
                outcome = {"status": "success", "event": event}
            elif event["type"] == "error":
                outcome = {"status": "stream_error", "routing": event["routing"]}
                outcome["error"] = event["error"]
            yield event
    finally:
        if outcome["status"] == "success":
            _record_success("stream", outcome["event"], started, ttft_ms=ttft_ms)
        else:
            routing = outcome["routing"] or {}
            usage.record_request(
                endpoint="stream",
                status=outcome["status"],
                requested_provider=request.provider,
                served_by=routing.get("served_by"),
                fallback_used=routing.get("fallback_used", False),
                attempts=routing.get("attempts", 1),
                latency_ms=_ms_since(started),
                ttft_ms=ttft_ms,
                error=outcome["error"],
            )


def _sse(events: Iterator[dict]) -> Iterator[str]:
    # SSE wire format: "event: <name>" + "data: <json>" + a blank line per event.
    for event in events:
        yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"


@app.get("/demo", include_in_schema=False)
def demo():
    """A small browser page for trying the streaming endpoint."""
    return FileResponse(Path(__file__).parent / "static" / "demo.html")


@app.get("/usage")
def get_usage(
    hours: float | None = Query(
        default=None, gt=0, description="Only count the last N hours. Omit for all time."
    ),
):
    """Request counts, success rate, tokens, cost and latency (p50/p95), overall and
    broken down by provider and by model."""
    return usage.summarize(hours)


@app.get("/usage/recent")
def get_recent_usage(limit: int = Query(default=20, ge=1, le=200)):
    """The most recent requests, newest first. Message text is never stored."""
    return usage.recent(limit)


def _ms_since(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _add_cost(result: dict) -> None:
    tokens = result["usage"]
    tokens["cost_usd"] = cost_usd(result["model"], tokens["input_tokens"], tokens["output_tokens"])


def _record_success(endpoint: str, result: dict, started: float, ttft_ms: int | None = None):
    routing = result["routing"]
    tokens = result["usage"]
    usage.record_request(
        endpoint=endpoint,
        status="success",
        requested_provider=routing["requested"],
        served_by=routing["served_by"],
        model=result["model"],
        fallback_used=routing["fallback_used"],
        attempts=routing["attempts"],
        input_tokens=tokens["input_tokens"],
        output_tokens=tokens["output_tokens"],
        total_tokens=tokens["total_tokens"],
        cost_usd=tokens["cost_usd"],
        latency_ms=_ms_since(started),
        ttft_ms=ttft_ms,
    )


def _record_failure(endpoint: str, request: ChatRequest, started: float, error: Exception):
    usage.record_request(
        endpoint=endpoint,
        status="error",
        requested_provider=request.provider,
        attempts=len(getattr(error, "attempts", [])) or 1,
        latency_ms=_ms_since(started),
        error=str(error),
    )
