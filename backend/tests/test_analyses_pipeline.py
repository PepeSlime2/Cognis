from __future__ import annotations

import datetime as dt
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.database import get_neo4j_driver
from app.db import session as db_session
from app.db.models import Analysis, Base, Project, User
from app.llm.pipeline import run_analysis_pipeline
from app.main import app
from app.metrics.windows import TimeWindow


# ==============================================================================
# Fixtures e Setup
# ==============================================================================

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
        user = User(
            email="ana@example.test",
            password_hash="hash123",
            name="Ana",
        )
        session.add(user)
        session.flush()

        project = Project(
            user_id=user.id,
            name="Projeto Alpha",
            timezone="America/Sao_Paulo",
        )
        session.add(project)
        session.commit()
        user_id = user.id
        project_id = project.id

    from app.metrics.windows import parse_window
    window = parse_window("2026-09-01", "2026-09-14", timezone="America/Sao_Paulo")
    return {"user_id": user_id, "project_id": project_id, "window": window}


@pytest.fixture
def mock_bundle():
    return {
        "project_id": "test-pid",
        "window": {"from": "2026-09-01", "to": "2026-09-14", "label": "Sprint 3"},
        "metrics": {
            "graph.components": {"value": {"total_nodes": 4}},
            "graph.density": {"value": 0.5},
            "flow.completion_rate": {"value": 0.80},
        },
        "signals": [
            {
                "id": "S1",
                "code": "BUS_FACTOR_1",
                "severity": "high",
                "subject": "Diego",
                "title": "Fator de ônibus crítico",
                "evidence": [{"metric_id": "team.knowledge_concentration", "value": "1.0"}],
            }
        ],
    }


# ==============================================================================
# 1. Critério de Aceite: Ollama Desligado -> Fallback Template (source='template')
# ==============================================================================

def test_pipeline_fallback_to_template_when_ollama_unavailable(test_setup, mock_bundle):
    with db_session.SessionLocal() as db:
        project = db.get(Project, test_setup["project_id"])
        mock_driver = MagicMock()

        with patch("app.llm.pipeline.check_ollama_health") as mock_health, \
             patch("app.llm.pipeline.get_metrics_bundle", return_value=mock_bundle):
            # Simula Ollama desligado
            mock_health.return_value = {
                "status": "unavailable",
                "available": False,
                "error": "Connection refused",
            }

            analysis = run_analysis_pipeline(
                db=db,
                neo4j_driver=mock_driver,
                project=project,
                window=test_setup["window"],
                scope="team",
            )

            assert analysis.status == "completed"
            assert analysis.source == "template"
            assert analysis.model == "template"
            assert analysis.result_json is not None
            assert "resumo" in analysis.result_json
            assert len(analysis.result_json["achados"]) >= 1
            assert analysis.result_json["achados"][0]["evidencias"][0]["ref"] == "S1"
            assert analysis.validation_json["passed"] is False  # Não rodou pelo LLM
            assert analysis.validation_json["source"] == "template"


# ==============================================================================
# 2. Sucesso com LLM (source='llm')
# ==============================================================================

def test_pipeline_success_with_llm(test_setup, mock_bundle):
    llm_output = {
        "resumo": "Análise da Sprint 3 com 4 membros ativos e conclusão de 80%.",
        "achados": [
            {
                "titulo": "Risco de concentração técnica",
                "descricao": "Diego concentra o módulo de acordo com o sinal identificado.",
                "severidade": "alta",
                "evidencias": [{"ref": "S1"}],
            }
        ],
        "recomendacoes": [
            {
                "acao": "Realizar pareamento.",
                "justificativa": "Mitiga a concentração em S1.",
                "evidencias": [{"ref": "S1"}],
            }
        ],
        "limitacoes": ["Dados da Sprint 3."],
    }

    with db_session.SessionLocal() as db:
        project = db.get(Project, test_setup["project_id"])
        mock_driver = MagicMock()

        with patch("app.llm.pipeline.check_ollama_health") as mock_health, \
             patch("app.llm.pipeline.get_metrics_bundle", return_value=mock_bundle), \
             patch("app.llm.pipeline.chat", return_value=json.dumps(llm_output)):
            mock_health.return_value = {
                "status": "ok",
                "available": True,
                "model": "llama3.1:8b",
            }

            analysis = run_analysis_pipeline(
                db=db,
                neo4j_driver=mock_driver,
                project=project,
                window=test_setup["window"],
                scope="team",
            )

            assert analysis.status == "completed"
            assert analysis.source == "llm"
            assert analysis.model == "llama3.1:8b"
            assert analysis.validation_json["passed"] is True
            assert analysis.validation_json["retries"] == 0


# ==============================================================================
# 3. Retry com Validação e Recuperação
# ==============================================================================

def test_pipeline_retry_with_validation_recovery(test_setup, mock_bundle):
    # 1ª resposta com violação de ref (S99)
    bad_llm_output = json.dumps({
        "resumo": "Resumo inicial.",
        "achados": [
            {
                "titulo": "Achado com erro",
                "descricao": "Desc.",
                "severidade": "alta",
                "evidencias": [{"ref": "S99"}],
            }
        ],
        "recomendacoes": [],
        "limitacoes": [],
    })

    # 2ª resposta corrigida
    good_llm_output = json.dumps({
        "resumo": "Resumo corrigido com 4 membros.",
        "achados": [
            {
                "titulo": "Achado corrigido",
                "descricao": "Desc.",
                "severidade": "alta",
                "evidencias": [{"ref": "S1"}],
            }
        ],
        "recomendacoes": [
            {"acao": "Ação.", "justificativa": "Just.", "evidencias": [{"ref": "S1"}]}
        ],
        "limitacoes": [],
    })

    with db_session.SessionLocal() as db:
        project = db.get(Project, test_setup["project_id"])
        mock_driver = MagicMock()

        with patch("app.llm.pipeline.check_ollama_health") as mock_health, \
             patch("app.llm.pipeline.get_metrics_bundle", return_value=mock_bundle), \
             patch("app.llm.pipeline.chat", side_effect=[bad_llm_output, good_llm_output]) as mock_chat:
            mock_health.return_value = {"status": "ok", "available": True, "model": "llama3.1:8b"}

            analysis = run_analysis_pipeline(
                db=db,
                neo4j_driver=mock_driver,
                project=project,
                window=test_setup["window"],
                scope="team",
            )

            assert mock_chat.call_count == 2
            assert analysis.status == "completed"
            assert analysis.source == "llm"
            assert analysis.validation_json["retries"] == 1
            assert analysis.validation_json["passed"] is True


# ==============================================================================
# 4. Endpoints REST da API
# ==============================================================================

def test_api_create_analysis_endpoint(test_setup, mock_bundle):
    from app.auth_router import get_current_user_id

    mock_driver = MagicMock()
    app.dependency_overrides[get_neo4j_driver] = lambda: mock_driver
    app.dependency_overrides[get_current_user_id] = lambda: test_setup["user_id"]

    try:
        with patch("app.llm.pipeline.check_ollama_health", return_value={"available": False}), \
             patch("app.llm.pipeline.get_metrics_bundle", return_value=mock_bundle):
            client = TestClient(app, headers={"Origin": config.app_config.frontend_url})

            # Chamada síncrona com wait=True
            resp = client.post(
                f"/projects/{test_setup['project_id']}/analyses",
                json={
                    "scope": "team",
                    "window": "14d",
                    "force_template": True,
                    "wait": True,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "completed"
            assert data["source"] == "template"
            analysis_id = data["id"]

            # Consulta por ID
            get_resp = client.get(f"/analyses/{analysis_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["id"] == analysis_id

            # Listagem de análises do projeto
            list_resp = client.get(f"/projects/{test_setup['project_id']}/analyses")
            assert list_resp.status_code == 200
            assert len(list_resp.json()) >= 1
            assert list_resp.json()[0]["id"] == analysis_id
    finally:
        app.dependency_overrides.pop(get_neo4j_driver, None)
        app.dependency_overrides.pop(get_current_user_id, None)


def test_api_tenant_isolation(test_setup):
    from app.auth_router import get_current_user_id

    mock_driver = MagicMock()
    app.dependency_overrides[get_neo4j_driver] = lambda: mock_driver

    with db_session.SessionLocal() as session:
        other_user = User(email="other@example.test", password_hash="hash", name="Other")
        session.add(other_user)
        session.commit()
        other_id = other_user.id

        an = Analysis(
            project_id=test_setup["project_id"],
            scope="team",
            window_from=dt.datetime.now(dt.timezone.utc),
            window_to=dt.datetime.now(dt.timezone.utc),
            status="completed",
            facts_json={},
        )
        session.add(an)
        session.commit()
        an_id = an.id

    app.dependency_overrides[get_current_user_id] = lambda: other_id
    try:
        # Usuário invasor tentando acessar análise do projeto alheio
        client = TestClient(app, headers={"Origin": config.app_config.frontend_url})
        resp = client.get(f"/analyses/{an_id}")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_neo4j_driver, None)
        app.dependency_overrides.pop(get_current_user_id, None)
