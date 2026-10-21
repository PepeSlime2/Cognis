"""
Testes unitários e de integração para o motor de Signals e templates PT-BR (SPEC §8, §15.2, F6.1).
Critério de aceite central: o seed dispara exatamente os signals plantados (e nenhum espúrio).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import sys
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config, main
from app.database import create_neo4j_driver
from app.db import session as db_session_module
from app.db.models import Project, Sprint, User
from app.db.session import SessionLocal, create_database
from app.graph.facts import (
    CommentFact,
    CommitFact,
    GraphFacts,
    ModuleCommitFact,
    PersonFact,
    PRFact,
    ReviewFact,
    TaskAssignmentFact,
    TaskDependencyFact,
)
from app.llm.templates import (
    SIGNAL_TEMPLATES,
    render_signal_message,
    render_signal_title,
)
from app.metrics.service import get_metrics_bundle
from app.metrics.signals import Signal, detect_signals
from app.metrics.windows import parse_window

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from seed_demo import DEMO_PROJECT_ID, seed_demo


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


# =========================================================================
# 1. Testes de Templates PT-BR
# =========================================================================

def test_signal_templates_catalog_complete():
    """Valida que todos os 15 códigos de signals de SPEC §8 possuem templates PT-BR."""
    expected_codes = {
        "BUS_FACTOR_1",
        "REVIEW_CONCENTRATION",
        "PR_WAIT_HIGH",
        "NO_REVIEW_MERGES",
        "ISOLATED_MEMBER",
        "SILOS",
        "TASK_CONCENTRATION",
        "LATE_RATE_HIGH",
        "LOW_COMPLETION",
        "WIP_HIGH",
        "BLOCKED_AGING",
        "STALE_TASKS",
        "REWORK_HIGH",
        "COLLAB_DROP",
        "INSUFFICIENT_DATA",
    }
    assert expected_codes.issubset(set(SIGNAL_TEMPLATES.keys()))

    for code in expected_codes:
        title = render_signal_title(code)
        assert title and len(title) > 5
        # Renderização resiliente
        msg = render_signal_message(code, {})
        assert msg and len(msg) > 10


def test_signal_templates_rendering():
    """Valida renderização de variáveis nos textos dos signals."""
    ctx_bus = {"module": "api/payments", "author": "Diego Souza", "top1_share": 1.0}
    msg_bus = render_signal_message("BUS_FACTOR_1", ctx_bus)
    assert "api/payments" in msg_bus
    assert "Diego Souza" in msg_bus
    assert "100%" in msg_bus

    ctx_rev = {"person": "Bruno Costa", "pct": 0.60, "n": 12, "total": 20}
    msg_rev = render_signal_message("REVIEW_CONCENTRATION", ctx_rev)
    assert "Bruno Costa" in msg_rev
    assert "60%" in msg_rev
    assert "12 de 20" in msg_rev


# =========================================================================
# 2. Testes Unitários de Detecção de Signals
# =========================================================================

def test_detect_signals_bus_factor():
    """Valida BUS_FACTOR_1 com severidade high (>=20% das alterações) e medium (<20%)."""
    # Módulo payments com 80 alterações de 100 totais -> 80% (high)
    metrics_high = {
        "team.knowledge_concentration": {
            "status": "ok",
            "values": {
                "modules": {
                    "api/payments": {
                        "bus_factor": 1,
                        "is_eligible": True,
                        "top1_share": 1.0,
                        "total_changes": 80,
                    },
                    "web/pages": {
                        "bus_factor": 2,
                        "is_eligible": True,
                        "top1_share": 0.5,
                        "total_changes": 20,
                    },
                }
            },
        }
    }
    sigs_high = detect_signals(metrics=metrics_high)
    assert len(sigs_high) == 1
    assert sigs_high[0].code == "BUS_FACTOR_1"
    assert sigs_high[0].severity == "high"
    assert sigs_high[0].subject.id == "api/payments"

    # Módulo utils com 10 alterações de 100 totais -> 10% (medium)
    metrics_med = {
        "team.knowledge_concentration": {
            "status": "ok",
            "values": {
                "modules": {
                    "core/utils": {
                        "bus_factor": 1,
                        "is_eligible": True,
                        "top1_share": 1.0,
                        "total_changes": 10,
                    },
                    "core/main": {
                        "bus_factor": 2,
                        "is_eligible": True,
                        "top1_share": 0.5,
                        "total_changes": 90,
                    },
                }
            },
        }
    }
    sigs_med = detect_signals(metrics=metrics_med)
    assert len(sigs_med) == 1
    assert sigs_med[0].code == "BUS_FACTOR_1"
    assert sigs_med[0].severity == "medium"


def test_detect_signals_pr_wait_high():
    """Valida PR_WAIT_HIGH com limiares padrão (48h medium, 96h high)."""
    # 60h -> medium
    sigs_60 = detect_signals(
        metrics={"flow.pr_time_to_first_review": {"status": "ok", "values": {"p85_h": 60.0}}}
    )
    assert len(sigs_60) == 1
    assert sigs_60[0].code == "PR_WAIT_HIGH"
    assert sigs_60[0].severity == "medium"

    # 120h -> high
    sigs_120 = detect_signals(
        metrics={"flow.pr_time_to_first_review": {"status": "ok", "values": {"p85_h": 120.0}}}
    )
    assert len(sigs_120) == 1
    assert sigs_120[0].code == "PR_WAIT_HIGH"
    assert sigs_120[0].severity == "high"

    # 24h -> não dispara
    sigs_24 = detect_signals(
        metrics={"flow.pr_time_to_first_review": {"status": "ok", "values": {"p85_h": 24.0}}}
    )
    assert len(sigs_24) == 0


def test_detect_signals_no_review_merges():
    """Valida NO_REVIEW_MERGES com limiares padrão (0.80 medium, 0.50 high)."""
    # 0.70 -> medium
    sigs_med = detect_signals(
        metrics={"team.review_coverage": {"status": "ok", "values": {"review_coverage": 0.70}}}
    )
    assert len(sigs_med) == 1
    assert sigs_med[0].code == "NO_REVIEW_MERGES"
    assert sigs_med[0].severity == "medium"

    # 0.40 -> high
    sigs_high = detect_signals(
        metrics={"team.review_coverage": {"status": "ok", "values": {"review_coverage": 0.40}}}
    )
    assert len(sigs_high) == 1
    assert sigs_high[0].code == "NO_REVIEW_MERGES"
    assert sigs_high[0].severity == "high"

    # 0.90 -> não dispara
    sigs_ok = detect_signals(
        metrics={"team.review_coverage": {"status": "ok", "values": {"review_coverage": 0.90}}}
    )
    assert len(sigs_ok) == 0


def test_detect_signals_wip_high():
    """Valida WIP_HIGH quando uma pessoa ultrapassa o wip_limit."""
    metrics = {
        "flow.wip_per_person": {
            "status": "ok",
            "values": {
                "p_alice": 3,
                "p_bob": 6,  # > 4
            },
        }
    }
    sigs = detect_signals(metrics=metrics, settings={"wip_limit": 4})
    assert len(sigs) == 1
    assert sigs[0].code == "WIP_HIGH"
    assert sigs[0].subject.id == "p_bob"
    assert sigs[0].severity == "medium"


def test_detect_signals_blocked_and_stale_tasks():
    """Valida BLOCKED_AGING e STALE_TASKS."""
    t0 = dt.datetime(2026, 3, 20, 12, 0, 0, tzinfo=dt.timezone.utc)
    t_10d_ago = t0 - dt.timedelta(days=10)
    t_20d_ago = t0 - dt.timedelta(days=20)

    facts = GraphFacts(
        project_id="test-proj",
        task_assignments=[
            # 2 tarefas bloqueadas há 10 dias (> 7 dias) -> dispara BLOCKED_AGING
            TaskAssignmentFact(
                task_uid="t_b1",
                person_uids=["u1"],
                status_category="doing",
                blocked=True,
                blocked_since=t_10d_ago,
            ),
            TaskAssignmentFact(
                task_uid="t_b2",
                person_uids=["u2"],
                status_category="todo",
                blocked=True,
                blocked_since=t_10d_ago,
            ),
            # 3 tarefas em doing sem atividade há 20 dias (> 14 dias) -> dispara STALE_TASKS
            TaskAssignmentFact(
                task_uid="t_s1",
                person_uids=["u1"],
                status_category="doing",
                updated_at=t_20d_ago,
            ),
            TaskAssignmentFact(
                task_uid="t_s2",
                person_uids=["u2"],
                status_category="doing",
                updated_at=t_20d_ago,
            ),
            TaskAssignmentFact(
                task_uid="t_s3",
                person_uids=["u3"],
                status_category="doing",
                updated_at=t_20d_ago,
            ),
        ],
    )
    sigs = detect_signals(metrics={}, facts=facts, now=t0)
    codes = {s.code for s in sigs}
    assert "BLOCKED_AGING" in codes
    assert "STALE_TASKS" in codes


# =========================================================================
# 3. Critério de Aceite Central: Seed Demo (SPEC §15.2 e F6.1)
# =========================================================================

def test_seed_demo_planted_signals_acceptance():
    """
    CRITÉRIO DE ACEITE CENTRAL (F6.1):
    O seed dispara exatamente os signals plantados e NENHUM espúrio.
    
    Na janela completa do projeto demo:
      - BUS_FACTOR_1 (api/payments, Diego)
      - REVIEW_CONCENTRATION (Bruno Costa, ~60% dos reviews)
      - SILOS (backend x frontend)
      - ISOLATED_MEMBER (Felipe Lima)
    
    Na Sprint 3:
      - LATE_RATE_HIGH (3 de 10 tarefas atrasadas = 30%)
    """
    driver = create_neo4j_driver()
    with SessionLocal() as session:
        seed_stats = seed_demo(driver, session, reset=True)
        project = session.get(Project, DEMO_PROJECT_ID)
        assert project is not None

        # -------------------------------------------------------------
        # 1. Testar Janela Completa do Projeto Demo (2026-01-05 a 2026-02-15)
        # -------------------------------------------------------------
        win_full = parse_window("2026-01-05", "2026-02-15", timezone=project.timezone)
        bundle_full = get_metrics_bundle(
            db=session,
            neo4j_driver=driver,
            project=project,
            window=win_full,
            force_refresh=True,
        )

        signals_full = bundle_full.get("signals", [])
        sig_codes_full = [s["code"] for s in signals_full]

        # Validar que exatamente os 4 padrões plantados da janela geral foram disparados
        assert set(sig_codes_full) == {
            "BUS_FACTOR_1",
            "REVIEW_CONCENTRATION",
            "SILOS",
            "ISOLATED_MEMBER",
        }, f"Esperava exatamente os 4 plantados, mas obteve: {sig_codes_full}"

        # Validar detalhes dos 4 signals gerais:
        sig_map = {s["code"]: s for s in signals_full}

        # 1.1 BUS_FACTOR_1
        bf_sig = sig_map["BUS_FACTOR_1"]
        assert bf_sig["subject"]["id"] == "api/payments"
        assert bf_sig["severity"] == "high"  # api/payments > 20% das alterações
        assert "api/payments" in bf_sig["message"]

        # 1.2 REVIEW_CONCENTRATION
        rev_sig = sig_map["REVIEW_CONCENTRATION"]
        assert "Bruno" in rev_sig["subject"]["label"]
        assert rev_sig["severity"] == "medium"  # 60% (>= 50% e < 70%)
        assert "60%" in rev_sig["message"]

        # 1.3 SILOS
        silos_sig = sig_map["SILOS"]
        assert silos_sig["subject"]["type"] == "team"
        assert silos_sig["severity"] == "medium"

        # 1.4 ISOLATED_MEMBER
        iso_sig = sig_map["ISOLATED_MEMBER"]
        assert "Felipe" in iso_sig["subject"]["label"]
        assert iso_sig["severity"] == "medium"

        # -------------------------------------------------------------
        # 2. Testar Sprint 3 (2026-02-02 a 2026-02-15)
        # -------------------------------------------------------------
        win_s3 = parse_window("2026-02-02", "2026-02-15", timezone=project.timezone)
        bundle_s3 = get_metrics_bundle(
            db=session,
            neo4j_driver=driver,
            project=project,
            window=win_s3,
            force_refresh=True,
        )

        signals_s3 = bundle_s3.get("signals", [])
        sig_codes_s3 = [s["code"] for s in signals_s3]

        # Na Sprint 3, o padrão plantado de tarefas atrasadas dispara LATE_RATE_HIGH
        assert "LATE_RATE_HIGH" in sig_codes_s3
        late_sig = next(s for s in signals_s3 if s["code"] == "LATE_RATE_HIGH")
        assert late_sig["severity"] == "medium"  # 30% (>= 25% e < 40%)
        assert "30%" in late_sig["message"]
        assert "3 de 10" in late_sig["message"]


# =========================================================================
# 4. Testes de API: GET /projects/{pid}/signals
# =========================================================================

def test_api_get_project_signals_flow_and_isolation():
    """Valida autorização, isolamento (SPEC §13) e retorno da lista de signals via API."""
    with TestClient(main.app, follow_redirects=False) as client:
        # 1. Usuário A autentica
        user_a_email = f"signals_a_{uuid.uuid4().hex[:6]}@example.test"
        register_and_login(client, user_a_email)

        with SessionLocal() as session:
            user_a = session.scalar(select(User).where(User.email == user_a_email))
            driver = create_neo4j_driver()
            seed_demo(driver, session, user_id=user_a.id, reset=True)
            demo_proj = session.get(Project, DEMO_PROJECT_ID)
            demo_proj.user_id = user_a.id
            session.commit()

        # 2. Chamada autenticada pelo dono -> 200 e lista de signals
        resp = client.get(
            f"/projects/{DEMO_PROJECT_ID}/signals",
            params={"from": "2026-01-05", "to": "2026-02-15"},
        )
        assert resp.status_code == 200
        signals_data = resp.json()
        assert isinstance(signals_data, list)
        assert len(signals_data) == 4
        codes = {s["code"] for s in signals_data}
        assert codes == {"BUS_FACTOR_1", "REVIEW_CONCENTRATION", "SILOS", "ISOLATED_MEMBER"}

        # Cada item possui o formato de SPEC §8
        for sig in signals_data:
            assert "id" in sig
            assert "code" in sig
            assert "severity" in sig
            assert "title" in sig
            assert "message" in sig
            assert "subject" in sig
            assert "evidence" in sig
            assert "window" in sig

        # 3. Consulta de signals da Sprint 3 por sprint_id
        resp_s3 = client.get(
            f"/projects/{DEMO_PROJECT_ID}/signals",
            params={"sprint_id": "demo-sprint-3"},
        )
        assert resp_s3.status_code == 200
        s3_data = resp_s3.json()
        s3_codes = {s["code"] for s in s3_data}
        assert "LATE_RATE_HIGH" in s3_codes

        # 4. ISOLAMENTO: Usuário B tenta acessar signals do projeto de A -> 404
        user_b_email = f"signals_b_{uuid.uuid4().hex[:6]}@example.test"
        register_and_login(client, user_b_email)

        resp_b = client.get(
            f"/projects/{DEMO_PROJECT_ID}/signals",
            params={"from": "2026-01-05", "to": "2026-02-15"},
        )
        assert resp_b.status_code == 404
