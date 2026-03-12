"""
Settings management API router.

Endpoints:
    GET  /api/settings  - retrieve current settings (API keys masked)
    PUT  /api/settings  - update settings

The settings table is a single-row table (id=1) that stores LLM
configuration, graphiti-zep connection info, and UI preferences.

Note: the router has no prefix — main.py mounts it at ``/api/settings``.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_db
from ..runtime_settings import apply_runtime_settings

logger = logging.getLogger("studio.api.settings")

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SettingsResponse(BaseModel):
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    graphiti_base_url: str
    graphiti_api_key: str
    default_chunk_size: int
    default_chunk_overlap: int
    theme: str


class SettingsUpdate(BaseModel):
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    graphiti_base_url: Optional[str] = None
    graphiti_api_key: Optional[str] = None
    default_chunk_size: Optional[int] = Field(None, ge=100, le=10000)
    default_chunk_overlap: Optional[int] = Field(None, ge=0, le=5000)
    theme: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MASKED_FIELDS = ("llm_api_key", "graphiti_api_key")


def _mask_key(value: str) -> str:
    """Mask an API key, revealing only the last 4 characters.

    Short keys (<=8 chars) are fully masked.  Empty strings pass through
    unchanged.
    """
    if not value:
        return ""
    if len(value) <= 8:
        return "****" + value[-4:] if len(value) > 4 else "****"
    return "*" * (len(value) - 4) + value[-4:]


def _row_to_response(row, *, mask: bool = True) -> SettingsResponse:
    """Convert an aiosqlite Row to a SettingsResponse, optionally masking
    API key fields."""
    d = dict(row)
    if mask:
        for field in _MASKED_FIELDS:
            d[field] = _mask_key(d.get(field, "") or "")
    return SettingsResponse(
        llm_api_key=d.get("llm_api_key", ""),
        llm_base_url=d.get("llm_base_url", ""),
        llm_model=d.get("llm_model", ""),
        graphiti_base_url=d.get("graphiti_base_url", ""),
        graphiti_api_key=d.get("graphiti_api_key", ""),
        default_chunk_size=d.get("default_chunk_size", 1000),
        default_chunk_overlap=d.get("default_chunk_overlap", 100),
        theme=d.get("theme", "system"),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=SettingsResponse)
async def get_settings():
    """Return the current application settings.

    API key values are masked in the response (only the last 4 characters
    are shown).
    """
    db = get_db()
    row = await db.fetchone("SELECT * FROM settings WHERE id = 1")
    if not row:
        raise HTTPException(
            status_code=500,
            detail="Settings row missing — database may not be initialised.",
        )
    return _row_to_response(row, mask=True)


@router.put("", response_model=SettingsResponse)
async def update_settings(body: SettingsUpdate):
    """Update one or more settings fields.

    Only the fields included in the request body are updated; omitted
    fields are left unchanged.  The response contains the full settings
    object with API keys masked.
    """
    db = get_db()

    # Build a dynamic UPDATE statement from only the supplied fields.
    supplied = body.model_dump(exclude_none=True)
    if not supplied:
        # Nothing to update — return current settings.
        row = await db.fetchone("SELECT * FROM settings WHERE id = 1")
        if not row:
            raise HTTPException(status_code=500, detail="Settings row missing.")
        return _row_to_response(row, mask=True)

    set_clauses: list[str] = []
    params: list = []
    for field_name, value in supplied.items():
        set_clauses.append(f"{field_name} = ?")
        params.append(value)

    params.append(1)  # WHERE id = 1
    sql = f"UPDATE settings SET {', '.join(set_clauses)} WHERE id = ?"

    await db.execute(sql, tuple(params))

    # Re-fetch and return.
    row = await db.fetchone("SELECT * FROM settings WHERE id = 1")
    if not row:
        raise HTTPException(status_code=500, detail="Settings row missing.")
    await apply_runtime_settings(db)
    return _row_to_response(row, mask=True)


class TestConnectionRequest(BaseModel):
    graphiti_base_url: str = "http://127.0.0.1:8000"
    graphiti_api_key: str = ""


@router.post("/test-connection")
async def test_connection(body: TestConnectionRequest):
    """Test connectivity to a graphiti-zep server."""
    base_url = body.graphiti_base_url.rstrip("/")
    headers = {}
    if body.graphiti_api_key:
        headers["Authorization"] = f"Bearer {body.graphiti_api_key}"

    try:
        async with httpx.AsyncClient(timeout=10, headers=headers) as client:
            resp = await client.get(f"{base_url}/healthcheck")
            resp.raise_for_status()
        return {"ok": True, "message": "Connection successful"}
    except Exception as exc:
        return {"ok": False, "message": f"Connection failed: {exc}"}
