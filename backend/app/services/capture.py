"""
Background extract worker that processes pending extract jobs.

Runs as an asyncio background task, polling for pending or retry-ready
jobs and processing them one at a time through the graphiti-zep pipeline.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("studio.capture")

MAX_RETRIES = 3
POLL_INTERVAL_SECONDS = 5
# Exponential backoff base: 2^retry * BASE seconds
BACKOFF_BASE_SECONDS = 2


class ExtractWorker:
    """Background worker that processes pending extract jobs."""

    def __init__(self, db: Any, graphiti_client: Any):
        """
        Args:
            db: A SQLite database connection with extract_jobs and
                raw_memories tables.
            graphiti_client: An httpx.AsyncClient (or similar) configured to
                talk to the graphiti-zep server.
        """
        self._db = db
        self._graphiti = graphiti_client
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        """Start the background worker loop."""
        if self._running:
            logger.warning("ExtractWorker is already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._worker_loop())
        logger.info("ExtractWorker started")

    async def stop(self):
        """Stop the background worker loop gracefully."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("ExtractWorker stopped")

    async def _worker_loop(self):
        """
        Poll for pending/retry-ready jobs every POLL_INTERVAL_SECONDS.

        Processes jobs one at a time to avoid overwhelming the graphiti-zep
        server or the database.
        """
        while self._running:
            try:
                jobs = self._fetch_ready_jobs()
                for job in jobs:
                    if not self._running:
                        break
                    try:
                        await self.process_job(job)
                    except Exception as exc:
                        logger.error(
                            "Failed to process job %s: %s",
                            job["id"],
                            exc,
                        )
            except Exception as exc:
                logger.exception("Worker loop error: %s", exc)

            # Sleep between polls; check _running in small increments
            # so we can stop promptly
            for _ in range(POLL_INTERVAL_SECONDS):
                if not self._running:
                    return
                await asyncio.sleep(1)

    def _fetch_ready_jobs(self) -> list[dict]:
        """
        Fetch jobs that are pending or failed-with-retries-left.

        For failed jobs, only pick them up if enough time has passed
        for exponential backoff (2^retry_count seconds since last update).
        """
        now_ts = time.time()
        try:
            cursor = self._db.execute(
                """
                SELECT j.id, j.memory_id, j.project_id, j.status,
                       j.retry_count, j.updated_at, m.content
                FROM extract_jobs AS j
                JOIN raw_memories AS m ON m.id = j.memory_id
                WHERE j.status IN ('pending', 'failed')
                  AND j.retry_count < ?
                ORDER BY j.created_at ASC
                LIMIT 10
                """,
                (MAX_RETRIES,),
            )
            rows = cursor.fetchall()
        except Exception as exc:
            logger.error("Failed to fetch ready jobs: %s", exc)
            return []

        ready: list[dict] = []
        for row in rows:
            job = {
                "id": row[0],
                "memory_id": row[1],
                "project_id": row[2],
                "status": row[3],
                "retry_count": row[4],
                "updated_at": row[5],
                "content": row[6],
            }

            # For failed jobs, enforce exponential backoff
            if job["status"] == "failed" and job["retry_count"] > 0:
                backoff = BACKOFF_BASE_SECONDS ** job["retry_count"]
                try:
                    updated = time.mktime(
                        time.strptime(job["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
                    )
                    if now_ts - updated < backoff:
                        continue  # Not ready yet
                except (ValueError, TypeError):
                    pass  # If we can't parse the timestamp, process anyway

            ready.append(job)

        return ready

    async def process_job(self, job: dict):
        """
        Execute a single extract job.

        Sends the memory content to graphiti-zep as an episode, then updates
        the job status. On failure, increments retry_count up to MAX_RETRIES.
        """
        job_id = job["id"]
        memory_id = job["memory_id"]
        project_id = job["project_id"]
        content = job["content"]

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Mark as processing
        try:
            self._db.execute(
                "UPDATE extract_jobs SET status = 'processing', updated_at = ? WHERE id = ?",
                (now, job_id),
            )
            self._db.commit()
        except Exception as exc:
            logger.error("Failed to mark job %s as processing: %s", job_id, exc)
            return

        try:
            # Send to graphiti-zep
            await self._ingest_to_graphiti(memory_id, project_id, content)

            # Mark as done
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._db.execute(
                "UPDATE extract_jobs SET status = 'done', updated_at = ? WHERE id = ?",
                (now, job_id),
            )
            self._db.commit()
            logger.info("Extract job %s completed for memory %s", job_id, memory_id)

        except Exception as exc:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            new_retry = job.get("retry_count", 0) + 1
            new_status = "failed"

            self._db.execute(
                """
                UPDATE extract_jobs
                SET status = ?,
                    retry_count = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (new_status, new_retry, now, job_id),
            )
            self._db.commit()

            if new_retry >= MAX_RETRIES:
                logger.error(
                    "Extract job %s permanently failed after %d retries: %s",
                    job_id,
                    new_retry,
                    exc,
                )
            else:
                backoff = BACKOFF_BASE_SECONDS ** new_retry
                logger.warning(
                    "Extract job %s failed (retry %d/%d, backoff %ds): %s",
                    job_id,
                    new_retry,
                    MAX_RETRIES,
                    backoff,
                    exc,
                )

    async def _ingest_to_graphiti(
        self, memory_id: str, project_id: str, content: str
    ):
        """
        Send content to graphiti-zep for knowledge graph extraction.

        Supports both httpx.AsyncClient and SDK-style clients.
        """
        if isinstance(self._graphiti, httpx.AsyncClient):
            resp = await self._graphiti.post(
                "/graph/episodes",
                json={
                    "group_id": project_id,
                    "name": f"memory-{memory_id[:8]}",
                    "episodes": [
                        {
                            "content": content,
                            "source": "text",
                            "source_description": f"raw_memory:{memory_id}",
                        }
                    ],
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            return resp.json()

        # SDK-style client with graph.add_batch
        if hasattr(self._graphiti, "graph"):
            return await self._graphiti.graph.add_batch(
                group_id=project_id,
                episodes=[
                    {
                        "content": content,
                        "source": "text",
                        "source_description": f"raw_memory:{memory_id}",
                    }
                ],
            )

        raise RuntimeError(
            "graphiti_client has no recognized interface for ingestion"
        )
