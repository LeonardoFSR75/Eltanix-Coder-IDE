import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["NOVAAI_STUDIO_API_KEY"] = "chave-de-teste"

from novaai_studio.main import app

client = TestClient(app)


def test_trello_api_crud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("novaai_studio.api.routes.trello._projects_root", lambda req: tmp_path)

    project_dir = tmp_path / "test-proj"
    project_dir.mkdir()

    headers = {"Authorization": "Bearer chave-de-teste"}

    # 1. List cards (creates samples if empty)
    res = client.get("/api/projects/test-proj/trello", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["project"] == "test-proj"
    assert len(data["cards"]) >= 3

    # 2. Create card
    res_create = client.post(
        "/api/projects/test-proj/trello",
        json={
          "title": "Nova Tarefa do Teste",
          "description": "Detalhes da tarefa",
          "status": "todo",
          "priority": "high",
        },
        headers=headers,
    )
    assert res_create.status_code == 200
    card_created = res_create.json()["card"]
    card_id = card_created["id"]
    assert card_created["title"] == "Nova Tarefa do Teste"

    # 3. Update card status
    res_update = client.put(
        f"/api/projects/test-proj/trello/{card_id}",
        json={"status": "in_progress"},
        headers=headers,
    )
    assert res_update.status_code == 200
    assert res_update.json()["card"]["status"] == "in_progress"

    # 4. Delete card
    res_del = client.delete(f"/api/projects/test-proj/trello/{card_id}", headers=headers)
    assert res_del.status_code == 200
    assert res_del.json()["ok"] is True
