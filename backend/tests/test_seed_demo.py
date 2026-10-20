from __future__ import annotations

import datetime as dt
from pathlib import Path
import sys

import pytest
from sqlalchemy import select

from app.database import create_neo4j_driver
from app.db.models import Project, Sprint, User
from app.db.repository import get_project_for_user
from app.db.session import SessionLocal, create_database

# Importar seed_demo a partir do script
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from seed_demo import DEMO_PROJECT_ID, seed_demo


@pytest.fixture
def db_session():
    create_database()
    with SessionLocal() as session:
        yield session


@pytest.fixture
def neo4j_driver():
    driver = create_neo4j_driver()
    yield driver


def test_seed_demo_executes_and_creates_project(neo4j_driver, db_session):
    """Verifica que seed_demo cria o projeto Demo COGNIS, sprints no SQLite e nós no Neo4j."""
    user = db_session.scalar(select(User).where(User.email == "demo_test@cognis.local"))
    if user is None:
        user = User(email="demo_test@cognis.local", name="Demo Tester")
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

    stats = seed_demo(neo4j_driver, db_session, user_id=user.id, reset=True)

    # 1. Checagens no SQLite
    project = get_project_for_user(db_session, DEMO_PROJECT_ID, user.id)
    assert project.name == "Demo COGNIS"
    assert project.timezone == "America/Sao_Paulo"

    sprints = list(
        db_session.scalars(
            select(Sprint).where(Sprint.project_id == DEMO_PROJECT_ID).order_by(Sprint.name)
        ).all()
    )
    assert len(sprints) == 3
    assert sprints[0].name == "Sprint 1"
    assert sprints[1].name == "Sprint 2"
    assert sprints[2].name == "Sprint 3"

    # 2. Padrão plantado 1: Bruno dá ~60% dos reviews
    assert stats["total_reviews"] == 20
    assert stats["bruno_reviews"] == 12
    assert stats["bruno_review_share"] == 0.60

    # 3. Padrão plantado 5: Sprint 3 com ~30% de tarefas atrasadas
    assert stats["sprint3_total_tasks"] == 10
    assert stats["sprint3_late_count"] == 3
    assert stats["sprint3_late_rate"] == 0.30

    # 4. Validar fatos plantados diretamente no Neo4j
    with neo4j_driver.session() as session:
        # Pessoas
        res_people = session.run(
            "MATCH (p:Person {project_id: $pid}) RETURN count(p) AS count",
            pid=DEMO_PROJECT_ID,
        ).single()
        assert res_people["count"] == 6

        # Padrão 2: Módulo api/payments só alterado por Diego
        res_pay = session.run(
            """
            MATCH (a:Account {project_id: $pid})-[:REALIZOU]->(c:Commit)-[:ALTEROU]->(m:Module {project_id: $pid})
            WHERE m.path = 'api/payments'
            RETURN DISTINCT a.login AS author
            """,
            pid=DEMO_PROJECT_ID,
        )
        pay_authors = [r["author"] for r in res_pay]
        assert pay_authors == ["diego"]

        # Padrão 4: Felipe com <= 1 colaborador no grafo de PRs/Reviews
        res_felipe_revs = session.run(
            """
            MATCH (author:Account {login: 'felipe', project_id: $pid})-[:ABRIU]->(pr:PullRequest)<-[:SOBRE]-(r:Review)<-[:ENVIOU]-(reviewer:Account)
            RETURN DISTINCT reviewer.login AS reviewer
            """,
            pid=DEMO_PROJECT_ID,
        )
        felipe_reviewers = [r["reviewer"] for r in res_felipe_revs]
        assert len(felipe_reviewers) <= 1
        assert felipe_reviewers == ["bruno"]

        # Padrão 1 no Neo4j: Reviews enviados por Bruno
        res_bruno_revs = session.run(
            """
            MATCH (a:Account {login: 'bruno', project_id: $pid})-[:ENVIOU]->(r:Review)
            RETURN count(r) AS bruno_count
            """,
            pid=DEMO_PROJECT_ID,
        ).single()
        assert res_bruno_revs["bruno_count"] == 12
