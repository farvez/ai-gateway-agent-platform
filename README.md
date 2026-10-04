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
- **Streaming** via Server-Sent Events (`/chat/stream`) — tokens appear as they're generated, with a browser demo at `/demo`
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
│       └── groq_provider.py    # Groq – subclass of OpenAIProvider (OpenAI-compatible API)
│   └── static/demo.html        # Browser demo for streaming
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
| `OPENAI_MODEL` / `ANTHROPIC_MODEL` / `GROQ_MODEL` | built-in | Default model per provider (providers retire models — change it here, no code edit) |

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
| POST   | `/chat/stream` | Same request, streamed as Server-Sent Events |
| GET    | `/demo`   | Browser page for trying streaming |

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
`model` — optional; defaults to `gpt-4o-mini` (OpenAI), `claude-sonnet-5` (Claude) or `openai/gpt-oss-120b` (Groq) — override with `OPENAI_MODEL`, `ANTHROPIC_MODEL` or `GROQ_MODEL` in `.env`. Applies to the primary provider only — fallbacks use their own default model.  
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

### `POST /chat/stream`

Same request body as `/chat`. The response is a `text/event-stream`:

```
event: delta
data: {"type": "delta", "text": "Rivers "}

event: delta
data: {"type": "delta", "text": "carve valleys..."}

event: done
data: {"type": "done", "provider": "groq", "model": "openai/gpt-oss-120b", "usage": {...}, "routing": {...}}
```

| Event | Meaning |
|---|---|
| `delta` | A piece of the answer — append `text` to what you have |
| `done` | Final event, with token `usage` and `routing` |
| `error` | The provider failed *after* streaming started; the stream ends |

**Retries and fallback with streaming:** the gateway waits for the provider's first event before sending the response headers. Until then, retries and fallback work exactly as in `/chat`, and if every provider fails you get a real `400`/`502` status. Once text has been sent, switching providers would glue two different answers together, so a failure mid-stream ends with an `error` event instead.

```bash
curl -N -X POST http://127.0.0.1:8000/chat/stream   -H "Content-Type: application/json"   -d '{"provider": "groq", "message": "Write 3 sentences about rivers."}'
```

Or open **http://127.0.0.1:8000/demo** to watch it stream in the browser, with time-to-first-token and token counts.

> **Windows tip:** use `127.0.0.1` rather than `localhost` for local testing — `localhost` tries IPv6 first and can add ~2s per connection.

**Measured locally** (warm connection): time to first token ≈ 0.26s on Groq and ≈ 0.72s on OpenAI `gpt-4o-mini` — the same as calling the SDKs directly, so the gateway adds no measurable latency.

## Adding a new provider

1. Create `app/gateway/<name>_provider.py` and subclass `LLMProvider`.
2. Implement `generate(message, model=None) -> dict` returning the normalized shape, and
   `stream(message, model=None)` yielding `delta` events then one `done` event.
   For an OpenAI-compatible API, just subclass `OpenAIProvider` and set `name`, `api_key_env`,
   `base_url` and `fallback_model` — see `groq_provider.py`.
3. Register the class (not an instance) in `LLMGateway.__init__` — it is created lazily on first use:

```python
self.provider_classes["gemini"] = GeminiProvider
```

## Roadmap

- [x] Groq provider
- [x] Retries with exponential backoff, cross-provider fallback, timeouts
- [x] Streaming responses (Server-Sent Events) + browser demo
- [ ] Gemini provider
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
