from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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
