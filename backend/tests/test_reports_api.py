from __future__ import annotations

import datetime as dt
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.auth_router import get_current_user_id
from app.database import get_neo4j_driver
from app.db import session as db_session
from app.db.models import Base, Project, Report, User
from app.llm.schemas import AnalysisSection, Finding, Recommendation
from app.main import app


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(
        db_session,
        "SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()


@pytest.fixture
def test_setup():
    with db_session.SessionLocal() as session:
        user_a = User(
            email="user_a@example.test",
            password_hash="hash_a",
            name="Usuário A",
        )
        session.add(user_a)
        session.flush()

        project_a = Project(
            user_id=user_a.id,
            name="Projeto do Usuário A",
            timezone="America/Sao_Paulo",
        )
        session.add(project_a)

        user_b = User(
            email="user_b@example.test",
            password_hash="hash_b",
            name="Usuário B",
        )
        session.add(user_b)
        session.commit()

        return {
            "user_a_id": user_a.id,
            "project_a_id": project_a.id,
            "user_b_id": user_b.id,
        }


@pytest.fixture
def mock_metrics_bundle():
    return {
        "project_id": "proj-a",
        "data_version": "1.0",
        "window": {
            "from": "2026-09-01",
            "to": "2026-09-30",
            "label": "Sprint 1",
            "timezone": "America/Sao_Paulo",
        },
        "metrics": {
            "flow.completion_rate": {"id": "flow.completion_rate", "values": 0.85, "unit": "0-1", "status": "ok"},
            "team.interaction_intensity": {"id": "team.interaction_intensity", "values": 40, "unit": "count", "status": "ok"},
            "graph.community": {"id": "graph.community", "values": {"Pessoa 1": 0}, "status": "ok"},
        },
        "signals": [],
    }


def test_create_and_download_report_with_tenant_isolation(
    test_setup: dict,
    mock_metrics_bundle: dict,
    tmp_path: Path,
    monkeypatch,
):
    """
    Critério central de aceite de F8.6:
    - O Usuário A gera um relatório e consegue baixá-lo nos formatos HTML, DOCX e PDF.
    - O Usuário B NÃO consegue baixar o relatório do Usuário A (retorna 404 estrito, nunca 403).
    """
    mock_driver = MagicMock()
    app.dependency_overrides[get_neo4j_driver] = lambda: mock_driver
    app.dependency_overrides[get_current_user_id] = lambda: test_setup["user_a_id"]

    mock_analysis_sec = AnalysisSection(
        resumo="Resumo automático da sprint para testes.",
        achados=[],
        recomendacoes=[],
        limitacoes=[],
    )

    try:
        with patch("app.reports_router.service.get_metrics_bundle", return_value=mock_metrics_bundle), \
             patch("app.reports_router.run_analysis_pipeline") as mock_pipeline, \
             patch("app.reports_router.load_facts_from_neo4j") as mock_facts:

            mock_pipeline.return_value = MagicMock(section=mock_analysis_sec, source="template")
            mock_facts.return_value = MagicMock(people=[])

            client_a = TestClient(app, headers={"Origin": config.app_config.frontend_url})

            # 1. Usuário A solicita geração do relatório de forma síncrona (?wait=True)
            create_resp = client_a.post(
                f"/projects/{test_setup['project_a_id']}/reports",
                json={
                    "type": "sprint",
                    "window": "30d",
                    "formats": ["html", "docx", "pdf"],
                    "include_ai": True,
                    "anonymize": False,
                    "wait": True,
                },
            )
            assert create_resp.status_code == 200
            report_data = create_resp.json()
            assert report_data["status"] == "completed"
            assert "html" in report_data["formats"]
            assert "docx" in report_data["formats"]
            assert "pdf" in report_data["formats"]
            report_id = report_data["id"]

            # 2. Usuário A consulta o relatório por ID e lista relatórios do projeto
            get_resp = client_a.get(f"/reports/{report_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["id"] == report_id

            list_resp = client_a.get(f"/projects/{test_setup['project_a_id']}/reports")
            assert list_resp.status_code == 200
            assert len(list_resp.json()) == 1

            # 3. Usuário A faz download dos 3 formatos gerados
            # Download HTML
            html_resp = client_a.get(f"/reports/{report_id}/download?format=html")
            assert html_resp.status_code == 200
            assert "text/html" in html_resp.headers["content-type"]
            assert "<!DOCTYPE html>" in html_resp.text

            # Download DOCX
            docx_resp = client_a.get(f"/reports/{report_id}/download?format=docx")
            assert docx_resp.status_code == 200
            assert docx_resp.content.startswith(b"PK\x03\x04")

            # Download PDF
            pdf_resp = client_a.get(f"/reports/{report_id}/download?format=pdf")
            assert pdf_resp.status_code == 200
            assert pdf_resp.content.startswith(b"%PDF-")

            # =========================================================================
            # 4. TESTE DE ISOLAMENTO DE TENANT: Usuário B tenta acessar os dados do Usuário A
            # =========================================================================
            app.dependency_overrides[get_current_user_id] = lambda: test_setup["user_b_id"]
            client_b = TestClient(app, headers={"Origin": config.app_config.frontend_url})

            # Usuário B tenta ler relatório do Usuário A -> 404
            b_get_resp = client_b.get(f"/reports/{report_id}")
            assert b_get_resp.status_code == 404

            # Usuário B tenta listar relatórios do projeto do Usuário A -> 404
            b_list_resp = client_b.get(f"/projects/{test_setup['project_a_id']}/reports")
            assert b_list_resp.status_code == 404

            # Usuário B tenta baixar relatório do Usuário A em qualquer formato -> 404
            b_down_html = client_b.get(f"/reports/{report_id}/download?format=html")
            assert b_down_html.status_code == 404

            b_down_docx = client_b.get(f"/reports/{report_id}/download?format=docx")
            assert b_down_docx.status_code == 404

            b_down_pdf = client_b.get(f"/reports/{report_id}/download?format=pdf")
            assert b_down_pdf.status_code == 404

    finally:
        app.dependency_overrides.pop(get_neo4j_driver, None)
        app.dependency_overrides.pop(get_current_user_id, None)


def test_individual_report_validation(test_setup: dict):
    """Verifica que o tipo 'individual' exige person_uid obrigatoriamente."""
    mock_driver = MagicMock()
    app.dependency_overrides[get_neo4j_driver] = lambda: mock_driver
    app.dependency_overrides[get_current_user_id] = lambda: test_setup["user_a_id"]

    try:
        client = TestClient(app, headers={"Origin": config.app_config.frontend_url})
        resp = client.post(
            f"/projects/{test_setup['project_a_id']}/reports",
            json={
                "type": "individual",
                # person_uid omitido de propósito
                "window": "30d",
            },
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_neo4j_driver, None)
        app.dependency_overrides.pop(get_current_user_id, None)
