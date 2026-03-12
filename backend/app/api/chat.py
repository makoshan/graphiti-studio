"""
Chat and thread management API router.

Endpoints:
    POST   /api/projects/{project_id}/chat                  - SSE streaming chat
    GET    /api/projects/{project_id}/threads                - list threads
    POST   /api/projects/{project_id}/threads                - create thread
    DELETE /api/projects/{project_id}/threads/{thread_id}    - delete thread

The chat endpoint wires up a PiAgent instance with memory_search and
memory_capture tools, streams events to the client via SSE, and persists
the conversation in SQLite.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..db import get_db
from ..services.graphiti_client import get_graphiti_client
from ..services.memory_adapter import get_memory_adapter
from ..services.pi_agent import PiAgent
from ..config import Config

MAX_ENRICHED_REFS = 10  # cap per category to avoid slow lookups

logger = logging.getLogger("studio.api.chat")

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful knowledge assistant for this project. "
    "When the user asks a question, use the memory_search tool to retrieve "
    "relevant information from the project's knowledge graph before answering. "
    "Always cite sources when available. "
    "If the user explicitly asks you to remember something, use the "
    "memory_capture tool to save it to the knowledge graph."
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    thread_id: Optional[str] = None


class ThreadCreate(BaseModel):
    title: str = ""
    system_prompt: str = ""


class ThreadResponse(BaseModel):
    id: str
    project_id: str
    title: str
    system_prompt: str
    created_at: str


class MessageResponse(BaseModel):
    id: int
    thread_id: str
    role: str
    content: str
    tool_calls: Any = None
    references: Any = None
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _row_to_dict(row) -> dict:
    d = dict(row)
    for field in ("tool_calls", "references"):
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


async def _get_or_create_thread(project_id: str, thread_id: Optional[str]) -> dict:
    """Return the requested thread or create a new one if thread_id is None."""
    db = get_db()

    if thread_id:
        row = await db.fetchone(
            "SELECT * FROM threads WHERE id = ? AND project_id = ?",
            (thread_id, project_id),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Thread not found")
        return dict(row)

    # Auto-create a new thread.
    new_id = str(uuid.uuid4())
    now = _now_iso()
    await db.execute(
        "INSERT INTO threads (id, project_id, title, system_prompt, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (new_id, project_id, "", "", now),
    )
    row = await db.fetchone("SELECT * FROM threads WHERE id = ?", (new_id,))
    return dict(row)


async def _load_messages(thread_id: str) -> list[dict]:
    """Load conversation history for the given thread."""
    db = get_db()
    rows = await db.fetchall(
        "SELECT role, content, tool_calls FROM messages "
        "WHERE thread_id = ? ORDER BY created_at ASC",
        (thread_id,),
    )
    messages: list[dict] = []
    for r in rows:
        d = dict(r)
        msg: dict[str, Any] = {"role": d["role"], "content": d["content"] or ""}
        if d.get("tool_calls"):
            try:
                msg["tool_calls"] = json.loads(d["tool_calls"])
            except (json.JSONDecodeError, TypeError):
                pass
        messages.append(msg)
    return messages


async def _save_message(
    thread_id: str,
    role: str,
    content: str,
    tool_calls: Any = None,
    references: Any = None,
) -> None:
    """Persist a message to SQLite."""
    db = get_db()
    now = _now_iso()
    tc_json = json.dumps(tool_calls, default=str) if tool_calls else None
    ref_json = json.dumps(references, default=str) if references else None
    await db.execute(
        'INSERT INTO messages (thread_id, role, content, tool_calls, "references", created_at) '
        "VALUES (?, ?, ?, ?, ?, ?)",
        (thread_id, role, content, tc_json, ref_json, now),
    )


async def _enrich_references(references: dict) -> dict:
    """Resolve UUID strings to ``{uuid, name}`` objects so the frontend can
    display human-readable reference chips."""
    graphiti = get_graphiti_client()
    enriched: dict[str, list[dict]] = {"nodes": [], "edges": []}

    for node_uuid in references.get("nodes", [])[:MAX_ENRICHED_REFS]:
        try:
            node = await graphiti.graph.node.get(node_uuid)
            enriched["nodes"].append({
                "uuid": node_uuid,
                "name": getattr(node, "name", None) or node_uuid[:8],
            })
        except Exception:
            enriched["nodes"].append({"uuid": node_uuid, "name": node_uuid[:8]})

    for edge_uuid in references.get("edges", [])[:MAX_ENRICHED_REFS]:
        try:
            edge = await graphiti.graph.edge.get(edge_uuid)
            enriched["edges"].append({
                "uuid": edge_uuid,
                "name": getattr(edge, "fact", None)
                or getattr(edge, "name", None)
                or edge_uuid[:8],
            })
        except Exception:
            enriched["edges"].append({"uuid": edge_uuid, "name": edge_uuid[:8]})

    return enriched


def _build_pi_agent(project_id: str) -> PiAgent:
    """Create a PiAgent instance with memory_search and memory_capture tools
    registered.  The ``project_id`` is captured in closures so the LLM never
    needs to provide it."""
    agent = PiAgent(
        api_key=Config.LLM_API_KEY,
        base_url=Config.LLM_BASE_URL,
        model=Config.LLM_MODEL,
    )

    adapter = get_memory_adapter()

    # ---- memory_search tool ----
    async def _memory_search(query: str, limit: int = 10) -> dict:
        result = await adapter.search(
            query=query,
            project_id=project_id,
            limit=limit,
        )
        return result

    agent.register_tool(
        name="memory_search",
        description=(
            "Search the project's knowledge graph and raw memories. "
            "Returns relevant facts, text snippets, and graph references. "
            "Call this whenever the user asks a question about the project's knowledge."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return.",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
        handler=_memory_search,
    )

    # ---- memory_capture tool ----
    async def _memory_capture(content: str) -> dict:
        result = await adapter.capture(
            content=content,
            project_id=project_id,
            source="chat",
        )
        return {
            "saved": True,
            "id": result["id"],
            "message": f"Saved to knowledge graph (ID: {result['id']})",
        }

    agent.register_tool(
        name="memory_capture",
        description=(
            "Save important information to the project's knowledge graph. "
            "Only call this when the user explicitly asks to remember or save something."
        ),
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The text content to store.",
                },
            },
            "required": ["content"],
        },
        handler=_memory_capture,
    )

    return agent


# ---------------------------------------------------------------------------
# SSE Chat endpoint
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/chat")
async def chat(project_id: str, body: ChatRequest):
    """SSE streaming chat endpoint.

    Accepts a user message, loads the thread's history, invokes PiAgent with
    memory tools, and streams events back to the client.  Both the user and
    assistant messages are persisted in SQLite once the stream completes.

    SSE event types:
        start        - {"role": "assistant"}
        text_chunk   - {"text": "..."}
        tool_call    - {"id": "...", "name": "...", "arguments": "..."}
        tool_result  - {"id": "...", "result": {...}}
        end          - {"content": "...", "references": {"nodes": [], "edges": []}}
        error        - {"message": "..."}
    """
    db = get_db()

    # Validate project exists.
    project = await db.fetchone(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Resolve (or create) thread.
    thread = await _get_or_create_thread(project_id, body.thread_id)
    thread_id = thread["id"]

    # Load conversation history.
    history = await _load_messages(thread_id)

    # Save the incoming user message immediately.
    await _save_message(thread_id, "user", body.message)

    # Append user message to the history we'll send to the LLM.
    history.append({"role": "user", "content": body.message})

    # Build agent with memory tools bound to this project.
    agent = _build_pi_agent(project_id)

    # Determine system prompt: use thread override if present, else default.
    system_prompt = thread.get("system_prompt") or DEFAULT_SYSTEM_PROMPT

    async def _event_generator() -> AsyncGenerator[dict, None]:
        """Wraps PiAgent.chat, persists the final assistant message,
        and yields SSE-formatted dicts."""
        final_content = ""
        final_references: dict[str, list[str]] = {"nodes": [], "edges": []}
        tool_calls_log: list[dict] = []

        try:
            async for event in agent.chat(history, system_prompt=system_prompt):
                event_type = event.get("event", "")
                event_data = event.get("data", {})

                if event_type == "tool_call":
                    tool_calls_log.append(event_data)

                # Intercept `end` event: enrich references before sending.
                if event_type == "end":
                    final_content = event_data.get("content", "")
                    raw_refs = event_data.get("references", final_references)

                    # Resolve UUIDs → {uuid, name} objects.
                    if any(raw_refs.values()):
                        try:
                            final_references = await _enrich_references(raw_refs)
                        except Exception as exc:
                            logger.warning("Reference enrichment failed: %s", exc)
                            final_references = raw_refs
                    else:
                        final_references = raw_refs

                    yield {
                        "event": "end",
                        "data": json.dumps(
                            {"content": final_content, "references": final_references},
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                    continue

                yield {
                    "event": event_type,
                    "data": json.dumps(event_data, ensure_ascii=False, default=str),
                }

        except Exception as exc:
            logger.exception("Streaming chat failed for project %s", project_id)
            yield {
                "event": "error",
                "data": json.dumps({"message": str(exc)}),
            }
            return

        # Persist assistant message after streaming completes.
        try:
            await _save_message(
                thread_id=thread_id,
                role="assistant",
                content=final_content,
                tool_calls=tool_calls_log if tool_calls_log else None,
                references=final_references if any(final_references.values()) else None,
            )

            # Auto-title the thread from the first user message if it is untitled.
            if not thread.get("title"):
                title = body.message[:60].strip()
                if len(body.message) > 60:
                    title += "..."
                await db.execute(
                    "UPDATE threads SET title = ? WHERE id = ?",
                    (title, thread_id),
                )
        except Exception as exc:
            logger.error("Failed to save assistant message: %s", exc)

    return EventSourceResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "X-Thread-Id": thread_id,
        },
    )


# ---------------------------------------------------------------------------
# Thread management endpoints
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/threads", response_model=list[ThreadResponse])
async def list_threads(project_id: str):
    """List all threads belonging to a project, most recent first."""
    db = get_db()
    project = await db.fetchone("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = await db.fetchall(
        "SELECT * FROM threads WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    )
    return [
        ThreadResponse(
            id=r["id"],
            project_id=r["project_id"],
            title=r["title"] or "",
            system_prompt=r["system_prompt"] or "",
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.post(
    "/projects/{project_id}/threads",
    response_model=ThreadResponse,
    status_code=201,
)
async def create_thread(project_id: str, body: ThreadCreate):
    """Create a new conversation thread for a project."""
    db = get_db()
    project = await db.fetchone("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    thread_id = str(uuid.uuid4())
    now = _now_iso()
    await db.execute(
        "INSERT INTO threads (id, project_id, title, system_prompt, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (thread_id, project_id, body.title, body.system_prompt, now),
    )

    return ThreadResponse(
        id=thread_id,
        project_id=project_id,
        title=body.title,
        system_prompt=body.system_prompt,
        created_at=now,
    )


@router.delete("/projects/{project_id}/threads/{thread_id}", status_code=204)
async def delete_thread(project_id: str, thread_id: str):
    """Delete a thread and all its messages (cascade)."""
    db = get_db()
    existing = await db.fetchone(
        "SELECT id FROM threads WHERE id = ? AND project_id = ?",
        (thread_id, project_id),
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Thread not found")

    await db.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
    return None
