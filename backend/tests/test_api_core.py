from __future__ import annotations

import asyncio
import json
from types import MethodType

import app.api.chat as chat_api
from app.db import get_db


def test_settings_get_and_update_masks_keys(client):
    update = {
        "llm_api_key": "sk-secret-1234",
        "graphiti_api_key": "graphiti-secret-5678",
        "llm_base_url": "https://llm.test/v1",
        "llm_model": "demo-model",
        "theme": "dark",
    }
    put_resp = client.put("/api/settings", json=update)
    assert put_resp.status_code == 200

    body = put_resp.json()
    assert body["llm_api_key"].endswith("1234")
    assert body["llm_api_key"] != update["llm_api_key"]
    assert body["graphiti_api_key"].endswith("5678")
    assert body["theme"] == "dark"

    get_resp = client.get("/api/settings")
    assert get_resp.status_code == 200
    current = get_resp.json()
    assert current["llm_model"] == "demo-model"
    assert current["llm_api_key"].endswith("1234")


def test_project_create_and_stats_refresh(client, fake_graphiti_client):
    create_resp = client.post(
        "/api/projects",
        json={"name": "吴越史", "description": "项目描述", "settings": {"chunk_size": 800}},
    )
    assert create_resp.status_code == 201
    project = create_resp.json()

    assert project["name"] == "吴越史"
    assert project["settings"]["chunk_size"] == 800
    assert fake_graphiti_client.created_groups
    assert fake_graphiti_client.created_groups[0][0] == project["id"]

    stats_resp = client.get(f"/api/projects/{project['id']}/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert stats["node_count"] == 2
    assert stats["edge_count"] == 1
    assert stats["memory_count"] == 0


def test_project_graph_endpoint_fetches_paginated_graph_snapshot(client, fake_graphiti_client):
    project = client.post("/api/projects", json={"name": "大图项目"}).json()
    project_id = project["id"]

    record_cls = fake_graphiti_client.node_records["node-1"].__class__
    fake_graphiti_client.node_records.clear()
    fake_graphiti_client.node_records.update({
        f"node-{i:04d}": record_cls(
            uuid=f"node-{i:04d}",
            name=f"节点{i:04d}",
        )
        for i in range(250)
    })
    fake_graphiti_client.edge_records.clear()
    fake_graphiti_client.edge_records.update({
        f"edge-{i:04d}": record_cls(
            uuid=f"edge-{i:04d}",
            fact=f"节点{i:04d} RELATED_TO 节点{i+1:04d}",
            source_node_uuid=f"node-{i:04d}",
            target_node_uuid=f"node-{(i + 1) % 250:04d}",
            score=0.8,
        )
        for i in range(230)
    })

    graph_resp = client.get(f"/api/projects/{project_id}/graph")
    assert graph_resp.status_code == 200
    graph = graph_resp.json()

    assert len(graph["nodes"]) == 250
    assert len(graph["edges"]) == 230
    assert graph["nodes"][0]["uuid"] == "node-0000"
    assert graph["edges"][0]["uuid"] == "edge-0000"


def test_memory_capture_search_get_and_status(client):
    project = client.post("/api/projects", json={"name": "记忆项目"}).json()
    project_id = project["id"]

    capture_resp = client.post(
        "/memory/capture",
        json={"content": "钱俶在开宝八年纳土归宋", "project_id": project_id, "source": "chat"},
    )
    assert capture_resp.status_code == 200
    capture = capture_resp.json()
    assert capture["id"].startswith("mem_")
    assert capture["job_id"].startswith("job_")
    assert capture["status"] == "pending"

    search_resp = client.post(
        "/memory/search",
        json={"query": "钱俶 归宋", "project_id": project_id, "limit": 10},
    )
    assert search_resp.status_code == 200
    payload = search_resp.json()

    assert payload["degraded"] is False
    assert any(item["channel"] == "raw" for item in payload["results"])
    assert any(item["channel"] == "graph" for item in payload["results"])
    assert payload["references"]["nodes"] == ["node-1", "node-2"]
    assert payload["references"]["edges"] == ["edge-1"]

    get_resp = client.get(f"/memory/get/{capture['id']}")
    assert get_resp.status_code == 200
    raw = get_resp.json()
    assert raw["content"] == "钱俶在开宝八年纳土归宋"
    assert raw["source"] == "chat"

    status_resp = client.get("/memory/status")
    assert status_resp.status_code == 200
    status = status_resp.json()
    assert status["queue"]["pending"] == 1
    assert status["neo4j_ok"] is True


def test_memory_search_degrades_when_graphiti_fails(client, fake_graphiti_client):
    project = client.post("/api/projects", json={"name": "降级项目"}).json()
    project_id = project["id"]

    capture_resp = client.post(
        "/memory/capture",
        json={"content": "吴越国向北宋纳土归附", "project_id": project_id, "source": "note"},
    )
    assert capture_resp.status_code == 200

    async def failing_search(self, *, query: str, group_id: str, limit: int = 10):
        raise RuntimeError("graphiti offline")

    fake_graphiti_client.search = MethodType(failing_search, fake_graphiti_client)

    search_resp = client.post(
        "/memory/search",
        json={"query": "吴越国 北宋", "project_id": project_id, "limit": 10},
    )
    assert search_resp.status_code == 200

    payload = search_resp.json()
    assert payload["degraded"] is True
    assert payload["references"] == {"nodes": [], "edges": []}
    assert [item["channel"] for item in payload["results"]] == ["raw"]


def test_chat_streams_events_and_persists_messages(client, monkeypatch):
    project = client.post("/api/projects", json={"name": "对话项目"}).json()
    project_id = project["id"]

    class FakeAgent:
        async def chat(self, messages, system_prompt=None):
            assert messages[-1]["content"] == "吴越国为什么归宋？"
            assert system_prompt
            yield {"event": "start", "data": {"role": "assistant"}}
            yield {
                "event": "tool_call",
                "data": {"id": "call-1", "name": "memory_search", "arguments": "{\"query\":\"吴越国\"}"},
            }
            yield {
                "event": "tool_result",
                "data": {
                    "id": "call-1",
                    "result": {
                        "results": [{"snippet": "钱俶在开宝八年纳土归宋", "channel": "graph"}],
                        "references": {"nodes": ["node-1"], "edges": ["edge-1"]},
                        "degraded": False,
                    },
                },
            }
            yield {
                "event": "end",
                "data": {
                    "content": "钱俶在开宝八年纳土归宋。",
                    "references": {"nodes": ["node-1"], "edges": ["edge-1"]},
                },
            }

    monkeypatch.setattr(chat_api, "_build_pi_agent", lambda _project_id: FakeAgent())

    with client.stream(
        "POST",
        f"/api/projects/{project_id}/chat",
        json={"message": "吴越国为什么归宋？", "thread_id": None},
    ) as response:
        assert response.status_code == 200
        assert response.headers.get("X-Thread-Id")
        body = "".join(response.iter_text())

    assert "event: start" in body
    assert "event: tool_call" in body
    assert "event: end" in body
    assert "钱俶在开宝八年纳土归宋" in body

    thread_id = response.headers["X-Thread-Id"]
    rows = asyncio.run(
        get_db().fetchall(
            'SELECT role, content, "references" FROM messages WHERE thread_id = ? ORDER BY id ASC',
            (thread_id,),
        )
    )
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assistant_refs = json.loads(rows[1]["references"])
    assert assistant_refs == {
        "nodes": [{"uuid": "node-1", "name": "钱俶"}],
        "edges": [{"uuid": "edge-1", "name": "钱俶 SURRENDERED_TO 宋太祖"}],
    }


def test_thread_crud_and_delete_cascades_messages(client):
    project = client.post("/api/projects", json={"name": "线程项目"}).json()
    project_id = project["id"]

    create_resp = client.post(
        f"/api/projects/{project_id}/threads",
        json={"title": "归宋讨论", "system_prompt": "保持简洁"},
    )
    assert create_resp.status_code == 201
    thread = create_resp.json()

    rows = asyncio.run(
        get_db().execute(
            'INSERT INTO messages (thread_id, role, content, tool_calls, "references", created_at) '
            "VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (thread["id"], "user", "保存一条消息", None, None),
        )
    )
    assert rows is not None

    list_resp = client.get(f"/api/projects/{project_id}/threads")
    assert list_resp.status_code == 200
    assert [item["id"] for item in list_resp.json()] == [thread["id"]]

    delete_resp = client.delete(f"/api/projects/{project_id}/threads/{thread['id']}")
    assert delete_resp.status_code == 204

    remaining = asyncio.run(
        get_db().fetchall(
            'SELECT id FROM messages WHERE thread_id = ?',
            (thread["id"],),
        )
    )
    assert remaining == []


def test_project_export_import_and_delete_cascade(client, fake_graphiti_client):
    source_project = client.post("/api/projects", json={"name": "导出项目"}).json()
    source_project_id = source_project["id"]

    thread_resp = client.post(
        f"/api/projects/{source_project_id}/threads",
        json={"title": "导出线程", "system_prompt": "记录事实"},
    )
    assert thread_resp.status_code == 201
    thread = thread_resp.json()

    asyncio.run(
        get_db().execute(
            'INSERT INTO messages (thread_id, role, content, tool_calls, "references", created_at) '
            "VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (
                thread["id"],
                "assistant",
                "钱俶纳土归宋。",
                json.dumps([{"name": "memory_search"}]),
                json.dumps({"nodes": ["node-1"], "edges": ["edge-1"]}),
            ),
        )
    )

    capture_resp = client.post(
        "/memory/capture",
        json={"content": "开宝八年，钱俶纳土归宋。", "project_id": source_project_id, "source": "import"},
    )
    assert capture_resp.status_code == 200

    export_resp = client.get(f"/api/projects/{source_project_id}/export")
    assert export_resp.status_code == 200
    export_payload = export_resp.json()
    assert export_payload["project"]["id"] == source_project_id
    assert len(export_payload["threads"]) == 1
    assert len(export_payload["messages"]) == 1
    assert len(export_payload["raw_memories"]) == 1
    assert export_payload["graph"]["nodes"]
    assert export_payload["graph"]["edges"]

    target_project = client.post("/api/projects", json={"name": "导入项目"}).json()
    target_project_id = target_project["id"]

    import_resp = client.post(
        f"/api/projects/{target_project_id}/import",
        json=export_payload,
    )
    assert import_resp.status_code == 200
    import_result = import_resp.json()
    assert import_result == {
        "imported_threads": 1,
        "imported_messages": 1,
        "imported_memories": 1,
    }

    imported_threads = client.get(f"/api/projects/{target_project_id}/threads").json()
    assert len(imported_threads) == 1

    memory_rows = asyncio.run(
        get_db().fetchall(
            "SELECT id FROM raw_memories WHERE project_id = ?",
            (target_project_id,),
        )
    )
    job_rows = asyncio.run(
        get_db().fetchall(
            "SELECT id FROM extract_jobs WHERE project_id = ?",
            (target_project_id,),
        )
    )
    assert len(memory_rows) == 1
    assert len(job_rows) == 1

    delete_resp = client.delete(f"/api/projects/{target_project_id}")
    assert delete_resp.status_code == 204
    assert target_project_id in fake_graphiti_client.deleted_groups

    counts = {
        "projects": asyncio.run(get_db().fetchone("SELECT COUNT(*) AS cnt FROM projects WHERE id = ?", (target_project_id,)))["cnt"],
        "threads": asyncio.run(get_db().fetchone("SELECT COUNT(*) AS cnt FROM threads WHERE project_id = ?", (target_project_id,)))["cnt"],
        "raw_memories": asyncio.run(get_db().fetchone("SELECT COUNT(*) AS cnt FROM raw_memories WHERE project_id = ?", (target_project_id,)))["cnt"],
        "extract_jobs": asyncio.run(get_db().fetchone("SELECT COUNT(*) AS cnt FROM extract_jobs WHERE project_id = ?", (target_project_id,)))["cnt"],
    }
    assert counts == {"projects": 0, "threads": 0, "raw_memories": 0, "extract_jobs": 0}
