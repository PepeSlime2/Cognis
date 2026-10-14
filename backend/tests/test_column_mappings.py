from __future__ import annotations

import uuid
from fastapi.testclient import TestClient

from app import config, main
from app.db import repository
from app.db import session as db_session
from app.db.models import ColumnMapping, Project, User


def register_user(client: TestClient, email: str) -> None:
    client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "name": "Pedro Test"},
        headers={"Origin": config.app_config.frontend_url},
    )


def test_list_and_update_column_mappings():
    user_email = f"col_user_{uuid.uuid4().hex[:8]}@example.test"
    with TestClient(main.app, follow_redirects=False) as client:
        register_user(client, user_email)
        create_res = client.post(
            "/projects",
            json={
                "name": "Projeto Colunas",
                "timezone": "America/Sao_Paulo",
                "history_days": 90,
                "auto_sync": False,
                "sync_interval_min": 60,
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert create_res.status_code == 201
        project_id = create_res.json()["id"]

        # Insert some initial column mappings (auto generated)
        with db_session.SessionLocal() as session:
            c1 = ColumnMapping(
                project_id=project_id,
                column_uid="col_1",
                name="Backlog Geral",
                category="backlog",
                source="auto",
            )
            c2 = ColumnMapping(
                project_id=project_id,
                column_uid="col_2",
                name="Em Teste",
                category="todo",
                source="auto",
            )
            session.add_all([c1, c2])
            session.commit()

        # 1. GET /projects/{id}/columns
        get_res = client.get(f"/projects/{project_id}/columns")
        assert get_res.status_code == 200
        data = get_res.json()
        assert len(data["columns"]) == 2
        assert "columns_unconfirmed" in data["warnings"]
        col_names = {c["column_uid"]: c["name"] for c in data["columns"]}
        assert col_names["col_1"] == "Backlog Geral"
        assert col_names["col_2"] == "Em Teste"

        # 2. PUT /projects/{id}/columns (Update and confirm mapping)
        put_res = client.put(
            f"/projects/{project_id}/columns",
            json={
                "columns": [
                    {"column_uid": "col_1", "category": "backlog"},
                    {"column_uid": "col_2", "category": "review"},
                ]
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert put_res.status_code == 200
        put_data = put_res.json()
        # All columns are now user-confirmed, warnings should be empty
        assert "columns_unconfirmed" not in put_data["warnings"]
        cat_map = {c["column_uid"]: (c["category"], c["source"]) for c in put_data["columns"]}
        assert cat_map["col_2"] == ("review", "user")
        assert cat_map["col_1"] == ("backlog", "user")

        # 3. Invalid category should return 422
        invalid_res = client.put(
            f"/projects/{project_id}/columns",
            json={"columns": [{"column_uid": "col_1", "category": "invalid_cat"}]},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert invalid_res.status_code == 422

        # 4. Non-existing column should return 404
        not_found_res = client.put(
            f"/projects/{project_id}/columns",
            json={"columns": [{"column_uid": "non_existent", "category": "done"}]},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert not_found_res.status_code == 404

    # 5. Isolation: User B cannot access or update User A's columns
    user_b_email = f"col_user_{uuid.uuid4().hex[:8]}@example.test"
    with TestClient(main.app, follow_redirects=False) as client_b:
        register_user(client_b, user_b_email)
        iso_get = client_b.get(f"/projects/{project_id}/columns")
        assert iso_get.status_code == 404

        iso_put = client_b.put(
            f"/projects/{project_id}/columns",
            json={"columns": [{"column_uid": "col_1", "category": "done"}]},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert iso_put.status_code == 404
