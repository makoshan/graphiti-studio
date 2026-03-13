"""
SQLite database manager using aiosqlite.

Provides an async Database class and schema initialization for Graphiti Studio.
"""

from __future__ import annotations

import os
from typing import Any

import aiosqlite

from .config import Config

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    settings    TEXT NOT NULL DEFAULT '{}',   -- JSON
    node_count  INTEGER NOT NULL DEFAULT 0,
    edge_count  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS threads (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title         TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id   TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    tool_calls  TEXT,   -- JSON
    "references" TEXT,  -- JSON
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS raw_memories (
    id             TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content        TEXT NOT NULL DEFAULT '',
    source         TEXT NOT NULL DEFAULT '',
    graph_group_id TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS extract_jobs (
    id            TEXT PRIMARY KEY,
    memory_id     TEXT NOT NULL REFERENCES raw_memories(id) ON DELETE CASCADE,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'pending',
    retry_count   INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    error_log     TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Full-text search on raw_memories content
CREATE VIRTUAL TABLE IF NOT EXISTS raw_memories_fts USING fts5(
    content,
    content='raw_memories',
    content_rowid='rowid'
);

-- Triggers to keep FTS index in sync
CREATE TRIGGER IF NOT EXISTS raw_memories_ai AFTER INSERT ON raw_memories BEGIN
    INSERT INTO raw_memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS raw_memories_ad AFTER DELETE ON raw_memories BEGIN
    INSERT INTO raw_memories_fts(raw_memories_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS raw_memories_au AFTER UPDATE ON raw_memories BEGIN
    INSERT INTO raw_memories_fts(raw_memories_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
    INSERT INTO raw_memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;

-- Single-row application settings
CREATE TABLE IF NOT EXISTS settings (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    agent_runtime        TEXT NOT NULL DEFAULT 'builtin',
    pi_provider          TEXT NOT NULL DEFAULT 'kimi-coding',
    pi_model             TEXT NOT NULL DEFAULT 'k2p5',
    pi_api_key           TEXT NOT NULL DEFAULT '',
    llm_api_key          TEXT NOT NULL DEFAULT '',
    llm_base_url         TEXT NOT NULL DEFAULT 'https://api.openai.com/v1',
    llm_model            TEXT NOT NULL DEFAULT 'gpt-4o-mini',
    graphiti_base_url    TEXT NOT NULL DEFAULT 'http://127.0.0.1:8000',
    graphiti_api_key     TEXT NOT NULL DEFAULT '',
    graphiti_summary_language TEXT NOT NULL DEFAULT 'original',
    default_chunk_size   INTEGER NOT NULL DEFAULT 1000,
    default_chunk_overlap INTEGER NOT NULL DEFAULT 100,
    theme                TEXT NOT NULL DEFAULT 'system'
);

-- Ensure the settings row exists
INSERT OR IGNORE INTO settings (id) VALUES (1);
"""


class Database:
    """Async SQLite database wrapper."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or os.path.join(Config.STUDIO_DATA_DIR, "studio.db")
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database connection and enable WAL mode + foreign keys."""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    def _ensure_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected. Call connect() first.")
        return self._conn

    async def execute(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> aiosqlite.Cursor:
        """Execute a single SQL statement and commit."""
        conn = self._ensure_conn()
        cursor = await conn.execute(sql, params)
        await conn.commit()
        return cursor

    async def executemany(self, sql: str, params_seq: list[tuple[Any, ...] | dict[str, Any]]) -> aiosqlite.Cursor:
        """Execute a SQL statement against many parameter sets and commit."""
        conn = self._ensure_conn()
        cursor = await conn.executemany(sql, params_seq)
        await conn.commit()
        return cursor

    async def fetchone(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> aiosqlite.Row | None:
        """Execute a query and return the first row (or None)."""
        conn = self._ensure_conn()
        cursor = await conn.execute(sql, params)
        return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[aiosqlite.Row]:
        """Execute a query and return all rows."""
        conn = self._ensure_conn()
        cursor = await conn.execute(sql, params)
        return await cursor.fetchall()


async def init_schema(db: Database) -> None:
    """Create all tables, indexes, and triggers if they do not already exist."""
    conn = db._ensure_conn()
    await conn.executescript(_SCHEMA_SQL)
    cursor = await conn.execute("PRAGMA table_info(settings)")
    columns = {row[1] for row in await cursor.fetchall()}
    if "agent_runtime" not in columns:
        await conn.execute(
            """
            ALTER TABLE settings
            ADD COLUMN agent_runtime TEXT NOT NULL DEFAULT 'builtin'
            """
        )
    if "pi_provider" not in columns:
        await conn.execute(
            """
            ALTER TABLE settings
            ADD COLUMN pi_provider TEXT NOT NULL DEFAULT 'kimi-coding'
            """
        )
    if "pi_model" not in columns:
        await conn.execute(
            """
            ALTER TABLE settings
            ADD COLUMN pi_model TEXT NOT NULL DEFAULT 'k2p5'
            """
        )
    if "pi_api_key" not in columns:
        await conn.execute(
            """
            ALTER TABLE settings
            ADD COLUMN pi_api_key TEXT NOT NULL DEFAULT ''
            """
        )
    if "graphiti_summary_language" not in columns:
        await conn.execute(
            """
            ALTER TABLE settings
            ADD COLUMN graphiti_summary_language TEXT NOT NULL DEFAULT 'original'
            """
        )
    await conn.commit()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_db_instance: Database | None = None


def get_db() -> Database:
    """Return the global Database singleton (created lazily, not yet connected)."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
