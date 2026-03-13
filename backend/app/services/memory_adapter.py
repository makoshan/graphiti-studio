"""
Dual-channel memory search and capture/extract service.

Channel 1: SQLite FTS5 search on local raw_memories table.
Channel 2: Graphiti-Zep knowledge graph search (with graceful degradation).

Capture inserts raw memories and triggers async extraction to the knowledge graph.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from ..config import Config

logger = logging.getLogger("studio.memory_adapter")


class MemoryAdapter:
    """Dual-channel search + capture/extract for project memories."""

    def __init__(self, db: Any, graphiti_client: Any):
        """
        Args:
            db: The async ``Database`` singleton from ``app.db``.
            graphiti_client: The ``AsyncGraphitiClient`` singleton from
                ``app.services.graphiti_client``.
        """
        self._db = db
        self._graphiti = graphiti_client

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self, query: str, project_id: str, limit: int = 10
    ) -> dict:
        """Dual-channel search.

        Channel 1 — SQLite FTS5 on ``raw_memories_fts``.
        Channel 2 — graphiti-zep ``/search`` endpoint.

        Returns::

            {
                "results": [{"channel": "raw"|"graph", "snippet": ..., "score": ...}, ...],
                "references": {"nodes": [...], "edges": [...]},
                "degraded": bool
            }
        """
        references: dict[str, list[str]] = {"nodes": [], "edges": []}
        degraded = False

        # --- Channel 1: SQLite FTS5 ---
        fts_results = await self._search_fts(query, project_id, limit)

        # --- Channel 2: Graphiti-Zep graph search ---
        graph_results: list[dict] = []
        try:
            graph_results = await self._search_graphiti(query, project_id, limit)

            # Collect node/edge references.
            for item in graph_results:
                raw = item if isinstance(item, dict) else vars(item) if hasattr(item, "__dict__") else {}

                for node_key in ("source_node_uuid", "target_node_uuid", "node_uuid"):
                    nid = raw.get(node_key) or getattr(item, node_key, None)
                    if nid and nid not in references["nodes"]:
                        references["nodes"].append(nid)

                eid = raw.get("uuid") or getattr(item, "uuid", None)
                if eid and eid not in references["edges"]:
                    references["edges"].append(eid)
        except Exception as exc:
            logger.warning("Graphiti-Zep search degraded: %s", exc)
            degraded = True

        # --- Merge results ---
        merged: list[dict] = []
        seen_snippets: set[str] = set()

        for item in fts_results:
            snippet = (item.get("content") or "")[:500]
            if snippet and snippet not in seen_snippets:
                seen_snippets.add(snippet)
                merged.append({
                    "channel": "raw",
                    "snippet": snippet,
                    "score": abs(item.get("rank", 0.0)),
                    "source": item.get("source", ""),
                    "metadata": {
                        "memory_id": item.get("id"),
                        "created_at": item.get("created_at"),
                    },
                })

        for item in graph_results:
            raw = item if isinstance(item, dict) else vars(item) if hasattr(item, "__dict__") else {}
            snippet = (
                raw.get("fact")
                or raw.get("content")
                or raw.get("name")
                or str(item)
            )[:500]
            if snippet and snippet not in seen_snippets:
                seen_snippets.add(snippet)
                merged.append({
                    "channel": "graph",
                    "snippet": snippet,
                    "score": raw.get("score", raw.get("weight", 0.5)),
                    "source": raw.get("source", "graph"),
                    "metadata": {
                        "uuid": raw.get("uuid"),
                        "source_node_uuid": raw.get("source_node_uuid"),
                        "target_node_uuid": raw.get("target_node_uuid"),
                    },
                })

        # Sort by score descending and trim.
        merged.sort(key=lambda x: x.get("score", 0), reverse=True)
        merged = merged[:limit]

        return {
            "results": merged,
            "references": references,
            "degraded": degraded,
        }

    async def _search_graphiti(
        self, query: str, project_id: str, limit: int
    ) -> list:
        """Search graphiti-zep via the client's search method."""
        return await self._graphiti.search(
            query=query, group_id=project_id, limit=limit
        )

    async def _search_fts(
        self, query: str, project_id: str, limit: int
    ) -> list[dict]:
        """SQLite FTS5 full-text search on ``raw_memories_fts``.

        Falls back to LIKE search if FTS5 query fails (e.g. syntax errors).
        """
        tokens = query.strip().split()
        if not tokens:
            return []

        # Escape and quote each token for FTS5.
        fts_query = " ".join(
            '"' + tok.replace('"', '""') + '"' for tok in tokens
        )

        try:
            rows = await self._db.fetchall(
                """
                SELECT m.id, m.content, m.source, m.project_id, m.created_at,
                       fts.rank
                FROM raw_memories_fts AS fts
                JOIN raw_memories AS m ON m.rowid = fts.rowid
                WHERE raw_memories_fts MATCH ?
                  AND m.project_id = ?
                ORDER BY fts.rank
                LIMIT ?
                """,
                (fts_query, project_id, limit),
            )
        except Exception as exc:
            logger.warning("FTS5 search failed (%s), falling back to LIKE", exc)
            try:
                rows = await self._search_like(tokens, project_id, limit)
            except Exception as fallback_exc:
                logger.error("LIKE fallback also failed: %s", fallback_exc)
                return []

        if not rows:
            try:
                rows = await self._search_like(tokens, project_id, limit)
            except Exception as exc:
                logger.error("LIKE fallback after empty FTS result failed: %s", exc)
                return []

        return [
            {
                "id": dict(r).get("id", ""),
                "content": dict(r).get("content", ""),
                "source": dict(r).get("source", ""),
                "project_id": dict(r).get("project_id", ""),
                "created_at": dict(r).get("created_at", ""),
                "rank": dict(r).get("rank", 0),
            }
            for r in rows
        ]

    async def _search_like(
        self, tokens: list[str], project_id: str, limit: int
    ) -> list[Any]:
        """Token-based LIKE fallback that works better for CJK queries than
        a single ``%full query%`` search."""
        conditions = ["project_id = ?"]
        params: list[Any] = [project_id]

        for token in tokens:
            conditions.append("content LIKE ?")
            params.append(f"%{token}%")

        params.append(limit)

        return await self._db.fetchall(
            f"""
            SELECT id, content, source, project_id, created_at, 0 AS rank
            FROM raw_memories
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            tuple(params),
        )

    # ------------------------------------------------------------------
    # Capture + Extract
    # ------------------------------------------------------------------

    async def capture(
        self, content: str, project_id: str, source: str = "note"
    ) -> dict:
        """Capture a new raw memory and trigger async extraction.

        1. Insert into ``raw_memories`` (sync SQLite, immediate).
        2. Create an ``extract_jobs`` row (``pending``).
        3. Fire-and-forget async extraction via ``asyncio.create_task``.

        Returns ``{"id": ..., "job_id": ..., "status": "pending"}``.
        """
        memory_id = f"mem_{uuid.uuid4().hex[:12]}"
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = _now_iso()

        # Insert raw memory.
        await self._db.execute(
            """
            INSERT INTO raw_memories
                (id, project_id, content, source, graph_group_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (memory_id, project_id, content, source, project_id, now, now),
        )

        # Create extract job.
        await self._db.execute(
            """
            INSERT INTO extract_jobs
                (id, memory_id, project_id, status, retry_count, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', 0, ?, ?)
            """,
            (job_id, memory_id, project_id, now, now),
        )

        # Fire-and-forget async extraction.
        asyncio.create_task(
            self._safe_extract(job_id, memory_id, project_id, content)
        )

        return {"id": memory_id, "job_id": job_id, "status": "pending"}

    async def _safe_extract(
        self, job_id: str, memory_id: str, project_id: str, content: str
    ) -> None:
        """Wrapper that catches all exceptions so the background task
        does not crash the event loop."""
        try:
            await self._extract(job_id, memory_id, project_id, content)
        except Exception as exc:
            logger.exception(
                "Background extract failed for job %s: %s", job_id, exc
            )

    async def _extract(
        self, job_id: str, memory_id: str, project_id: str, content: str
    ) -> None:
        """Run extraction: send content to graphiti-zep as an episode.

        1. Mark job as ``processing``.
        2. Call graphiti-zep ingestion.
        3. Mark as ``done`` on success, ``failed`` on error.
        """
        now = _now_iso()

        # Mark as processing.
        await self._db.execute(
            "UPDATE extract_jobs SET status = 'processing', updated_at = ? WHERE id = ?",
            (now, job_id),
        )

        try:
            from .graphiti_client import EpisodeData

            await self._graphiti.graph.add_batch(
                project_id,
                [
                    EpisodeData(
                        data=content,
                        type="text",
                        source_description=f"raw_memory:{memory_id}",
                        summary_language=Config.GRAPHITI_SUMMARY_LANGUAGE,
                    )
                ],
            )

            now = _now_iso()
            await self._db.execute(
                "UPDATE extract_jobs SET status = 'done', error_log = NULL, updated_at = ? WHERE id = ?",
                (now, job_id),
            )
            logger.info("Extract job %s completed successfully", job_id)

        except Exception as exc:
            now = _now_iso()
            await self._db.execute(
                """
                UPDATE extract_jobs
                SET status = 'failed',
                    retry_count = retry_count + 1,
                    error_log = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (str(exc)[:2000], now, job_id),
            )
            logger.error("Extract job %s failed: %s", job_id, exc)
            raise

    # ------------------------------------------------------------------
    # Sync (re-trigger pending / failed jobs)
    # ------------------------------------------------------------------

    async def sync(self, project_id: str | None = None) -> int:
        """Find ``pending`` and ``failed`` extract jobs (with retry_count < 3)
        and re-trigger extraction for each.

        Returns the number of jobs triggered.
        """
        if project_id:
            rows = await self._db.fetchall(
                """
                SELECT j.id, j.memory_id, j.project_id, m.content
                FROM extract_jobs AS j
                JOIN raw_memories AS m ON m.id = j.memory_id
                WHERE j.status IN ('pending', 'failed')
                  AND j.retry_count < 3
                  AND j.project_id = ?
                ORDER BY j.created_at ASC
                """,
                (project_id,),
            )
        else:
            rows = await self._db.fetchall(
                """
                SELECT j.id, j.memory_id, j.project_id, m.content
                FROM extract_jobs AS j
                JOIN raw_memories AS m ON m.id = j.memory_id
                WHERE j.status IN ('pending', 'failed')
                  AND j.retry_count < 3
                ORDER BY j.created_at ASC
                """,
            )

        triggered = 0
        for row in rows:
            d = dict(row)
            asyncio.create_task(
                self._safe_extract(
                    d["id"], d["memory_id"], d["project_id"], d["content"]
                )
            )
            triggered += 1

        logger.info("Triggered %d pending/failed extract jobs", triggered)
        return triggered


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_adapter_instance: MemoryAdapter | None = None


def get_memory_adapter() -> MemoryAdapter:
    """Return a lazily-created singleton MemoryAdapter.

    Uses the global ``Database`` and ``AsyncGraphitiClient`` singletons.
    """
    global _adapter_instance
    if _adapter_instance is None:
        from ..db import get_db
        from .graphiti_client import get_graphiti_client

        _adapter_instance = MemoryAdapter(
            db=get_db(),
            graphiti_client=get_graphiti_client(),
        )
    return _adapter_instance


def reset_memory_adapter() -> None:
    """Drop the cached singleton so it can be rebuilt with fresh services."""
    global _adapter_instance
    _adapter_instance = None
