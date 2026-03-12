# Graphiti Studio

Graphiti Studio is a local knowledge-graph workbench with an AI chat interface. It combines a FastAPI backend, a Vue 3 frontend, SQLite for local state, and a `graphiti-zep` service for graph-backed memory retrieval.

## Features

- Project-based knowledge graph management
- Local raw memory storage in SQLite with FTS fallback search
- AI chat with tool-calling memory search
- File upload and chunked memory capture
- Vue + D3 visualization for graph exploration

## Tech Stack

- Frontend: Vue 3, Vite, Tailwind CSS, D3.js
- Backend: FastAPI, Uvicorn, OpenAI SDK
- Storage: SQLite
- Graph service: `graphiti-zep`
- Tooling: `npm` and `uv`

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

## Environment

The backend expects standard LLM and graph-service settings through environment variables or the Studio settings UI. See `.env.example` for the initial shape.

## Development

- Frontend build: `npm run build`
- Backend tests: `cd backend && uv run pytest`

## License

MIT. See `LICENSE`.
