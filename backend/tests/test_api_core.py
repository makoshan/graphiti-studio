from __future__ import annotations

import asyncio
import io
import json
from types import MethodType

import app.api.chat as chat_api
from app.db import get_db


def test_settings_get_and_update_masks_keys(client):
    update = {
        "agent_runtime": "pi-rpc",
        "pi_provider": "kimi-coding",
        "pi_model": "k2p5",
        "pi_api_key": "sk-kimi-coding-9999",
        "llm_api_key": "sk-secret-1234",
        "graphiti_api_key": "graphiti-secret-5678",
        "llm_base_url": "https://llm.test/v1",
        "llm_model": "demo-model",
        "graphiti_summary_language": "zh-CN",
        "theme": "dark",
    }
    put_resp = client.put("/api/settings", json=update)
    assert put_resp.status_code == 200

    body = put_resp.json()
    assert body["agent_runtime"] == "pi-rpc"
    assert body["pi_provider"] == "kimi-coding"
    assert body["pi_model"] == "k2p5"
    assert body["pi_api_key"].endswith("9999")
    assert body["pi_api_key"] != update["pi_api_key"]
    assert body["llm_api_key"].endswith("1234")
    assert body["llm_api_key"] != update["llm_api_key"]
    assert body["graphiti_api_key"].endswith("5678")
    assert body["theme"] == "dark"

    get_resp = client.get("/api/settings")
    assert get_resp.status_code == 200
    current = get_resp.json()
    assert current["agent_runtime"] == "pi-rpc"
    assert current["llm_model"] == "demo-model"
    assert current["llm_api_key"].endswith("1234")
    assert current["graphiti_summary_language"] == "zh-CN"


def test_settings_update_ignores_masked_api_key_placeholders(client):
    first = client.put(
        "/api/settings",
        json={
            "pi_api_key": "sk-pi-real-8888",
            "llm_api_key": "sk-real-1234",
            "graphiti_api_key": "graphiti-real-5678",
        },
    )
    assert first.status_code == 200

    second = client.put(
        "/api/settings",
        json={
            "pi_api_key": "********8888",
            "llm_api_key": "********1234",
            "graphiti_api_key": "********5678",
            "llm_model": "kimi-k2-thinking",
        },
    )
    assert second.status_code == 200

    db_row = asyncio.run(get_db().fetchone("SELECT * FROM settings WHERE id = 1"))
    saved = dict(db_row)
    assert saved["pi_api_key"] == "sk-pi-real-8888"
    assert saved["llm_api_key"] == "sk-real-1234"
    assert saved["graphiti_api_key"] == "graphiti-real-5678"
    assert saved["llm_model"] == "kimi-k2-thinking"


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
            episodes=[f"ep-{i:04d}"],
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
    assert graph["edges"][0]["episodes"] == ["ep-0000"]


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


def test_extract_uses_configured_summary_language(client, fake_graphiti_client):
    project = client.post("/api/projects", json={"name": "中文摘要项目"}).json()
    project_id = project["id"]

    update_resp = client.put(
        "/api/settings",
        json={"graphiti_summary_language": "zh-CN"},
    )
    assert update_resp.status_code == 200

    capture_resp = client.post(
        "/memory/capture",
        json={"content": "Graphiti powers Zep", "project_id": project_id, "source": "note"},
    )
    assert capture_resp.status_code == 200
    capture = capture_resp.json()

    from app.services.memory_adapter import get_memory_adapter

    asyncio.run(
        get_memory_adapter()._extract(
            capture["job_id"],
            capture["id"],
            project_id,
            "Graphiti powers Zep",
        )
    )

    last_call = fake_graphiti_client.graph.batch_calls[-1]
    assert last_call["graph_id"] == project_id
    assert last_call["episodes"][0]["summary_language"] == "zh-CN"


def test_chat_uses_pi_rpc_runtime_when_configured(client, monkeypatch):
    project = client.post("/api/projects", json={"name": "Pi RPC"}).json()
    project_id = project["id"]

    class StubPiRpcAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def chat(self, messages, system_prompt=None):
            assert self.kwargs["project_id"] == project_id
            assert self.kwargs["provider"] == "kimi-coding"
            assert self.kwargs["model"] == "k2p5"
            assert self.kwargs["api_key"] == "sk-kimi-rpc"
            assert messages[-1]["content"] == "惠泉寺是什么？"
            assert system_prompt
            yield {"event": "start", "data": {"role": "assistant"}}
            yield {"event": "text_chunk", "data": {"text": "惠泉寺是一座寺院。"}}
            yield {
                "event": "tool_call",
                "data": {"id": "call_1", "name": "memory_search", "arguments": "{\"query\":\"惠泉寺\"}"},
            }
            yield {
                "event": "tool_result",
                "data": {
                    "id": "call_1",
                    "result": {
                        "results": [{"snippet": "惠泉在钱塘长寿乡大遮山惠泉寺"}],
                        "references": {"nodes": ["node-1"], "edges": []},
                        "degraded": False,
                    },
                },
            }
            yield {
                "event": "end",
                "data": {
                    "content": "惠泉寺是一座寺院。",
                    "references": {"nodes": ["node-1"], "edges": []},
                },
            }

    monkeypatch.setattr(chat_api.Config, "AGENT_RUNTIME", "pi-rpc")
    monkeypatch.setattr(chat_api.Config, "PI_PROVIDER", "kimi-coding")
    monkeypatch.setattr(chat_api.Config, "PI_MODEL", "k2p5")
    monkeypatch.setattr(chat_api.Config, "PI_API_KEY", "sk-kimi-rpc")
    monkeypatch.setattr(chat_api, "PiRpcAgent", StubPiRpcAgent)

    response = client.post(
        f"/api/projects/{project_id}/chat",
        json={"message": "惠泉寺是什么？"},
    )
    assert response.status_code == 200
    body = response.text
    assert "event: tool_call" in body
    assert "惠泉寺是一座寺院。" in body


def test_project_episode_detail_returns_episode_content_and_linked_raw_memory(client, fake_graphiti_client):
    project = client.post("/api/projects", json={"name": "证据项目"}).json()
    project_id = project["id"]

    fake_graphiti_client.episode_records["ep-linked"] = fake_graphiti_client.episode_records["ep-1"].__class__(
        uuid="ep-linked",
        name=f"{project_id}-episode-1",
        group_id=project_id,
        content="这是关联到原始文本块的 episode 内容。",
        source="EpisodeType.message",
        source_description="raw_memory:mem-linked",
        processed=True,
    )

    asyncio.run(
        get_db().execute(
            """
            INSERT INTO raw_memories
                (id, project_id, content, source, graph_group_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (
                "mem-linked",
                project_id,
                "这是关联到原始文本块的 episode 内容。",
                "note",
                project_id,
            ),
        )
    )

    detail_resp = client.get(f"/api/projects/{project_id}/episodes/ep-linked")
    assert detail_resp.status_code == 200
    payload = detail_resp.json()

    assert payload["episode"]["uuid"] == "ep-linked"
    assert payload["episode"]["content"] == "这是关联到原始文本块的 episode 内容。"
    assert payload["episode"]["source_description"] == "raw_memory:mem-linked"
    assert payload["raw_memory"]["id"] == "mem-linked"
    assert payload["raw_memory"]["content"] == "这是关联到原始文本块的 episode 内容。"


def test_project_upload_splits_text_using_overlap_setting(client):
    project = client.post(
        "/api/projects",
        json={"name": "上传项目", "settings": {"chunk_size": 8, "chunk_overlap": 2}},
    ).json()
    project_id = project["id"]

    upload_resp = client.post(
        f"/api/projects/{project_id}/upload",
        files={"files": ("sample.txt", io.BytesIO(b"abcdefghijklmno"), "text/plain")},
    )
    assert upload_resp.status_code == 200
    payload = upload_resp.json()

    assert payload["total_chunks"] >= 2
    rows = asyncio.run(
        get_db().fetchall(
            "SELECT content FROM raw_memories WHERE project_id = ? ORDER BY created_at ASC",
            (project_id,),
        )
    )
    assert len(rows) == payload["total_chunks"]
    assert rows[0]["content"].startswith("abcdefgh")


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


def test_chat_reuses_thread_history_without_replaying_tool_calls(client, monkeypatch):
    project = client.post("/api/projects", json={"name": "连续对话项目"}).json()
    project_id = project["id"]

    thread_id = "thread-history-1"
    asyncio.run(
        get_db().execute(
            "INSERT INTO threads (id, project_id, title, system_prompt, created_at) VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (thread_id, project_id, "历史线程", ""),
        )
    )
    asyncio.run(
        get_db().execute(
            'INSERT INTO messages (thread_id, role, content, tool_calls, "references", created_at) '
            "VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (thread_id, "user", "先前的问题", None, None),
        )
    )
    asyncio.run(
        get_db().execute(
            'INSERT INTO messages (thread_id, role, content, tool_calls, "references", created_at) '
            "VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (
                thread_id,
                "assistant",
                "先前的回答",
                json.dumps([{"id": "call-1", "name": "memory_search"}]),
                json.dumps({"nodes": ["node-1"], "edges": []}),
            ),
        )
    )

    class FakeAgent:
        async def chat(self, messages, system_prompt=None):
            assert messages == [
                {"role": "user", "content": "先前的问题"},
                {"role": "assistant", "content": "先前的回答"},
                {"role": "user", "content": "继续追问"},
            ]
            yield {"event": "start", "data": {"role": "assistant"}}
            yield {"event": "end", "data": {"content": "后续回答", "references": {"nodes": [], "edges": []}}}

    monkeypatch.setattr(chat_api, "_build_pi_agent", lambda _project_id: FakeAgent())

    with client.stream(
        "POST",
        f"/api/projects/{project_id}/chat",
        json={"message": "继续追问", "thread_id": thread_id},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "后续回答" in body


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


def test_thread_messages_endpoint_returns_persisted_history_in_order(client):
    project = client.post("/api/projects", json={"name": "历史项目"}).json()
    project_id = project["id"]

    thread = client.post(
        f"/api/projects/{project_id}/threads",
        json={"title": "历史会话"},
    ).json()

    asyncio.run(
        get_db().execute(
            'INSERT INTO messages (thread_id, role, content, tool_calls, "references", created_at) '
            "VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (thread["id"], "user", "第一条问题", None, None),
        )
    )
    asyncio.run(
        get_db().execute(
            'INSERT INTO messages (thread_id, role, content, tool_calls, "references", created_at) '
            "VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (
                thread["id"],
                "assistant",
                "第一条回答",
                json.dumps([{"name": "memory_search"}]),
                json.dumps({"nodes": [{"uuid": "node-1", "name": "钱俶"}], "edges": []}),
            ),
        )
    )

    resp = client.get(f"/api/projects/{project_id}/threads/{thread['id']}/messages")
    assert resp.status_code == 200
    payload = resp.json()

    assert [item["role"] for item in payload] == ["user", "assistant"]
    assert payload[1]["references"]["nodes"][0]["uuid"] == "node-1"


def test_thread_history_skips_empty_assistant_messages(client):
    project = client.post("/api/projects", json={"name": "空回复过滤项目"}).json()
    project_id = project["id"]

    thread = client.post(
        f"/api/projects/{project_id}/threads",
        json={"title": "过滤空回复"},
    ).json()

    asyncio.run(
        get_db().execute(
            'INSERT INTO messages (thread_id, role, content, tool_calls, "references", created_at) '
            "VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (thread["id"], "user", "第一条问题", None, None),
        )
    )
    asyncio.run(
        get_db().execute(
            'INSERT INTO messages (thread_id, role, content, tool_calls, "references", created_at) '
            "VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (thread["id"], "assistant", "", None, None),
        )
    )
    asyncio.run(
        get_db().execute(
            'INSERT INTO messages (thread_id, role, content, tool_calls, "references", created_at) '
            "VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (thread["id"], "user", "第二条问题", None, None),
        )
    )

    resp = client.get(f"/api/projects/{project_id}/threads/{thread['id']}/messages")
    assert resp.status_code == 200
    payload = resp.json()

    assert [item["role"] for item in payload] == ["user", "user"]


def test_chat_does_not_persist_empty_assistant_message_on_error(client, monkeypatch):
    project = client.post("/api/projects", json={"name": "错误续聊项目"}).json()
    project_id = project["id"]

    class FailingAgent:
        async def chat(self, messages, system_prompt=None):
            yield {"event": "start", "data": {"role": "assistant"}}
            yield {"event": "error", "data": {"message": "upstream failure"}}

    monkeypatch.setattr(chat_api, "_build_pi_agent", lambda _project_id: FailingAgent())

    with client.stream(
        "POST",
        f"/api/projects/{project_id}/chat",
        json={"message": "会失败吗？", "thread_id": None},
    ) as response:
        assert response.status_code == 200
        thread_id = response.headers["X-Thread-Id"]
        body = "".join(response.iter_text())

    assert "event: error" in body

    rows = asyncio.run(
        get_db().fetchall(
            "SELECT role, content FROM messages WHERE thread_id = ? ORDER BY id ASC",
            (thread_id,),
        )
    )
    assert [row["role"] for row in rows] == ["user"]


def test_list_threads_orders_by_latest_message_activity(client):
    project = client.post("/api/projects", json={"name": "排序项目"}).json()
    project_id = project["id"]

    older = client.post(f"/api/projects/{project_id}/threads", json={"title": "较早线程"}).json()
    newer = client.post(f"/api/projects/{project_id}/threads", json={"title": "较新线程"}).json()

    asyncio.run(
        get_db().execute(
            'INSERT INTO messages (thread_id, role, content, tool_calls, "references", created_at) '
            "VALUES (?, ?, ?, ?, ?, '2026-03-12T10:00:00.000000Z')",
            (older["id"], "assistant", "旧消息", None, None),
        )
    )
    asyncio.run(
        get_db().execute(
            'INSERT INTO messages (thread_id, role, content, tool_calls, "references", created_at) '
            "VALUES (?, ?, ?, ?, ?, '2026-03-12T12:00:00.000000Z')",
            (newer["id"], "assistant", "新消息", None, None),
        )
    )

    resp = client.get(f"/api/projects/{project_id}/threads")
    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()][:2] == [newer["id"], older["id"]]


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
