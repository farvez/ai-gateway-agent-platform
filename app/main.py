from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.gateway.errors import AllProvidersFailedError, UnsupportedProviderError
from app.gateway.gateway import LLMGateway

# Providers read their API keys lazily (on first request), so loading
# .env here, after the imports, is early enough.
load_dotenv()

app = FastAPI(title="AI Gateway Agent Platform", version="0.1.0")

gateway = LLMGateway()


class ChatRequest(BaseModel):
    provider: str
    message: str
    model: str | None = None
    # Providers to try, in order, if the main one fails, e.g. ["claude", "groq"].
    fallbacks: list[str] = []


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
