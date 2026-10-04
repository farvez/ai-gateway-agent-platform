import itertools
import json
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.gateway.errors import AllProvidersFailedError, UnsupportedProviderError
from app.gateway.gateway import LLMGateway

# Providers read their API keys lazily (on first request), so loading
# .env here, after the imports, is early enough.
load_dotenv()

app = FastAPI(title="AI Gateway Agent Platform", version="0.1.0")

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

    try:
        response = gateway.generate(
            provider=request.provider,
            message=request.message,
            model=request.model,
            fallbacks=request.fallbacks,
        )
    except UnsupportedProviderError as e:
        # Client asked for a provider we don't support.
        raise HTTPException(status_code=400, detail=str(e)) from e
    except AllProvidersFailedError as e:
        # Every provider failed after retries: missing key, bad model, outage, etc.
        raise HTTPException(status_code=502, detail=f"Provider error: {e}") from e

    return response


@app.post("/chat/stream")
def chat_stream(request: ChatRequest):
    """Stream the answer as Server-Sent Events: `delta` events with text, then one
    `done` event with usage and routing (or an `error` event if it fails mid-stream)."""

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
        raise HTTPException(status_code=502, detail=f"Provider error: {e}") from e

    return StreamingResponse(
        _sse(itertools.chain([first], events)),
        media_type="text/event-stream",
        # Stop proxies (e.g. nginx) from buffering the stream and caches from storing it.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(events: Iterator[dict]) -> Iterator[str]:
    # SSE wire format: "event: <name>" + "data: <json>" + a blank line per event.
    for event in events:
        yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"


@app.get("/demo", include_in_schema=False)
def demo():
    """A small browser page for trying the streaming endpoint."""
    return FileResponse(Path(__file__).parent / "static" / "demo.html")
