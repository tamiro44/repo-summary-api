# Repo Summarizer

A production-ready FastAPI service that summarizes GitHub repositories using an LLM. Given a GitHub URL, it fetches the repository tree, intelligently selects the most informative files, and produces a structured JSON summary via any OpenAI-compatible LLM API.

## Quick Start

# PowerShell
copy .env.example .env
$env:LLM_API_KEY="..."
$env:GITHUB_TOKEN="..."
python -m uvicorn main:app --reload

```bash
# Install dependencies
pip install -r requirements.txt

# Configure via .env file (copy the template and fill in your keys)
cp .env.example .env
# Edit .env with your API keys

# Or set environment variables directly
export LLM_API_KEY="sk-..."       # OpenAI / compatible API key
export GITHUB_TOKEN="ghp_..."     # Optional but recommended (raises rate limits)

# Run
python -c "import uvicorn; uvicorn.run('main:app', host='127.0.0.1', port=8000, reload=True)"
```

```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}'
```

## Architecture

```
main.py                  — FastAPI app, middleware, health check
config.py                — Environment-based settings + .env loader
.env                     — Local environment variables (not committed)
routers/summarize.py     — POST /summarize endpoint, error mapping
services/summarizer.py   — Orchestration: fetch → score → download → build context → LLM
clients/github_client.py — Async GitHub REST API client
clients/llm_client.py    — Provider-agnostic OpenAI-compatible LLM client
utils/file_filter.py     — File scoring & exclusion heuristics
utils/context_builder.py — Budget-aware context assembly
models/schemas.py        — Pydantic request/response models
```

### Design Decisions

**Layered architecture** — Routers handle HTTP concerns (validation, error codes). Services own business logic. Clients encapsulate external APIs. This separation makes each layer independently testable and replaceable.

**Dependency injection via FastAPI `Depends`** — Settings and service instances are wired through FastAPI's DI system, making it trivial to swap implementations for testing.

**Zero-dependency `.env` loading** — `config.py` includes a lightweight `.env` parser (no `python-dotenv` needed). It reads key-value pairs, skips comments and blanks, and never overrides existing environment variables — so production env vars always win.

**Graceful auth handling** — The LLM client only sends an `Authorization` header when an API key is actually configured, allowing it to work with local models (Ollama, vLLM) that don't require authentication.

**No ORM, no database** — The service is stateless by design. An in-memory LRU cache provides optional repeat-request speedup without infrastructure overhead.

## File Filtering Strategy

Not all files in a repository are informative. The filtering pipeline has two stages:

### 1. Exclusion (hard filter)

Files are dropped entirely if they match:
- **Directories**: `node_modules`, `dist`, `build`, `.git`, `__pycache__`, `vendor`, `venv`, etc.
- **Extensions**: images, binaries, archives, fonts, lock files, minified assets, source maps
- **Filenames**: `package-lock.json`, `yarn.lock`, `poetry.lock`, etc.
- **Size**: anything over 500 KB (likely generated or binary)

### 2. Scoring (soft priority)

Remaining files receive a numeric score (lower = higher priority):

| Tier | Score  | Examples |
|------|--------|---------|
| 0    | 0      | Root README |
| 1    | 10+    | `pyproject.toml`, `package.json`, `Dockerfile` |
| 2    | 20+    | Nested READMEs |
| 3    | 30+    | Entry points (`main.py`, `app.py`, `index.js`) |
| 4    | 40     | Top-level source files |
| 5    | 60+    | Deep source files (score increases with depth) |
| 6    | 80+    | Test files |

Depth is used as a tiebreaker within tiers — shallower files are preferred.

## Context Window Strategy

LLMs have finite context windows. The service manages this with three controls:

| Parameter | Default | Env Variable |
|-----------|---------|-------------|
| Total budget | 100,000 chars | `MAX_CONTEXT_CHARS` |
| Prompt buffer | 4,000 chars | `PROMPT_BUFFER_CHARS` |
| Per-file cap | 15,000 chars | `PER_FILE_MAX_CHARS` |

**Assembly process:**
1. Files are sorted by score (ascending).
2. Files are included one-by-one until the budget is exhausted.
3. Each file is truncated to `PER_FILE_MAX_CHARS` to prevent a single large file from consuming the budget.
4. If the budget runs out mid-file, a partial section is included.

This ensures the LLM always receives the most valuable files first, regardless of repository size.

## Model Choice

The default model is `gpt-4o-mini` — a strong balance of quality, speed, and cost for structured summarization tasks. Override via `LLM_MODEL`.

The LLM client targets the OpenAI `/chat/completions` API format, which is supported by:
- OpenAI (GPT-4o, GPT-4o-mini)
- Azure OpenAI
- Anthropic Claude (via API proxy)
- Local models (Ollama, vLLM, LM Studio)
- Any OpenAI-compatible endpoint

Set `LLM_API_BASE` to point to any compatible endpoint.

## Configuration

Settings are loaded from **environment variables** and an optional **`.env` file** in the project root. Environment variables take precedence over `.env` values, so you can use `.env` for local development while overriding in production.

### `.env` file

Create a `.env` file in the project root (a template is provided as `.env.example`):

```env
GITHUB_TOKEN=ghp_your_token_here
LLM_API_KEY=sk-your_key_here
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

> **Note:** The `.env` loader is built into `config.py` with zero extra dependencies. It reads key-value pairs, skips comments (`#`) and blank lines, and never overrides variables already set in the environment.

### All variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_TOKEN` | _(none)_ | GitHub personal access token ([create one here](https://github.com/settings/tokens) — no scopes needed for public repos) |
| `GITHUB_API_BASE` | `https://api.github.com` | GitHub API base URL |
| `GITHUB_TIMEOUT` | `30` | GitHub request timeout (seconds) |
| `LLM_API_KEY` | _(required)_ | LLM provider API key |
| `LLM_API_BASE` | `https://api.openai.com/v1` | LLM API base URL |
| `LLM_MODEL` | `gpt-4o-mini` | Model identifier |
| `LLM_TIMEOUT` | `60` | LLM request timeout (seconds) |
| `LLM_MAX_TOKENS` | `4096` | Max response tokens |
| `MAX_CONTEXT_CHARS` | `100000` | Total context character budget |
| `PROMPT_BUFFER_CHARS` | `4000` | Reserved chars for prompt instructions |
| `PER_FILE_MAX_CHARS` | `15000` | Max chars per individual file |
| `CACHE_MAX_SIZE` | `128` | Max cached summaries |

> **Without `GITHUB_TOKEN`**, unauthenticated requests are limited to 60/hour by GitHub. With a token, the limit is 5,000/hour.

## Performance Considerations

- **Async throughout** — All I/O (GitHub API, LLM API) uses `httpx.AsyncClient` with configurable timeouts.
- **Batched downloads** — File contents are fetched in concurrent batches of 10 with early stopping once the budget is hit.
- **Single tree call** — The full repository file listing is retrieved with one API call (`/git/trees/HEAD?recursive=1`), not one call per directory.
- **In-memory cache** — Repeat requests for the same repo are served instantly from an LRU-like cache.
- **Request timing** — Every request logs wall-clock time and returns it in the `X-Process-Time` header.

## Future Improvements

- **Redis cache** — Replace the in-memory cache with Redis for multi-process / multi-node deployments.
- **Branch/tag support** — Accept an optional `ref` parameter to summarize specific branches.
- **Streaming responses** — Stream the LLM response for faster time-to-first-byte on large repos.
- **Webhook integration** — Trigger re-summarization on push events.
- **Rate limiting** — Add per-client rate limits to protect the LLM budget.
- **OpenTelemetry** — Replace ad-hoc logging with structured traces and metrics.
- **Multi-model routing** — Route large repos to higher-context models automatically.
