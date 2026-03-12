from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import Config
import app.db as db_module
import app.main as main_module
import app.runtime_settings as runtime_settings_module
import app.services.graphiti_client as graphiti_client_module
import app.services.memory_adapter as memory_adapter_module


@dataclass
class FakeGraphRecord:
    uuid: str
    name: str | None = None
    fact: str | None = None
    source_node_uuid: str | None = None
    target_node_uuid: str | None = None
    score: float = 0.0


class _FakeNodeOps:
    def __init__(self, records: dict[str, FakeGraphRecord]):
        self._records = records

    async def get_by_graph_id(self, _graph_id: str, limit: int = 500, uuid_cursor: str | None = None):
        records = list(self._records.values())
        if uuid_cursor:
            for idx, record in enumerate(records):
                if record.uuid == uuid_cursor:
                    records = records[idx + 1 :]
                    break
        return records[:limit]

    async def get(self, uuid_: str):
        record = self._records.get(uuid_)
        return record or FakeGraphRecord(uuid=uuid_, name=uuid_[:8])


class _FakeEdgeOps:
    def __init__(self, records: dict[str, FakeGraphRecord]):
        self._records = records

    async def get_by_graph_id(self, _graph_id: str, limit: int = 2000, uuid_cursor: str | None = None):
        records = list(self._records.values())
        if uuid_cursor:
            for idx, record in enumerate(records):
                if record.uuid == uuid_cursor:
                    records = records[idx + 1 :]
                    break
        return records[:limit]

    async def get(self, uuid_: str):
        record = self._records.get(uuid_)
        return record or FakeGraphRecord(uuid=uuid_, fact=uuid_[:8])


class _FakeGraphOps:
    def __init__(self, node_records: dict[str, FakeGraphRecord], edge_records: dict[str, FakeGraphRecord]):
        self.node = _FakeNodeOps(node_records)
        self.edge = _FakeEdgeOps(edge_records)

    async def add_batch(self, _graph_id: str, _episodes):
        return []


class FakeGraphitiClient:
    def __init__(self):
        self.created_groups: list[tuple[str, str, str]] = []
        self.deleted_groups: list[str] = []
        self.search_payload: list[dict] = []
        self.remote_groups: list[dict] = []
        self.node_records = {
            "node-1": FakeGraphRecord(uuid="node-1", name="钱俶"),
            "node-2": FakeGraphRecord(uuid="node-2", name="宋太祖"),
        }
        self.edge_records = {
            "edge-1": FakeGraphRecord(
                uuid="edge-1",
                fact="钱俶 SURRENDERED_TO 宋太祖",
                source_node_uuid="node-1",
                target_node_uuid="node-2",
                score=0.95,
            )
        }
        self.graph = _FakeGraphOps(self.node_records, self.edge_records)

    async def create_group(self, group_id: str, *, name: str = "", description: str = ""):
        self.created_groups.append((group_id, name, description))
        return {"group_id": group_id}

    async def list_groups(self) -> list[dict]:
        created = [
            {"group_id": group_id, "name": name or group_id, "description": description}
            for group_id, name, description in self.created_groups
        ]
        return [*self.remote_groups, *created]

    async def delete_group(self, group_id: str):
        self.deleted_groups.append(group_id)
        return {"ok": True}

    async def get_group_stats(self, _group_id: str) -> dict[str, int]:
        return {"node_count": len(self.node_records), "edge_count": len(self.edge_records)}

    async def get_group_graph(
        self,
        _group_id: str,
        *,
        max_nodes: int = 2000,
        node_page_size: int = 100,
        edge_page_size: int = 100,
    ) -> dict[str, list[FakeGraphRecord]]:
        nodes: list[FakeGraphRecord] = []
        cursor: str | None = None
        while True:
            page = await self.graph.node.get_by_graph_id(_group_id, limit=node_page_size, uuid_cursor=cursor)
            if not page:
                break
            nodes.extend(page)
            if len(nodes) >= max_nodes:
                nodes = nodes[:max_nodes]
                break
            if len(page) < node_page_size:
                break
            cursor = page[-1].uuid

        edges: list[FakeGraphRecord] = []
        cursor = None
        while True:
            page = await self.graph.edge.get_by_graph_id(_group_id, limit=edge_page_size, uuid_cursor=cursor)
            if not page:
                break
            edges.extend(page)
            if len(page) < edge_page_size:
                break
            cursor = page[-1].uuid

        return {"nodes": nodes, "edges": edges}

    async def search(self, *, query: str, group_id: str, limit: int = 10) -> list[dict]:
        if self.search_payload:
            return self.search_payload[:limit]
        return [
            {
                "uuid": "edge-1",
                "fact": f"{query} -> 钱俶 SURRENDERED_TO 宋太祖",
                "source_node_uuid": "node-1",
                "target_node_uuid": "node-2",
                "score": 0.95,
                "source": "graph",
                "group_id": group_id,
            }
        ]

    async def health(self) -> bool:
        return True


def _disable_background_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_create_task(coro):
        coro.close()
        return SimpleNamespace(cancel=lambda: None)

    monkeypatch.setattr(memory_adapter_module.asyncio, "create_task", fake_create_task)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(Config, "STUDIO_DATA_DIR", str(data_dir))
    monkeypatch.setattr(Config, "LLM_API_KEY", "test-llm-key")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setattr(Config, "LLM_MODEL", "test-model")
    monkeypatch.setattr(Config, "GRAPHITI_BASE_URL", "http://graphiti.test")
    monkeypatch.setattr(Config, "GRAPHITI_API_KEY", "test-graphiti-key")

    db_module._db_instance = None
    graphiti_client_module._client_instance = FakeGraphitiClient()
    memory_adapter_module._adapter_instance = None
    monkeypatch.setattr(runtime_settings_module, "reset_graphiti_client", lambda: None)
    monkeypatch.setattr(runtime_settings_module, "reset_memory_adapter", lambda: None)

    _disable_background_extract(monkeypatch)

    with TestClient(main_module.app) as test_client:
        yield test_client

    db = db_module.get_db()
    asyncio.run(db.close())
    db_module._db_instance = None
    graphiti_client_module._client_instance = None
    memory_adapter_module._adapter_instance = None


@pytest.fixture
def fake_graphiti_client() -> FakeGraphitiClient:
    client = graphiti_client_module.get_graphiti_client()
    assert isinstance(client, FakeGraphitiClient)
    return client
