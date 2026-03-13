"""
Runtime settings synchronisation helpers.

Loads persisted settings from SQLite into ``Config`` so long-lived service
singletons use the latest user-provided connection details.
"""

from __future__ import annotations

from .config import Config
from .db import Database
from .services.graphiti_client import reset_graphiti_client
from .services.memory_adapter import reset_memory_adapter


async def apply_runtime_settings(db: Database) -> None:
    """Load persisted settings from SQLite and apply them to ``Config``."""
    row = await db.fetchone("SELECT * FROM settings WHERE id = 1")
    if not row:
        return

    data = dict(row)
    Config.AGENT_RUNTIME = data.get("agent_runtime", Config.AGENT_RUNTIME) or Config.AGENT_RUNTIME
    Config.PI_PROVIDER = data.get("pi_provider", Config.PI_PROVIDER) or Config.PI_PROVIDER
    Config.PI_MODEL = data.get("pi_model", Config.PI_MODEL) or Config.PI_MODEL
    Config.PI_API_KEY = data.get("pi_api_key", "") or ""
    Config.LLM_API_KEY = data.get("llm_api_key", "") or ""
    Config.LLM_BASE_URL = data.get("llm_base_url", Config.LLM_BASE_URL) or Config.LLM_BASE_URL
    Config.LLM_MODEL = data.get("llm_model", Config.LLM_MODEL) or Config.LLM_MODEL
    Config.GRAPHITI_BASE_URL = data.get("graphiti_base_url", Config.GRAPHITI_BASE_URL) or Config.GRAPHITI_BASE_URL
    Config.GRAPHITI_API_KEY = data.get("graphiti_api_key", "") or ""
    Config.GRAPHITI_SUMMARY_LANGUAGE = (
        data.get("graphiti_summary_language", Config.GRAPHITI_SUMMARY_LANGUAGE)
        or Config.GRAPHITI_SUMMARY_LANGUAGE
    )
    Config.DEFAULT_CHUNK_SIZE = data.get("default_chunk_size", Config.DEFAULT_CHUNK_SIZE) or Config.DEFAULT_CHUNK_SIZE
    Config.DEFAULT_CHUNK_OVERLAP = data.get("default_chunk_overlap", Config.DEFAULT_CHUNK_OVERLAP) or Config.DEFAULT_CHUNK_OVERLAP

    reset_graphiti_client()
    reset_memory_adapter()
