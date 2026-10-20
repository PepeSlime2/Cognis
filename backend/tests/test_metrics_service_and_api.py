from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config, main
from app.db import session as db_session_module
from app.db.models import MetricSnapshot, Project, SyncRun, User
from app.graph.facts import (
    GraphFacts,
    PersonFact,
    TaskAssignmentFact,
)
from app.metrics.registry import METRICS_CATALOG, get_catalog_dict
from app.metrics.service import (
    DEFAULT_SETTINGS,
    compute_config_hash,
    get_data_version,
    get_metrics_bundle,
)
from app.metrics.windows import parse_window


def _utc(year: int, month: int, day: int, hour: int = 0) -> dt.datetime:
    return dt.datetime(year, month, day, hour, tzinfo=dt.timezone.utc)


def register_and_login(client: TestClient, email: str) -> None:
    client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "name": "Pedro Test"},
        headers={"Origin": config.app_config.frontend_url},
    )
    client.post(
        "/auth/login",
        json={"email": email, "password": "Password123!"},
        headers={"Origin": config.app_config.frontend_url},
    )


def test_catalog_registry():
    catalog = get_catalog_dict()
    assert len(catalog) >= 30
    assert len(catalog) == len(METRICS_CATALOG)

    ids = {entry["id"] for entry in catalog}
    assert "graph.degree" in ids
    assert "person.overall" in ids
    assert "team.knowledge_concentration" in ids
    assert "flow.completion_rate" in ids

    # Cada item possui as chaves contratuais do SPEC §7.2
    for item in catalog:
        for required_key in ["id", "name", "category", "scope", "unit", "description", "formula", "min_sample"]:
            assert required_key in item
            assert item[required_key] is not None


def test_config_hash_changes_when_weights_change():
    hash_default = compute_config_hash(None)
    assert isinstance(hash_default, str)
    assert len(hash_default) == 64

    # Mesmo settings -> mesmo hash
    hash_default_2 = compute_config_hash(DEFAULT_SETTINGS)
    assert hash_default == hash_default_2

    # Mudar peso de aresta -> muda hash
    settings_edge = {"edge_weights": {"review": 2.5}}
    hash_edge = compute_config_hash(settings_edge)
    assert hash_edge != hash_default

    # Mudar peso de score -> muda hash
    settings_score = {"score_weights": {"participation": 0.50}}
    hash_score = compute_config_hash(settings_score)
    assert hash_score != hash_default
    assert hash_score != hash_edge

    # Mudar threshold -> muda hash
    settings_thresh = {"thresholds": {"wip_limit": 6}}
    hash_thresh = compute_config_hash(settings_thresh)
    assert hash_thresh != hash_default


def test_data_version_from_sync_runs():
    with db_session_module.SessionLocal() as session:
        u_email = f"data_ver_{uuid.uuid4().hex[:8]}@example.test"
        user = User(email=u_email, password_hash="hash")
        session.add(user)
        session.commit()

        proj = Project(user_id=user.id, name="Data Ver Proj")
        session.add(proj)
        session.commit()

        # Sem sync run -> v0
        assert get_data_version(session, proj.id) == "v0"

        # Sync run em andamento ou falho não conta como data_version
        run_running = SyncRun(project_id=proj.id, status="running")
        session.add(run_running)
        session.commit()
        assert get_data_version(session, proj.id) == "v0"

        # Sync run com sucesso -> usa id da run
        run_success = SyncRun(
            project_id=proj.id,
            status="success",
            finished_at=_utc(2026, 3, 10, 12),
        )
        session.add(run_success)
        session.commit()
        assert get_data_version(session, proj.id) == str(run_success.id)


def test_metrics_service_pipeline_and_cache():
    with db_session_module.SessionLocal() as session:
        u_email = f"pipeline_{uuid.uuid4().hex[:8]}@example.test"
        user = User(email=u_email, password_hash="hash")
        session.add(user)
        session.commit()

        proj = Project(user_id=user.id, name="Pipeline Proj", timezone="UTC")
        session.add(proj)
        session.commit()

        win = parse_window("2026-03-01", "2026-03-15", timezone="UTC")

        # Fatos fabricados para testar
        facts = GraphFacts(
            project_id=proj.id,
            window=win,
            people=[
                PersonFact("u1", "User 1"),
                PersonFact("u2", "User 2"),
                PersonFact("u3", "User 3"),
            ],
            task_assignments=[
                TaskAssignmentFact("t1", ["u1"], "done", due_at=_utc(2026, 3, 5), done_at=_utc(2026, 3, 4)),
                TaskAssignmentFact("t2", ["u2"], "doing", due_at=_utc(2026, 3, 6)),
            ],
        )

        # 1ª chamada: calcula e grava no snapshot (cached == False)
        bundle_1 = get_metrics_bundle(
            db=session,
            neo4j_driver=None,
            project=proj,
            window=win,
            raw_facts=facts,
        )
        assert bundle_1["project_id"] == proj.id
        assert bundle_1["cached"] is False
        assert "metrics" in bundle_1
        assert "graph.degree" in bundle_1["metrics"]
        assert "flow.completion_rate" in bundle_1["metrics"]

        # Verifica que o snapshot foi salvo no banco
        snaps = session.execute(
            select(MetricSnapshot).where(MetricSnapshot.project_id == proj.id)
        ).scalars().all()
        assert len(snaps) == 1
        assert snaps[0].config_hash == bundle_1["config_hash"]

        # 2ª chamada: deve vir do cache (cached == True)
        bundle_2 = get_metrics_bundle(
            db=session,
            neo4j_driver=None,
            project=proj,
            window=win,
            raw_facts=facts,
        )
        assert bundle_2["cached"] is True
        assert bundle_2["config_hash"] == bundle_1["config_hash"]
        assert len(bundle_2["metrics"]) == len(bundle_1["metrics"])

        # Se mudar o peso no projeto, o config_hash muda e NÃO vem do cache anterior
        proj.settings_json = {"edge_weights": {"review": 3.0}}
        session.commit()

        bundle_3 = get_metrics_bundle(
            db=session,
            neo4j_driver=None,
            project=proj,
            window=win,
            raw_facts=facts,
        )
        assert bundle_3["cached"] is False
        assert bundle_3["config_hash"] != bundle_1["config_hash"]


def test_api_catalog_endpoint():
    with TestClient(main.app, follow_redirects=False) as client:
        resp = client.get("/metrics/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 30
        assert any(m["id"] == "flow.lead_time" for m in data)


def test_api_project_settings_and_metrics_endpoints():
    u_email = f"api_user_{uuid.uuid4().hex[:8]}@example.test"
    with TestClient(main.app, follow_redirects=False) as client:
        register_and_login(client, u_email)

        # Criar projeto
        create_proj_resp = client.post(
            "/projects",
            json={"name": "API Metrics Proj", "timezone": "America/Sao_Paulo"},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert create_proj_resp.status_code == 201
        proj_id = create_proj_resp.json()["id"]

        # GET /projects/{pid}/settings
        settings_resp = client.get(f"/projects/{proj_id}/settings")
        assert settings_resp.status_code == 200
        settings_data = settings_resp.json()
        assert "auto_sync" in settings_data

        # PUT /projects/{pid}/settings com novos pesos em settings_json
        put_resp = client.put(
            f"/projects/{proj_id}/settings",
            json={
                "auto_sync": False,
                "sync_interval_min": 60,
                "settings_json": {
                    "edge_weights": {"review": 2.0, "comment": 0.8},
                    "score_weights": {"participation": 0.35},
                },
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["settings_json"]["edge_weights"]["review"] == 2.0

        # GET /projects/{pid}/metrics
        metrics_resp = client.get(
            f"/projects/{proj_id}/metrics",
            params={"from": "2026-03-01", "to": "2026-03-15"},
        )
        assert metrics_resp.status_code == 200
        metrics_data = metrics_resp.json()
        assert metrics_data["project_id"] == proj_id
        assert metrics_data["cached"] is False
        assert "metrics" in metrics_data

        # 2ª chamada vem do cache (cached == True)
        metrics_resp_2 = client.get(
            f"/projects/{proj_id}/metrics",
            params={"from": "2026-03-01", "to": "2026-03-15"},
        )
        assert metrics_resp_2.status_code == 200
        assert metrics_resp_2.json()["cached"] is True
