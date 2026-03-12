"""
FastAPI application entry point for Graphiti Studio.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Config
from .db import get_db, init_schema
from .runtime_settings import apply_runtime_settings


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    # Ensure data directory exists
    os.makedirs(Config.STUDIO_DATA_DIR, exist_ok=True)

    # Initialize database
    db = get_db()
    await db.connect()
    await init_schema(db)
    await apply_runtime_settings(db)

    yield

    # Shutdown
    await db.close()


app = FastAPI(
    title="Graphiti Studio",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS (permissive for local dev)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
from .api import projects, chat, memory, settings  # noqa: E402

app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
# Chat router paths already include /projects/{project_id}/... prefixes
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(memory.router, prefix="/api/memory", tags=["memory"])
# Also mount memory at /memory (no /api prefix) as per spec
app.include_router(memory.router, prefix="/memory", tags=["memory"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health_check() -> dict:
    return {"status": "ok", "version": "0.1.0"}
