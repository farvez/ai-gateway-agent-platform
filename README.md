# AI Gateway Agent Platform

[![CI](https://github.com/farvez/ai-gateway-agent-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/farvez/ai-gateway-agent-platform/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.13-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230)

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
- **Retries with exponential backoff** on temporary errors (429, 5xx, timeouts, dropped connections) — permanent errors like a bad key fail fast
- **Automatic fallback** across providers (e.g. OpenAI → Claude → Groq), with routing details in every response
- **Request timeouts** so a slow provider can't hang the API
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
│   ├── config.py               # Timeout / retry settings from environment
│   └── gateway/
│       ├── base.py             # LLMProvider abstract base class
│       ├── gateway.py          # LLMGateway – registry, retries, fallback
│       ├── errors.py           # Error types & retryable-vs-permanent classification
│       ├── openai_provider.py  # OpenAI implementation
│       ├── claude_provider.py  # Anthropic Claude implementation
│       └── groq_provider.py    # Groq implementation (OpenAI-compatible API)
├── tests/                      # pytest suite with fake providers
├── .github/workflows/ci.yml    # Lint + tests on every push
├── .env.example
├── requirements.txt
├── requirements-dev.txt
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

Optional reliability settings (defaults shown):

| Variable | Default | Meaning |
|---|---|---|
| `LLM_TIMEOUT_SECONDS` | `30` | Max seconds for one provider call |
| `LLM_MAX_RETRIES` | `2` | Extra attempts per provider on temporary errors |
| `LLM_RETRY_BASE_DELAY` | `0.5` | First retry delay; doubles each retry (±10% jitter) |

### Run

```bash
uvicorn app.main:app --reload
```

Open **http://localhost:8000/docs** for the interactive Swagger UI.

## Development

```bash
pip install -r requirements-dev.txt   # app + pytest + ruff
pytest -v                             # run tests (no API keys needed - providers are mocked)
ruff check .                          # lint
ruff format .                         # auto-format
```

Every push and pull request runs lint, format check and tests on GitHub Actions.

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
  "model": "claude-sonnet-5",
  "fallbacks": ["openai", "groq"]
}
```

`provider` — `openai` | `claude` | `groq`  
`model` — optional; defaults to `gpt-4o-mini` (OpenAI), `claude-sonnet-5` (Claude) or `llama-3.3-70b-versatile` (Groq). Applies to the primary provider only — fallbacks use their own default model.  
`fallbacks` — optional; providers to try in order if the primary one fails after its retries

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
  },
  "routing": {
    "requested": "claude",
    "served_by": "claude",
    "fallback_used": false,
    "attempts": 1,
    "failures": []
  }
}
```

**Errors**

| Status | When |
|---|---|
| `400` | Unknown provider in `provider` or `fallbacks` (checked before any call is made) |
| `502` | Every provider in the chain failed; `detail` lists each failure |

### How retries and fallback work

```
request(openai, fallbacks=[claude, groq])
  openai  ─ try ─✗ wait ~0.5s ─ try ─✗ wait ~1s ─ try ─✗   (429 / 5xx / timeout → retry)
  claude  ─ try ─✗ 401 bad key                             (permanent → skip retries)
  groq    ─ try ─✓  → routing.served_by = "groq"
```

The provider SDKs' built-in retries are disabled (`max_retries=0`) so the gateway is the single place retry policy lives.

**cURL**

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"provider": "openai", "message": "Hello!", "fallbacks": ["claude", "groq"]}'
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
- [x] Retries with exponential backoff, cross-provider fallback, timeouts
- [ ] Gemini provider
- [ ] Streaming responses (Server-Sent Events)
- [ ] Cost tracking per request and per API key
- [ ] Response caching (Redis)
- [ ] Rate limiting & API-key authentication
- [ ] Request logging & usage dashboard (PostgreSQL)
- [ ] Agent layer: tool calling and multi-step workflows
- [x] pytest suite with mocked providers, ruff, GitHub Actions CI
- [ ] Docker + docker-compose

## Tech stack

Python · FastAPI · Pydantic · Uvicorn · OpenAI SDK · Anthropic SDK · python-dotenv

## License

MIT
