# Graphiti Studio

Graphiti Studio is a local knowledge-graph workbench with an AI chat interface. It combines a FastAPI backend, a Vue 3 frontend, SQLite for local state, and a `graphiti-zep` service for graph-backed memory retrieval.

The important architecture detail is that Studio now supports two different AI runtimes:

- `Chat Agent Runtime`: the interactive project chat agent
- `Extraction / Graph Pipeline`: document upload, chunking, episode ingestion, graph extraction, and Neo4j-backed retrieval

These two layers are intentionally separate. Chat can run on `pi-coding-agent + Kimi Coding`, while the extraction and graph pipeline continue to use the existing Graphiti-compatible backend.

## Features

- Project-based knowledge graph management
- Local raw memory storage in SQLite with FTS fallback search
- AI chat with tool-calling memory search
- Optional `pi-coding-agent` RPC runtime for chat
- Optional `Kimi Coding` support for the chat agent runtime
- File upload and chunked memory capture
- Vue + D3 visualization for graph exploration

## Tech Stack

- Frontend: Vue 3, Vite, Tailwind CSS, D3.js
- Backend: FastAPI, Uvicorn, OpenAI SDK, optional `pi-coding-agent` RPC bridge
- Storage: SQLite
- Graph service: `graphiti-zep`
- Tooling: `npm` and `uv`

## Runtime Model

Studio has two AI paths with different responsibilities:

- `Chat Agent Runtime`
  - Default option: built-in Python `PiAgent`
  - Optional option: `pi-coding-agent` RPC
  - When configured with `pi_provider = kimi-coding`, project chat runs through `Kimi Coding`
- `Extraction / Graph Pipeline`
  - Uploads raw text into SQLite
  - Splits text into chunks
  - Sends episodes to `graphiti-zep`
  - Builds and retrieves graph data from Neo4j
  - This pipeline does not automatically become `Kimi Coding` just because chat does

In other words:

- If you switch chat to `pi-rpc + kimi-coding`, project chat uses `Kimi Coding`
- Upload, memory ingestion, graph extraction, and graph search still run through the existing Graphiti pipeline unless you explicitly rework that layer too

## Project Structure

```text
graphiti-studio/
  backend/        FastAPI app and tests
  frontend/       Vue 3 app
  docs/           Product and implementation notes
  data/           Local runtime data (ignored by git)
```

## Quick Start

1. Install dependencies:

```bash
npm run setup:all
```

2. Configure environment:

```bash
cp .env.example .env
```

3. Start the app:

```bash
npm run dev
```

Frontend runs through Vite. The backend starts from `backend/run.py`.

## Settings

Use the Studio settings page to configure the runtime split clearly.

- `Agent Runtime`
  - `Built-in PiAgent`: uses the local Python chat runtime
  - `pi-coding-agent RPC`: uses `pi-mono` as the chat runtime
- `pi-coding-agent` settings
  - `Provider`: for example `kimi-coding`
  - `Model`: for example `k2p5`
  - `Provider API Key`: for example a `KIMI_API_KEY`
- `Built-in LLM Runtime`
  - Used only when the agent runtime is `Built-in PiAgent`
- `Graphiti-Zep Connection`
  - Used by graph sync, search, stats, and ingestion

### Recommended Setup for Kimi Coding

If you want project chat to run on `Kimi Coding`, use:

- `Agent Runtime = pi-coding-agent RPC`
- `Provider = kimi-coding`
- `Model = k2p5`
- `Provider API Key = your Kimi Coding key`

This affects chat only. It does not automatically replace the upload or graph extraction pipeline.

## Environment

The backend expects standard LLM and graph-service settings through environment variables or the Studio settings UI. See `.env.example` for the initial shape.

The main runtime-related settings are:

- `AGENT_RUNTIME`
- `PI_PROVIDER`
- `PI_MODEL`
- `PI_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_API_KEY`
- `GRAPHITI_BASE_URL`
- `GRAPHITI_API_KEY`

The UI persists these settings in SQLite and applies them at runtime.

## Development

- Frontend build: `npm run build`
- Backend tests: `cd backend && uv run pytest`

## License

MIT. See `LICENSE`.
