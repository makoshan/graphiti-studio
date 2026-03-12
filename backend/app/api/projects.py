"""
Projects API router — project CRUD, stats, and file upload.

Endpoints:
    GET    /api/projects              - list all projects
    POST   /api/projects              - create project (+ graphiti-zep group)
    GET    /api/projects/{id}         - get project details + stats
    PUT    /api/projects/{id}         - update project name/description/settings
    DELETE /api/projects/{id}         - delete project (cascade SQLite + graphiti-zep group)
    GET    /api/projects/{id}/stats   - node_count, edge_count from graphiti-zep
    POST   /api/projects/{id}/upload  - multipart file upload -> parse -> chunk -> batch capture
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..db import get_db
from ..services.graphiti_client import get_graphiti_client
from ..services.memory_adapter import get_memory_adapter

logger = logging.getLogger("studio.api.projects")

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    settings: dict[str, Any]
    node_count: int
    edge_count: int
    created_at: str
    updated_at: str


class ProjectStatsResponse(BaseModel):
    node_count: int
    edge_count: int
    memory_count: int
    last_updated: str


class UploadMemoryItem(BaseModel):
    id: str
    status: str


class UploadResponse(BaseModel):
    memories: list[UploadMemoryItem]
    total_chunks: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_project(row) -> ProjectResponse:
    """Convert an aiosqlite Row to a ProjectResponse."""
    d = dict(row)
    settings_raw = d.get("settings") or "{}"
    if isinstance(settings_raw, str):
        try:
            settings_parsed = json.loads(settings_raw)
        except json.JSONDecodeError:
            settings_parsed = {}
    else:
        settings_parsed = settings_raw

    return ProjectResponse(
        id=d["id"],
        name=d["name"],
        description=d.get("description") or "",
        settings=settings_parsed,
        node_count=d.get("node_count", 0) or 0,
        edge_count=d.get("edge_count", 0) or 0,
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _mirofish_projects_dir() -> Path:
    """Return the MiroFish local project metadata directory."""
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "backend" / "uploads" / "projects"


def _load_mirofish_project_metadata() -> dict[str, dict[str, str]]:
    """Index MiroFish local project metadata by ``graph_id``.

    This lets Graphiti Studio display meaningful names for remote
    ``mirofish_*`` graph groups that otherwise only expose generic group
    metadata such as ``Unnamed Project``.
    """
    projects_dir = _mirofish_projects_dir()
    if not projects_dir.exists():
        return {}

    metadata: dict[str, dict[str, str]] = {}
    for project_file in projects_dir.glob("*/project.json"):
        try:
            with project_file.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue

        graph_id = data.get("graph_id")
        if not graph_id:
            continue

        display_name = (
            data.get("title")
            or data.get("project_name")
            or (
                data.get("name")
                if data.get("name") and data.get("name") != "Unnamed Project"
                else None
            )
            or data.get("simulation_requirement")
            or graph_id
        )

        description = (
            data.get("description")
            or data.get("simulation_requirement")
            or data.get("analysis_summary")
            or ""
        )

        metadata[graph_id] = {
            "name": str(display_name).strip(),
            "description": str(description).strip(),
        }

    return metadata


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


async def _sync_remote_groups() -> int:
    """Discover groups in graphiti-zep that don't yet exist locally and
    create corresponding project records in SQLite.

    Returns the number of newly imported projects.
    """
    db = get_db()
    graphiti = get_graphiti_client()
    mirofish_metadata = _load_mirofish_project_metadata()

    try:
        remote_groups = await graphiti.list_groups()
    except Exception as exc:
        logger.debug("Could not list remote groups (graphiti-zep may be offline): %s", exc)
        return 0

    logger.info("Remote group sync: found %d remote groups", len(remote_groups))

    # Fetch existing local project IDs.
    rows = await db.fetchall("SELECT id FROM projects")
    local_ids = {dict(r)["id"] for r in rows}
    logger.info("Remote group sync: %d local project IDs", len(local_ids))

    imported_or_updated = 0
    now = _now_iso()
    for group in remote_groups:
        gid = group.get("group_id") or group.get("id", "")
        if not gid:
            continue

        local_meta = mirofish_metadata.get(gid, {})
        name = local_meta.get("name") or group.get("name") or gid
        description = local_meta.get("description") or group.get("description") or ""

        # Fetch live node/edge counts.
        node_count = 0
        edge_count = 0
        try:
            stats = await graphiti.get_group_stats(gid)
            node_count = stats.get("node_count", 0)
            edge_count = stats.get("edge_count", 0)
        except Exception:
            pass

        # Skip empty groups (no nodes and no edges) — avoids importing
        # dozens of test/smoke groups that have no real data.
        if node_count == 0 and edge_count == 0:
            continue

        if gid in local_ids:
            existing = await db.fetchone(
                "SELECT name, description, node_count, edge_count FROM projects WHERE id = ?",
                (gid,),
            )
            if existing:
                existing_dict = dict(existing)
                needs_name = (
                    existing_dict.get("name") in ("", "Unnamed Project", gid)
                    and name not in ("", "Unnamed Project", gid)
                )
                needs_description = (
                    existing_dict.get("description") in ("", "MiroFish Social Simulation Graph")
                    and description
                )
                needs_counts = (
                    (existing_dict.get("node_count") or 0) != node_count
                    or (existing_dict.get("edge_count") or 0) != edge_count
                )
                if needs_name or needs_description or needs_counts:
                    await db.execute(
                        """
                        UPDATE projects
                        SET name = ?, description = ?, node_count = ?, edge_count = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            name if needs_name else existing_dict.get("name", ""),
                            description if needs_description else existing_dict.get("description", ""),
                            node_count,
                            edge_count,
                            now,
                            gid,
                        ),
                    )
                    imported_or_updated += 1
                    logger.info("Updated imported remote group %s with MiroFish metadata", gid)
            continue

        await db.execute(
            """
            INSERT OR IGNORE INTO projects
                (id, name, description, settings, node_count, edge_count, created_at, updated_at)
            VALUES (?, ?, ?, '{}', ?, ?, ?, ?)
            """,
            (gid, name, description, node_count, edge_count, now, now),
        )
        imported_or_updated += 1
        logger.info("Auto-imported remote group %s (%s) with %d nodes", gid, name, node_count)

    return imported_or_updated


@router.get("", response_model=list[ProjectResponse])
async def list_projects():
    """List all projects, ordered by most recently updated.

    Automatically discovers groups that exist in graphiti-zep / Neo4j but
    don't have a local SQLite record yet and imports them.
    """
    # Auto-discover remote groups (best-effort, non-blocking on failure).
    try:
        imported = await _sync_remote_groups()
        if imported:
            logger.info("Auto-imported %d remote group(s) into local projects", imported)
    except Exception as exc:
        logger.debug("Remote group sync skipped: %s", exc)

    db = get_db()
    rows = await db.fetchall("SELECT * FROM projects ORDER BY updated_at DESC")
    return [_row_to_project(r) for r in rows]


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(body: ProjectCreate):
    """Create a new project and its corresponding graphiti-zep group.

    The project ID doubles as the graphiti-zep group_id so that graph data
    and local metadata are always linked.
    """
    project_id = f"proj_{uuid4().hex[:12]}"
    now = _now_iso()

    # Attempt to create the graphiti-zep group first.  If the remote is down
    # we still create the local record so the user can work offline.
    graphiti = get_graphiti_client()
    try:
        await graphiti.create_group(project_id, name=body.name)
    except Exception as exc:
        logger.warning(
            "graphiti-zep group creation for %s failed (%s) — proceeding offline.",
            project_id,
            exc,
        )

    db = get_db()
    settings_json = json.dumps(body.settings, ensure_ascii=False) if body.settings else "{}"
    await db.execute(
        """
        INSERT INTO projects (id, name, description, settings, node_count, edge_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, 0, 0, ?, ?)
        """,
        (project_id, body.name, body.description, settings_json, now, now),
    )

    return ProjectResponse(
        id=project_id,
        name=body.name,
        description=body.description,
        settings=body.settings or {},
        node_count=0,
        edge_count=0,
        created_at=now,
        updated_at=now,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    """Get a single project's details."""
    db = get_db()
    row = await db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return _row_to_project(row)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, body: ProjectUpdate):
    """Update a project's name, description, or settings."""
    db = get_db()
    existing = await db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")

    current = dict(existing)
    updates: list[str] = []
    params: list[Any] = []

    if body.name is not None:
        updates.append("name = ?")
        params.append(body.name)

    if body.description is not None:
        updates.append("description = ?")
        params.append(body.description)

    if body.settings is not None:
        # Merge with existing settings so callers can update a subset of keys.
        try:
            old_settings = json.loads(current.get("settings") or "{}")
        except (json.JSONDecodeError, TypeError):
            old_settings = {}
        old_settings.update(body.settings)
        updates.append("settings = ?")
        params.append(json.dumps(old_settings, ensure_ascii=False))

    if not updates:
        return _row_to_project(existing)

    now = _now_iso()
    updates.append("updated_at = ?")
    params.append(now)
    params.append(project_id)

    await db.execute(
        f"UPDATE projects SET {', '.join(updates)} WHERE id = ?",
        tuple(params),
    )

    row = await db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
    return _row_to_project(row)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str):
    """Delete a project. Cascades to threads/messages/raw_memories/extract_jobs
    via SQLite foreign keys and also deletes the graphiti-zep group."""
    db = get_db()
    existing = await db.fetchone("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")

    # Best-effort remote deletion.
    graphiti = get_graphiti_client()
    try:
        await graphiti.delete_group(project_id)
    except Exception as exc:
        logger.warning(
            "graphiti-zep group deletion for %s failed (%s) — continuing local delete.",
            project_id,
            exc,
        )

    # SQLite ON DELETE CASCADE handles threads, messages, raw_memories, extract_jobs.
    await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return None


@router.post("/sync")
async def sync_remote_groups():
    """Manually trigger discovery of remote graphiti-zep groups.

    Any groups found in graphiti-zep that don't exist locally are imported
    as new projects.
    """
    imported = await _sync_remote_groups()
    return {"imported": imported}


@router.get("/{project_id}/stats", response_model=ProjectStatsResponse)
async def get_project_stats(project_id: str):
    """Fetch live node/edge counts from graphiti-zep and local memory count.

    Also refreshes the cached node_count / edge_count in the projects row.
    """
    db = get_db()
    row = await db.fetchone("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    # Pull fresh stats from graphiti-zep.
    node_count = 0
    edge_count = 0
    graphiti = get_graphiti_client()
    try:
        stats = await graphiti.get_group_stats(project_id)
        node_count = stats.get("node_count", 0)
        edge_count = stats.get("edge_count", 0)
    except Exception as exc:
        logger.warning("Could not fetch graphiti-zep stats for %s: %s", project_id, exc)
        # Fall back to cached values.
        cached = await db.fetchone(
            "SELECT node_count, edge_count FROM projects WHERE id = ?",
            (project_id,),
        )
        if cached:
            node_count = cached["node_count"] or 0
            edge_count = cached["edge_count"] or 0

    # Refresh cached counts.
    now = _now_iso()
    await db.execute(
        "UPDATE projects SET node_count = ?, edge_count = ?, updated_at = ? WHERE id = ?",
        (node_count, edge_count, now, project_id),
    )

    # Count local raw memories.
    mem_row = await db.fetchone(
        "SELECT COUNT(*) AS cnt FROM raw_memories WHERE project_id = ?",
        (project_id,),
    )
    memory_count = dict(mem_row)["cnt"] if mem_row else 0

    return ProjectStatsResponse(
        node_count=node_count,
        edge_count=edge_count,
        memory_count=memory_count,
        last_updated=now,
    )


@router.get("/{project_id}/graph")
async def get_graph_data(project_id: str):
    """Fetch full graph data (nodes + edges) for visualization.

    Returns a dict with ``nodes`` and ``edges`` lists ready for D3.js rendering.
    """
    db = get_db()
    row = await db.fetchone("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    graphiti = get_graphiti_client()
    nodes_raw = []
    edges_raw = []

    try:
        graph_snapshot = await graphiti.get_group_graph(project_id)
        nodes_raw = graph_snapshot.get("nodes", [])
        edges_raw = graph_snapshot.get("edges", [])
    except Exception as exc:
        logger.warning("Could not fetch graph data for %s: %s", project_id, exc)

    def _ns_to_dict(obj: Any) -> dict:
        if isinstance(obj, dict):
            return obj
        return vars(obj) if hasattr(obj, "__dict__") else {"value": str(obj)}

    nodes = [_ns_to_dict(n) for n in nodes_raw]
    edges = [_ns_to_dict(e) for e in edges_raw]

    return {"nodes": nodes, "edges": edges}


@router.post("/{project_id}/upload", response_model=UploadResponse)
async def upload_files(project_id: str, files: list[UploadFile] = File(...)):
    """Accept multipart file uploads, parse each file to text, split into
    chunks, and batch-capture every chunk through the Memory Adapter.

    The extract phase runs asynchronously — callers should poll
    ``GET /memory/status`` or ``GET /api/projects/{id}/stats`` to track
    progress.
    """
    db = get_db()
    row = await db.fetchone("SELECT id, settings FROM projects WHERE id = ?", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    # Resolve chunk config from project settings, falling back to defaults.
    proj_data = dict(row)
    try:
        settings = json.loads(proj_data.get("settings") or "{}")
    except (json.JSONDecodeError, TypeError):
        settings = {}
    chunk_size: int = settings.get("chunk_size", 1000)
    chunk_overlap: int = settings.get("chunk_overlap", 100)

    # Lazy imports — these modules may not exist yet during early development.
    from ..services.file_parser import FileParser, split_text_into_chunks

    adapter = get_memory_adapter()
    all_memories: list[UploadMemoryItem] = []
    total_chunks = 0

    for upload_file in files:
        raw_bytes = await upload_file.read()
        filename = upload_file.filename or "unknown"

        # Parse file content to plain text.
        try:
            text = FileParser.parse(raw_bytes, filename)
        except Exception as exc:
            logger.error("Failed to parse uploaded file %s: %s", filename, exc)
            continue

        if not text or not text.strip():
            logger.info("Skipping empty file: %s", filename)
            continue

        # Split into chunks.
        chunks = split_text_into_chunks(
            text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        for chunk in chunks:
            if not chunk.strip():
                continue
            try:
                result = await adapter.capture(
                    content=chunk,
                    project_id=project_id,
                    source="upload",
                )
                all_memories.append(
                    UploadMemoryItem(id=result["id"], status=result["status"])
                )
                total_chunks += 1
            except Exception as exc:
                logger.error(
                    "Capture failed for chunk from %s: %s", filename, exc
                )

    return UploadResponse(memories=all_memories, total_chunks=total_chunks)


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------


@router.get("/{project_id}/export")
async def export_project(project_id: str):
    """Export project data as JSON.

    Includes the project metadata, threads, messages, raw_memories,
    extract_jobs, and a snapshot of the graph data from graphiti-zep.
    """
    db = get_db()
    row = await db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    project_data = dict(row)

    # Local SQLite data
    threads = [
        dict(r) for r in await db.fetchall(
            "SELECT * FROM threads WHERE project_id = ? ORDER BY created_at ASC",
            (project_id,),
        )
    ]
    messages = []
    for t in threads:
        msgs = [
            dict(r) for r in await db.fetchall(
                "SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at ASC",
                (t["id"],),
            )
        ]
        messages.extend(msgs)

    raw_memories = [
        dict(r) for r in await db.fetchall(
            "SELECT * FROM raw_memories WHERE project_id = ? ORDER BY created_at ASC",
            (project_id,),
        )
    ]
    extract_jobs = [
        dict(r) for r in await db.fetchall(
            "SELECT * FROM extract_jobs WHERE project_id = ? ORDER BY created_at ASC",
            (project_id,),
        )
    ]

    # Graph snapshot from graphiti-zep (best-effort)
    graph_nodes: list[dict] = []
    graph_edges: list[dict] = []
    graphiti = get_graphiti_client()
    try:
        nodes_raw = await graphiti.graph.node.get_by_graph_id(project_id, limit=500)
        edges_raw = await graphiti.graph.edge.get_by_graph_id(project_id, limit=2000)

        def _ns(obj: Any) -> dict:
            if isinstance(obj, dict):
                return obj
            return vars(obj) if hasattr(obj, "__dict__") else {"value": str(obj)}

        graph_nodes = [_ns(n) for n in nodes_raw]
        graph_edges = [_ns(e) for e in edges_raw]
    except Exception as exc:
        logger.warning("Could not snapshot graph for export of %s: %s", project_id, exc)

    return {
        "version": "1.0",
        "project": project_data,
        "threads": threads,
        "messages": messages,
        "raw_memories": raw_memories,
        "extract_jobs": extract_jobs,
        "graph": {"nodes": graph_nodes, "edges": graph_edges},
    }


@router.post("/{project_id}/import")
async def import_project_data(project_id: str, body: dict):
    """Import previously exported data into an existing project.

    Currently imports only ``raw_memories`` (re-triggering extraction).
    Threads and messages are imported as-is.
    """
    db = get_db()
    row = await db.fetchone("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    imported_memories = 0
    imported_threads = 0
    imported_messages = 0
    thread_id_map: dict[str, str] = {}

    # Import threads
    for t in body.get("threads", []):
        try:
            new_thread_id = str(uuid4())
            await db.execute(
                "INSERT INTO threads (id, project_id, title, system_prompt, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (new_thread_id, project_id, t.get("title", ""), t.get("system_prompt", ""),
                 t.get("created_at", _now_iso())),
            )
            thread_id_map[t["id"]] = new_thread_id
            imported_threads += 1
        except Exception as exc:
            logger.warning("Failed to import thread %s: %s", t.get("id"), exc)

    # Import messages
    for m in body.get("messages", []):
        try:
            mapped_thread_id = thread_id_map.get(m.get("thread_id", ""))
            if not mapped_thread_id:
                logger.warning("Skipping imported message with unknown thread_id: %s", m.get("thread_id"))
                continue
            await db.execute(
                'INSERT INTO messages (thread_id, role, content, tool_calls, "references", created_at) '
                "VALUES (?, ?, ?, ?, ?, ?)",
                (mapped_thread_id, m["role"], m.get("content", ""),
                 m.get("tool_calls"), m.get("references"), m.get("created_at", _now_iso())),
            )
            imported_messages += 1
        except Exception as exc:
            logger.warning("Failed to import message: %s", exc)

    # Import raw_memories — re-trigger extraction
    adapter = None
    for mem in body.get("raw_memories", []):
        try:
            if adapter is None:
                from ..services.memory_adapter import get_memory_adapter
                adapter = get_memory_adapter()
            await adapter.capture(
                content=mem.get("content", ""),
                project_id=project_id,
                source=mem.get("source", "import"),
            )
            imported_memories += 1
        except Exception as exc:
            logger.warning("Failed to import memory: %s", exc)

    return {
        "imported_threads": imported_threads,
        "imported_messages": imported_messages,
        "imported_memories": imported_memories,
    }
