from __future__ import annotations

import uuid
import pytest
from fastapi.testclient import TestClient

from app import config, main
from app.db import session as db_session_module
from app.db.models import Project, User


def register_and_login(client: TestClient, email: str) -> None:
    client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "name": "Sprint Tester"},
        headers={"Origin": config.app_config.frontend_url},
    )
    client.post(
        "/auth/login",
        json={"email": email, "password": "Password123!"},
        headers={"Origin": config.app_config.frontend_url},
    )


def test_sprint_crud_and_isolation():
    client = TestClient(main.app)
    uid_a = f"user_a_{uuid.uuid4().hex[:8]}@example.com"
    uid_b = f"user_b_{uuid.uuid4().hex[:8]}@example.com"

    register_and_login(client, uid_a)

    # Criar projeto para Usuário A
    with db_session_module.SessionLocal() as session:
        user_a = session.query(User).filter(User.email == uid_a).first()
        assert user_a is not None
        proj_a = Project(
            id=f"proj-a-{uuid.uuid4().hex[:6]}",
            user_id=user_a.id,
            name="Projeto Sprints A",
            timezone="America/Sao_Paulo",
        )
        session.add(proj_a)
        session.commit()
        project_id = proj_a.id

    # 1. POST /projects/{pid}/sprints (Criar Sprint 1)
    res_create = client.post(
        f"/projects/{project_id}/sprints",
        json={
            "name": "Sprint 1",
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        },
        headers={"Origin": config.app_config.frontend_url},
    )
    assert res_create.status_code == 201, res_create.text
    data_create = res_create.json()
    assert data_create["name"] == "Sprint 1"
    assert data_create["start_civil"] == "2026-03-01"
    assert data_create["end_civil"] == "2026-03-14"
    sprint_id = data_create["id"]

    # 2. POST /projects/{pid}/sprints (Criar Sprint 2)
    res_create_2 = client.post(
        f"/projects/{project_id}/sprints",
        json={
            "name": "Sprint 2",
            "start_date": "2026-03-15",
            "end_date": "2026-03-28",
        },
        headers={"Origin": config.app_config.frontend_url},
    )
    assert res_create_2.status_code == 201
    sprint_2_id = res_create_2.json()["id"]

    # 3. GET /projects/{pid}/sprints (Listar)
    res_list = client.get(
        f"/projects/{project_id}/sprints",
        headers={"Origin": config.app_config.frontend_url},
    )
    assert res_list.status_code == 200
    sprints = res_list.json()
    assert len(sprints) >= 2
    assert sprints[0]["name"] == "Sprint 1"
    assert sprints[1]["name"] == "Sprint 2"

    # 4. PUT /projects/{pid}/sprints/{sprint_id} (Atualizar)
    res_update = client.put(
        f"/projects/{project_id}/sprints/{sprint_id}",
        json={
            "name": "Sprint 1 - Renomeada",
            "start_date": "2026-03-02",
            "end_date": "2026-03-15",
        },
        headers={"Origin": config.app_config.frontend_url},
    )
    assert res_update.status_code == 200
    data_up = res_update.json()
    assert data_up["name"] == "Sprint 1 - Renomeada"
    assert data_up["start_civil"] == "2026-03-02"
    assert data_up["end_civil"] == "2026-03-15"

    # 5. Validação de erros
    # Start posterior a End
    res_err_date = client.post(
        f"/projects/{project_id}/sprints",
        json={
            "name": "Sprint Inválida",
            "start_date": "2026-03-20",
            "end_date": "2026-03-10",
        },
        headers={"Origin": config.app_config.frontend_url},
    )
    assert res_err_date.status_code == 400

    # Nome vazio
    res_err_name = client.post(
        f"/projects/{project_id}/sprints",
        json={
            "name": "   ",
            "start_date": "2026-03-10",
            "end_date": "2026-03-20",
        },
        headers={"Origin": config.app_config.frontend_url},
    )
    assert res_err_name.status_code == 400

    # 6. Teste de isolamento de usuário
    client_b = TestClient(main.app)
    register_and_login(client_b, uid_b)

    # Usuário B tenta listar sprints do projeto de A -> 404
    res_iso_list = client_b.get(
        f"/projects/{project_id}/sprints",
        headers={"Origin": config.app_config.frontend_url},
    )
    assert res_iso_list.status_code == 404

    # Usuário B tenta atualizar sprint de A -> 404
    res_iso_put = client_b.put(
        f"/projects/{project_id}/sprints/{sprint_id}",
        json={"name": "Hacked Sprint"},
        headers={"Origin": config.app_config.frontend_url},
    )
    assert res_iso_put.status_code == 404

    # Usuário B tenta excluir sprint de A -> 404
    res_iso_del = client_b.delete(
        f"/projects/{project_id}/sprints/{sprint_id}",
        headers={"Origin": config.app_config.frontend_url},
    )
    assert res_iso_del.status_code == 404

    # 7. DELETE /projects/{pid}/sprints/{sprint_id} por Usuário A
    res_del = client.delete(
        f"/projects/{project_id}/sprints/{sprint_id}",
        headers={"Origin": config.app_config.frontend_url},
    )
    assert res_del.status_code == 200
    assert res_del.json() == {"ok": True}

    # Verificar que foi removida da listagem
    res_list_after = client.get(
        f"/projects/{project_id}/sprints",
        headers={"Origin": config.app_config.frontend_url},
    )
    remaining_ids = [s["id"] for s in res_list_after.json()]
    assert sprint_id not in remaining_ids
    assert sprint_2_id in remaining_ids
