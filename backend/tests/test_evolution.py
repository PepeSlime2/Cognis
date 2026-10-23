import datetime as dt
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth_router import get_current_user_id
from app.database import create_neo4j_driver, get_neo4j_driver
from app.db.models import Project, Sprint, User
from app.db.session import SessionLocal, create_database
from app.main import app
from app.metrics.evolution import compute_team_evolution
from app.metrics.signals import detect_signals
from app.metrics.windows import parse_window

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from seed_demo import DEMO_PROJECT_ID, seed_demo


@pytest.fixture
def test_db():
    create_database()
    with SessionLocal() as session:
        yield session


@pytest.fixture
def seeded_env(test_db):
    driver = create_neo4j_driver()
    # Cria usuário dono do projeto demo
    user = test_db.scalar(select(User).where(User.email == "owner_evolution@cognis.local"))
    if not user:
        user = User(email="owner_evolution@cognis.local", name="Owner Evolution")
        test_db.add(user)
        test_db.commit()
        test_db.refresh(user)

    stats = seed_demo(driver, test_db, user_id=user.id, reset=True)
    project = test_db.get(Project, DEMO_PROJECT_ID)
    assert project is not None
    yield driver, test_db, user, project, stats


def test_compute_team_evolution_four_sprints(seeded_env):
    """
    CRITÉRIO DE ACEITE F9.1:
    Seed com 4 períodos mostra variação temporal coerente.
    """
    driver, db, user, project, stats = seeded_env

    res = compute_team_evolution(driver, db, project, granularity="sprint")

    assert res["id"] == "team.evolution"
    assert res["status"] == "ok"
    assert res["scope"] == "team"
    assert res["unit"] == "série"

    periods = res["values"]["periods"]
    assert len(periods) == 4, f"Esperado 4 períodos, obtido {len(periods)}"

    assert periods[0]["label"] == "Sprint 1"
    assert periods[1]["label"] == "Sprint 2"
    assert periods[2]["label"] == "Sprint 3"
    assert periods[3]["label"] == "Sprint 4"

    # Verificar que as métricas estão presentes e tipadas
    for p in periods:
        assert isinstance(p["density"], float)
        assert isinstance(p["modularity"], float)
        assert isinstance(p["centralization"], float)
        assert isinstance(p["components_count"], int)
        assert isinstance(p["active_people_count"], int)
        assert isinstance(p["reviews_per_pr"], float)
        assert isinstance(p["weight_per_person"], float)

    # Período 1 não possui delta vs período anterior
    assert periods[0]["delta"] is None

    # Períodos 2, 3 e 4 possuem deltas calculados
    for p in periods[1:]:
        assert p["delta"] is not None
        d = p["delta"]
        assert "density_drop_pct" in d
        assert "prev_weight_per_person" in d
        assert "curr_weight_per_person" in d
        assert "delta_density" in d
        assert "delta_modularity" in d

    # No último período (Sprint 4), houve queda de colaboração plantada (COLLAB_DROP)
    s4_delta = periods[3]["delta"]
    assert s4_delta is not None
    assert s4_delta["density_drop_pct"] >= 0.30, (
        f"Esperado queda >= 30%, obtido {s4_delta['density_drop_pct']}"
    )


def test_compute_team_evolution_granularity_14d(seeded_env):
    """Verifica evolução com granularidade 14d."""
    driver, db, user, project, stats = seeded_env

    res = compute_team_evolution(driver, db, project, granularity="14d")
    assert res["status"] == "ok"
    periods = res["values"]["periods"]
    assert len(periods) >= 2


def test_compute_team_evolution_insufficient_data():
    """Verifica status insufficient_data para projeto sem períodos suficientes."""
    driver = create_neo4j_driver()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "empty_evo@cognis.local"))
        if not user:
            user = User(email="empty_evo@cognis.local", name="Empty")
            db.add(user)
            db.commit()
            db.refresh(user)

        empty_proj = db.get(Project, "proj-empty-evo")
        if not empty_proj:
            empty_proj = Project(
                id="proj-empty-evo",
                user_id=user.id,
                name="Empty Project",
                timezone="UTC",
                history_days=30,
                auto_sync=False,
                sync_interval_min=60,
                settings_json={},
            )
            db.add(empty_proj)
            db.commit()
            db.refresh(empty_proj)

        res = compute_team_evolution(driver, db, empty_proj, granularity="sprint")
        assert res["status"] == "insufficient_data"
        assert "Menos de 2 períodos com dados" in res["reason"]
        assert len(res["values"]["periods"]) == 0


def test_signal_collab_drop_triggered_by_evolution():
    """Verifica que o sinal COLLAB_DROP é disparado quando density_drop_pct >= 0.30."""
    fake_metrics = {
        "team.evolution": {
            "id": "team.evolution",
            "status": "ok",
            "values": {
                "granularity": "sprint",
                "periods": [],
                "delta": {
                    "density_drop_pct": 0.42,
                    "prev_weight_per_person": 10.0,
                    "curr_weight_per_person": 5.8,
                },
            },
        }
    }
    signals = detect_signals(fake_metrics)
    collab_signals = [s for s in signals if s.code == "COLLAB_DROP"]
    assert len(collab_signals) == 1
    sig = collab_signals[0]
    assert sig.severity == "medium"
    assert sig.subject.type == "team"
    assert "42%" in sig.evidence[0].value or "0.42" in sig.evidence[0].value or "-42%" in sig.evidence[0].value


def test_signal_collab_drop_not_triggered_when_below_threshold():
    """Verifica que COLLAB_DROP NÃO é disparado se a queda for inferior a 30%."""
    fake_metrics = {
        "team.evolution": {
            "id": "team.evolution",
            "status": "ok",
            "values": {
                "granularity": "sprint",
                "periods": [],
                "delta": {
                    "density_drop_pct": 0.15,
                    "prev_weight_per_person": 10.0,
                    "curr_weight_per_person": 8.5,
                },
            },
        }
    }
    signals = detect_signals(fake_metrics)
    collab_signals = [s for s in signals if s.code == "COLLAB_DROP"]
    assert len(collab_signals) == 0


def test_api_metrics_evolution_success_and_tenant_isolation(seeded_env):
    """
    Testa o endpoint GET /projects/{pid}/metrics/evolution:
    - Retorno 200 para usuário dono com dados de evolução
    - Suporte a query params granularity=sprint e granularity=14d
    - Erro 400 para granularidade inválida
    - Isolamento estrito de tenant: Usuário B recebe 404
    """
    driver, db, user, project, stats = seeded_env
    client = TestClient(app)

    app.dependency_overrides[get_neo4j_driver] = lambda: driver
    app.dependency_overrides[get_current_user_id] = lambda: user.id

    try:
        # 1. Sucesso com granularity=sprint
        resp = client.get(f"/projects/{project.id}/metrics/evolution?granularity=sprint")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == "team.evolution"
        assert data["status"] == "ok"
        assert len(data["values"]["periods"]) == 4

        # 2. Sucesso com granularity=14d
        resp_14d = client.get(f"/projects/{project.id}/metrics/evolution?granularity=14d")
        assert resp_14d.status_code == 200
        assert resp_14d.json()["values"]["granularity"] == "14d"

        # 3. Erro 400 para granularidade inválida
        resp_bad = client.get(f"/projects/{project.id}/metrics/evolution?granularity=mensal")
        assert resp_bad.status_code == 400
        assert "invalida" in resp_bad.text.lower() or "inválida" in resp_bad.text.lower()

        # 4. Isolamento estrito de tenant (Usuário B não tem acesso ao projeto e recebe 404)
        user_b = db.scalar(select(User).where(User.email == "other_user_evo@cognis.local"))
        if not user_b:
            user_b = User(email="other_user_evo@cognis.local", name="Other User")
            db.add(user_b)
            db.commit()
            db.refresh(user_b)

        app.dependency_overrides[get_current_user_id] = lambda: user_b.id
        resp_forbidden = client.get(f"/projects/{project.id}/metrics/evolution")
        assert resp_forbidden.status_code == 404
    finally:
        app.dependency_overrides.pop(get_neo4j_driver, None)
        app.dependency_overrides.pop(get_current_user_id, None)
