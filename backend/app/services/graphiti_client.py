"""Async Graphiti client adapter.

Provides an httpx.AsyncClient-based interface for communicating with a
Graphiti server (typically backed by Neo4j).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import httpx

from ..config import Config


@dataclass
class EpisodeData:
    data: str
    type: str = "text"


@dataclass
class EntityEdgeSourceTarget:
    source: str
    target: str


def _to_obj(value: Any) -> Any:
    """Recursively convert dicts to SimpleNamespace for attribute access."""
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _to_obj(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_to_obj(v) for v in value]
    return value


class _AsyncGraphitiHTTP:
    """Low-level async HTTP transport for Graphiti API calls."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float,
        trust_env: bool,
        ingest_timeout: float,
    ):
        self._ingest_timeout = ingest_timeout
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            trust_env=trust_env,
            follow_redirects=True,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        if "timeout" not in kwargs and path.endswith("/episodes:batch"):
            kwargs["timeout"] = self._ingest_timeout
        resp = await self._client.request(method, path, **kwargs)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip() if exc.response is not None else ""
            if detail:
                message = f"{exc}. Response body: {detail[:500]}"
                raise httpx.HTTPStatusError(
                    message, request=exc.request, response=exc.response
                ) from exc
            raise
        if not resp.content:
            return None
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()


class _EpisodeOps:
    def __init__(self, http: _AsyncGraphitiHTTP):
        self._http = http

    async def get(self, uuid_: str):
        return _to_obj(await self._http.request("GET", f"/v1/episodes/{uuid_}"))


class _NodeOps:
    def __init__(self, http: _AsyncGraphitiHTTP):
        self._http = http

    async def get_by_graph_id(
        self, graph_id: str, limit: int = 100, uuid_cursor: str | None = None
    ):
        params: dict[str, Any] = {"limit": limit}
        if uuid_cursor:
            params["uuid_cursor"] = uuid_cursor
        data = (
            await self._http.request(
                "GET", f"/v1/groups/{graph_id}/nodes", params=params
            )
            or []
        )
        return [_to_obj(item) for item in data]

    async def get_entity_edges(self, node_uuid: str):
        data = (
            await self._http.request("GET", f"/v1/nodes/{node_uuid}/edges") or []
        )
        return [_to_obj(item) for item in data]

    async def get(self, uuid_: str):
        return _to_obj(await self._http.request("GET", f"/v1/nodes/{uuid_}"))


class _EdgeOps:
    def __init__(self, http: _AsyncGraphitiHTTP):
        self._http = http

    async def get_by_graph_id(
        self, graph_id: str, limit: int = 100, uuid_cursor: str | None = None
    ):
        params: dict[str, Any] = {"limit": limit}
        if uuid_cursor:
            params["uuid_cursor"] = uuid_cursor
        data = (
            await self._http.request(
                "GET", f"/v1/groups/{graph_id}/edges", params=params
            )
            or []
        )
        return [_to_obj(item) for item in data]

    async def get(self, uuid_: str):
        return _to_obj(await self._http.request("GET", f"/v1/edges/{uuid_}"))


class _GraphOps:
    def __init__(self, http: _AsyncGraphitiHTTP):
        self._http = http
        self.node = _NodeOps(http)
        self.edge = _EdgeOps(http)
        self.episode = _EpisodeOps(http)

    async def create(self, graph_id: str, name: str, description: str):
        return _to_obj(
            await self._http.request(
                "POST",
                "/v1/groups",
                json={
                    "group_id": graph_id,
                    "name": name,
                    "description": description,
                },
            )
        )

    async def set_ontology(
        self,
        graph_ids: list[str],
        entities: dict[str, Any] | None = None,
        edges: dict[str, Any] | None = None,
    ):
        for gid in graph_ids:
            await self._http.request(
                "POST",
                f"/v1/groups/{gid}/ontology",
                json={"entities": entities or {}, "edges": edges or {}},
            )

    async def add_batch(self, graph_id: str, episodes: list[EpisodeData]):
        payload = [{"content": ep.data, "type": ep.type} for ep in episodes]
        data = (
            await self._http.request(
                "POST",
                f"/v1/groups/{graph_id}/episodes:batch",
                json={"episodes": payload},
            )
            or []
        )
        return [_to_obj(item) for item in data]

    async def search(self, **kwargs: Any):
        graph_id = kwargs.pop("graph_id")
        return _to_obj(
            await self._http.request(
                "POST", f"/v1/groups/{graph_id}/search", json=kwargs
            )
        )

    async def delete(self, graph_id: str):
        return await self._http.request("DELETE", f"/v1/groups/{graph_id}")


class AsyncGraphitiClient:
    """Async client for interacting with a Graphiti server."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float,
        trust_env: bool = False,
        ingest_timeout: float = 180.0,
    ):
        self._http = _AsyncGraphitiHTTP(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            trust_env=trust_env,
            ingest_timeout=ingest_timeout,
        )
        self.graph = _GraphOps(self._http)

    async def close(self) -> None:
        await self._http.close()

    # ---------------------------------------------------------------
    # Convenience wrappers used by the projects API
    # ---------------------------------------------------------------

    async def list_groups(self) -> list[dict]:
        """List all groups from graphiti-zep."""
        data = await self._http.request("GET", "/v1/groups")
        if isinstance(data, list):
            return data
        return []

    async def get_group(self, group_id: str) -> dict | None:
        """Get a single group's metadata."""
        try:
            data = await self._http.request("GET", f"/v1/groups/{group_id}")
            return data if isinstance(data, dict) else None
        except httpx.HTTPStatusError:
            return None

    async def create_group(self, group_id: str, *, name: str = "", description: str = ""):
        """Create a graphiti-zep group (convenience wrapper)."""
        return await self.graph.create(group_id, name or group_id, description)

    async def delete_group(self, group_id: str):
        """Delete a graphiti-zep group (convenience wrapper)."""
        return await self.graph.delete(group_id)

    async def get_group_stats(self, group_id: str) -> dict[str, int]:
        """Fetch node/edge counts for a group.

        Tries ``GET /v1/groups/{group_id}/stats`` first.  If the endpoint
        does not exist, falls back to counting nodes and edges via the
        listing endpoints.
        """
        try:
            data = await self._http.request("GET", f"/v1/groups/{group_id}/stats")
            if isinstance(data, dict):
                return {
                    "node_count": data.get("node_count", 0),
                    "edge_count": data.get("edge_count", 0),
                }
        except httpx.HTTPStatusError:
            pass

        async def _count_all(fetch_page, limit: int) -> int:
            total = 0
            cursor: str | None = None
            seen_cursors: set[str] = set()

            while True:
                page = await fetch_page(group_id, limit=limit, uuid_cursor=cursor)
                if not page:
                    break

                total += len(page)
                if len(page) < limit:
                    break

                last = page[-1]
                next_cursor = getattr(last, "uuid_", None) or getattr(last, "uuid", None)
                if not next_cursor or next_cursor in seen_cursors:
                    break

                seen_cursors.add(next_cursor)
                cursor = next_cursor

            return total

        nodes = await _count_all(self.graph.node.get_by_graph_id, limit=500)
        edges = await _count_all(self.graph.edge.get_by_graph_id, limit=2000)
        return {
            "node_count": nodes,
            "edge_count": edges,
        }

    async def _fetch_all_items(
        self,
        fetch_page,
        group_id: str,
        *,
        page_limit: int,
        max_items: int | None = None,
    ) -> list[Any]:
        items: list[Any] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            page = await fetch_page(group_id, limit=page_limit, uuid_cursor=cursor)
            if not page:
                break

            items.extend(page)
            if max_items is not None and len(items) >= max_items:
                items = items[:max_items]
                break

            if len(page) < page_limit:
                break

            last = page[-1]
            next_cursor = getattr(last, "uuid_", None) or getattr(last, "uuid", None)
            if not next_cursor or next_cursor in seen_cursors:
                break

            seen_cursors.add(next_cursor)
            cursor = next_cursor

        return items

    async def get_group_graph(
        self,
        group_id: str,
        *,
        max_nodes: int = 2000,
        node_page_size: int = 100,
        edge_page_size: int = 100,
    ) -> dict[str, list[Any]]:
        """Fetch a paginated graph snapshot for visualization.

        Mirrors the main MiroFish app behavior: nodes are capped to avoid
        overwhelming the browser, while edges are fetched across all pages.
        """
        nodes = await self._fetch_all_items(
            self.graph.node.get_by_graph_id,
            group_id,
            page_limit=node_page_size,
            max_items=max_nodes,
        )
        edges = await self._fetch_all_items(
            self.graph.edge.get_by_graph_id,
            group_id,
            page_limit=edge_page_size,
        )
        return {"nodes": nodes, "edges": edges}

    async def search(self, *, query: str, group_id: str, limit: int = 10) -> list[dict]:
        """Search the knowledge graph (convenience wrapper)."""
        result = await self.graph.search(graph_id=group_id, query=query, limit=limit)
        if isinstance(result, list):
            return result
        # graphiti-zep may return {"facts": [...]} or {"results": [...]}
        if hasattr(result, "facts"):
            return result.facts if isinstance(result.facts, list) else []
        if hasattr(result, "results"):
            return result.results if isinstance(result.results, list) else []
        return []

    async def health(self) -> bool:
        """Check graphiti-zep server health."""
        try:
            await self._http.request("GET", "/healthcheck")
            return True
        except Exception:
            return False


def create_graphiti_client(
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
) -> AsyncGraphitiClient:
    """Factory function with sensible defaults from Config."""
    return AsyncGraphitiClient(
        base_url=base_url or Config.GRAPHITI_BASE_URL,
        api_key=api_key or Config.GRAPHITI_API_KEY,
        timeout=timeout or Config.GRAPHITI_TIMEOUT_SECONDS,
        trust_env=Config.GRAPHITI_TRUST_ENV,
        ingest_timeout=Config.GRAPHITI_INGEST_TIMEOUT_SECONDS,
    )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_client_instance: AsyncGraphitiClient | None = None


def get_graphiti_client() -> AsyncGraphitiClient:
    """Return a lazily-created singleton AsyncGraphitiClient."""
    global _client_instance
    if _client_instance is None:
        _client_instance = create_graphiti_client()
    return _client_instance


def reset_graphiti_client() -> None:
    """Drop the cached singleton so the next access uses fresh config."""
    global _client_instance
    _client_instance = None
