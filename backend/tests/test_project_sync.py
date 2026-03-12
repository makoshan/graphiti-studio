from __future__ import annotations

import app.config as config_module


def test_list_projects_auto_imports_remote_graph_groups(client, fake_graphiti_client):
    fake_graphiti_client.remote_groups = [
        {
            "group_id": "remote-wuyue",
            "name": "吴越图谱",
            "description": "从 Neo4j 自动同步的远程项目",
        }
    ]

    response = client.get("/api/projects")
    assert response.status_code == 200

    projects = response.json()
    assert len(projects) == 1
    assert projects[0]["id"] == "remote-wuyue"
    assert projects[0]["name"] == "吴越图谱"
    assert projects[0]["description"] == "从 Neo4j 自动同步的远程项目"
    assert projects[0]["node_count"] == 2
    assert projects[0]["edge_count"] == 1


def test_list_projects_uses_mirofish_metadata_for_remote_graph_names(client, fake_graphiti_client, monkeypatch):
    fake_graphiti_client.remote_groups = [
        {
            "group_id": "mirofish_ceb2869cf5a341cc",
            "name": "Unnamed Project",
            "description": "MiroFish Social Simulation Graph",
        }
    ]

    import app.api.projects as projects_api

    monkeypatch.setattr(
        projects_api,
        "_load_mirofish_project_metadata",
        lambda: {
            "mirofish_ceb2869cf5a341cc": {
                "name": "模拟社交媒体平台发布新推荐算法后的舆情反应",
                "description": "来自 MiroFish 本地项目元数据",
            }
        },
    )

    response = client.get("/api/projects")
    assert response.status_code == 200

    projects = response.json()
    assert len(projects) == 1
    assert projects[0]["id"] == "mirofish_ceb2869cf5a341cc"
    assert projects[0]["name"] == "模拟社交媒体平台发布新推荐算法后的舆情反应"
    assert projects[0]["description"] == "来自 MiroFish 本地项目元数据"


def test_updating_settings_applies_runtime_graphiti_config(client):
    response = client.put(
        "/api/settings",
        json={
            "graphiti_base_url": "http://127.0.0.1:8999",
            "graphiti_api_key": "graphiti-updated-9999",
            "llm_model": "gpt-4.1-mini",
        },
    )
    assert response.status_code == 200

    assert config_module.Config.GRAPHITI_BASE_URL == "http://127.0.0.1:8999"
    assert config_module.Config.GRAPHITI_API_KEY == "graphiti-updated-9999"
    assert config_module.Config.LLM_MODEL == "gpt-4.1-mini"


def test_list_projects_refreshes_stale_cached_counts_for_existing_remote_project(client, fake_graphiti_client):
    fake_graphiti_client.remote_groups = [
        {
            "group_id": "remote-counts",
            "name": "远程图谱",
            "description": "需要刷新计数",
        }
    ]

    first = client.get("/api/projects")
    assert first.status_code == 200
    assert first.json()[0]["node_count"] == 2
    assert first.json()[0]["edge_count"] == 1

    fake_graphiti_client.node_records["node-3"] = fake_graphiti_client.node_records["node-1"].__class__(
        uuid="node-3", name="赵匡胤"
    )
    fake_graphiti_client.edge_records["edge-2"] = fake_graphiti_client.edge_records["edge-1"].__class__(
        uuid="edge-2",
        fact="宋太祖 ALLIED_WITH 赵匡胤",
        source_node_uuid="node-2",
        target_node_uuid="node-3",
        score=0.88,
    )

    second = client.get("/api/projects")
    assert second.status_code == 200
    assert second.json()[0]["node_count"] == 3
    assert second.json()[0]["edge_count"] == 2
