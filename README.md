# AI Gateway Agent Platform

A unified **LLM gateway** built with FastAPI that routes chat requests to multiple AI providers (OpenAI, Anthropic Claude, Groq) through a single, consistent API — with normalized responses and token-usage reporting.

> One endpoint. Any model. Same response shape.

---

## Why

Every LLM provider ships a different SDK, request format and response schema. Applications that want to switch models, compare providers, or fall back when one is down end up littered with provider-specific code. This gateway puts that behind one interface.

## Features

- **Single `/chat` endpoint** for every provider
- **Pluggable provider architecture** — each provider implements the `LLMProvider` abstract base class
- **Normalized responses** — same JSON shape (`provider`, `model`, `content`, `usage`) regardless of backend
- **Token usage tracking** — input / output / total tokens returned on every call
- **Per-request model override** with sensible defaults per provider
- **Health check** endpoint for load balancers and uptime monitors
- **Auto-generated OpenAPI docs** at `/docs`

## Architecture

```
            ┌──────────────┐
 Client ──► │   FastAPI    │  POST /chat {provider, message, model?}
            │   app/main   │
            └──────┬───────┘
                   │
            ┌──────▼───────┐
            │  LLMGateway  │  looks up provider in registry
            └──────┬───────┘
        ┌──────────┼───────────┐
 ┌──────▼─────┐ ┌──▼─────────┐ ┌▼───────────┐
 │  OpenAI    │ │  Claude    │ │   Groq     │   each implements
 │  Provider  │ │  Provider  │ │  Provider  │   LLMProvider.generate()
 └────────────┘ └────────────┘ └────────────┘
```

## Project structure

```
ai-gateway-agent-platform/
├── app/
│   ├── main.py                 # FastAPI app & routes
│   └── gateway/
│       ├── base.py             # LLMProvider abstract base class
│       ├── gateway.py          # LLMGateway – provider registry & routing
│       ├── openai_provider.py  # OpenAI implementation
│       ├── claude_provider.py  # Anthropic Claude implementation
│       └── groq_provider.py    # Groq implementation (OpenAI-compatible API)
├── .env.example
├── requirements.txt
└── README.md
```

## Getting started

### Prerequisites

- Python 3.10+
- API keys for the providers you want to use

### Install

```bash
git clone https://github.com/farvez/ai-gateway-agent-platform.git
cd ai-gateway-agent-platform
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
```

Fill in the keys in `.env`:

```env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=gsk_...
GOOGLE_API_KEY=
```

### Run

```bash
uvicorn app.main:app --reload
```

Open **http://localhost:8000/docs** for the interactive Swagger UI.

## API

| Method | Path      | Description                      |
|--------|-----------|----------------------------------|
| GET    | `/`       | Service info                     |
| GET    | `/health` | Health check                     |
| POST   | `/chat`   | Send a message to a provider     |

### `POST /chat`

**Request**

```json
{
  "provider": "claude",
  "message": "Explain vector databases in one sentence.",
  "model": "claude-sonnet-5"
}
```

`provider` — `openai` | `claude` | `groq`  
`model` — optional; defaults to `gpt-4o-mini` (OpenAI), `claude-sonnet-5` (Claude) or `llama-3.3-70b-versatile` (Groq)

**Response**

```json
{
  "provider": "anthropic",
  "model": "claude-sonnet-5",
  "content": "A vector database stores embeddings and retrieves them by similarity...",
  "usage": {
    "input_tokens": 14,
    "output_tokens": 32,
    "total_tokens": 46
  }
}
```

**cURL**

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"provider": "openai", "message": "Hello!"}'
```

## Adding a new provider

1. Create `app/gateway/<name>_provider.py` and subclass `LLMProvider`.
2. Implement `generate(message, model=None) -> dict` returning the normalized shape.
3. Register the class (not an instance) in `LLMGateway.__init__` — it is created lazily on first use:

```python
self.provider_classes["gemini"] = GeminiProvider
```

## Roadmap

- [x] Groq provider
- [ ] Gemini provider
- [ ] Streaming responses (Server-Sent Events)
- [ ] Automatic fallback & retries when a provider fails
- [ ] Cost tracking per request and per API key
- [ ] Response caching (Redis)
- [ ] Rate limiting & API-key authentication
- [ ] Request logging & usage dashboard (PostgreSQL)
- [ ] Agent layer: tool calling and multi-step workflows
- [ ] Docker + docker-compose, GitHub Actions CI, pytest suite

## Tech stack

Python · FastAPI · Pydantic · Uvicorn · OpenAI SDK · Anthropic SDK · python-dotenv

## License

MIT
