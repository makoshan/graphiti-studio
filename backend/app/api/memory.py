"""
Memory Adapter HTTP endpoints.

Endpoints:
    POST  /capture   - capture raw memory + queue extract job
    POST  /search    - dual-channel search (FTS + graphiti-zep)
    GET   /get/{id}  - retrieve a single raw memory by id
    GET   /status    - queue counts by status + graphiti-zep health
    POST  /sync      - re-trigger pending / failed extract jobs

These endpoints are the public HTTP surface of the Memory Adapter.
The PiAgent also calls the adapter in-process via the same Python
functions, so the HTTP layer is mainly for external agents and debugging.

Note: the router has no prefix — main.py mounts it at both ``/memory``
and ``/api/memory``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_db
from ..services.graphiti_client import get_graphiti_client
from ..services.memory_adapter import get_memory_adapter

logger = logging.getLogger("studio.api.memory")

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class CaptureRequest(BaseModel):
    content: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    source: str = "note"


class CaptureResponse(BaseModel):
    id: str
    job_id: str
    status: str


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    filters: Optional[dict[str, Any]] = None
    limit: int = Field(10, ge=1, le=100)


class SearchResultItem(BaseModel):
    channel: str          # "raw" | "graph"
    snippet: str
    score: float
    source: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    references: dict[str, list[str]]  # {"nodes": [...], "edges": [...]}
    degraded: bool


class RawMemoryResponse(BaseModel):
    id: str
    project_id: str
    content: str
    source: str
    graph_group_id: str
    created_at: str
    updated_at: str


class QueueCounts(BaseModel):
    pending: int
    processing: int
    failed: int


class StatusResponse(BaseModel):
    queue: QueueCounts
    neo4j_ok: bool


class SyncResponse(BaseModel):
    triggered: int


# ---------------------------------------------------------------------------
# POST /capture
# ---------------------------------------------------------------------------


@router.post("/capture", response_model=CaptureResponse)
async def capture(body: CaptureRequest):
    """Write text into ``raw_memories`` (synchronous) and queue an
    asynchronous extract job that pushes it into graphiti-zep / Neo4j.

    Returns immediately with the memory id, job id, and initial status
    (``"pending"``).
    """
    db = get_db()

    # Validate project.
    project = await db.fetchone(
        "SELECT id FROM projects WHERE id = ?", (body.project_id,)
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    adapter = get_memory_adapter()
    result = await adapter.capture(
        content=body.content,
        project_id=body.project_id,
        source=body.source,
    )

    return CaptureResponse(
        id=result["id"],
        job_id=result["job_id"],
        status=result["status"],
    )


# ---------------------------------------------------------------------------
# POST /search
# ---------------------------------------------------------------------------


@router.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest):
    """Dual-channel search: SQLite FTS over ``raw_memories`` **and**
    graphiti-zep graph search.  Results are merged by score and
    de-duplicated.

    When graphiti-zep is unreachable the ``degraded`` flag is ``true``
    and only FTS results are returned.
    """
    db = get_db()

    project = await db.fetchone(
        "SELECT id FROM projects WHERE id = ?", (body.project_id,)
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    adapter = get_memory_adapter()
    result = await adapter.search(
        query=body.query,
        project_id=body.project_id,
        limit=body.limit,
    )

    items = [
        SearchResultItem(
            channel=r.get("channel", "raw"),
            snippet=r.get("snippet", ""),
            score=r.get("score", 0.0),
            source=r.get("source"),
            metadata=r.get("metadata"),
        )
        for r in result.get("results", [])
    ]

    return SearchResponse(
        results=items,
        references=result.get("references", {"nodes": [], "edges": []}),
        degraded=result.get("degraded", False),
    )


# ---------------------------------------------------------------------------
# GET /get/{memory_id}
# ---------------------------------------------------------------------------


@router.get("/get/{memory_id}", response_model=RawMemoryResponse)
async def get_memory(memory_id: str):
    """Retrieve a single raw memory by its id."""
    db = get_db()
    row = await db.fetchone(
        "SELECT * FROM raw_memories WHERE id = ?", (memory_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")

    d = dict(row)
    return RawMemoryResponse(
        id=d["id"],
        project_id=d["project_id"],
        content=d["content"],
        source=d.get("source", ""),
        graph_group_id=d.get("graph_group_id", ""),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
    )


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


@router.get("/status", response_model=StatusResponse)
async def status():
    """Return extract-job queue counts grouped by status and a quick
    connectivity check against graphiti-zep.
    """
    db = get_db()

    # Count jobs by status.
    pending_row = await db.fetchone(
        "SELECT COUNT(*) AS cnt FROM extract_jobs WHERE status = 'pending'"
    )
    processing_row = await db.fetchone(
        "SELECT COUNT(*) AS cnt FROM extract_jobs WHERE status = 'processing'"
    )
    failed_row = await db.fetchone(
        "SELECT COUNT(*) AS cnt FROM extract_jobs WHERE status = 'failed'"
    )

    pending = dict(pending_row)["cnt"] if pending_row else 0
    processing = dict(processing_row)["cnt"] if processing_row else 0
    failed = dict(failed_row)["cnt"] if failed_row else 0

    # Ping graphiti-zep health endpoint.
    neo4j_ok = False
    graphiti = get_graphiti_client()
    try:
        neo4j_ok = await graphiti.health()
    except Exception as exc:
        logger.debug("graphiti-zep health check failed: %s", exc)

    return StatusResponse(
        queue=QueueCounts(pending=pending, processing=processing, failed=failed),
        neo4j_ok=neo4j_ok,
    )


# ---------------------------------------------------------------------------
# POST /sync
# ---------------------------------------------------------------------------


@router.post("/sync", response_model=SyncResponse)
async def sync():
    """Re-trigger extraction for all ``pending`` and ``failed`` jobs.

    This is useful after a transient graphiti-zep outage or to retry jobs
    that previously failed due to LLM errors.
    """
    adapter = get_memory_adapter()
    triggered = await adapter.sync()
    return SyncResponse(triggered=triggered)
