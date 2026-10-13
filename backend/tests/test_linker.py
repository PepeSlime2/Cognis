from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config, linker, main
from app.db import session as db_session
from app.db.models import Base, Project, User


FIXTURE_TRELLO = (
    Path(__file__).parent / "fixtures" / "trello" / "capture.json"
)


class FakeRecord(dict):
    pass


class FakeResult:
    def __init__(self, records: list[dict[str, Any]] | None = None, count: int | None = None):
        if records is not None:
            self._records = [FakeRecord(r) for r in records]
        else:
            self._records = None
        self._count = count if count is not None else 1

    def __iter__(self):
        return iter(self._records or [])

    def single(self, strict=False):
        if self._records is not None:
            return self._records[0] if self._records else None
        return FakeRecord(count=self._count, linked=self._count, deleted=self._count, via="manual", confidence=1.0)

    def data(self):
        return [dict(r) for r in (self._records or [])]


class MockNeo4jSession:
    def __init__(self, calls: list, canned_records: list[dict[str, Any]] | None = None):
        self.calls = calls
        self.canned_records = canned_records or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def run(self, query: str, **parameters):
        self.calls.append((query, parameters))
        if "ORDER BY s.title ASC" in query:
            return FakeResult(
                [
                    {
                        "source_uid": "p1|task|trello|card-1",
                        "source_title": "Card 1",
                        "source_provider": "trello",
                        "source_url": "https://trello.com/c/ab12cd34",
                        "target_uid": "p1|pull_request|github|owner/repo#2",
                        "target_title": "PR 2",
                        "target_provider": "github",
                        "target_labels": ["PullRequest"],
                        "target_url": "https://github.com/owner/repo/pull/2",
                        "via": "attachment",
                        "confidence": 1.0,
                    }
                ]
            )
        if "WHERE NOT (t)-[:RELACIONADA_A]->()" in query:
            return FakeResult(
                [
                    {
                        "uid": "p1|task|trello|card-2",
                        "title": "Card 2",
                        "url": "https://trello.com/c/xy98zw76",
                        "short_link": "xy98zw76",
                    }
                ]
            )
        if "WHERE (c:PullRequest OR (c:Task AND c.provider = 'github'))" in query:
            return FakeResult(
                [
                    {
                        "uid": "p1|pull_request|github|owner/repo#2",
                        "title": "PR 2",
                        "labels": ["PullRequest"],
                        "url": "https://github.com/owner/repo/pull/2",
                    }
                ]
            )
        if "MATCH (s:Task {project_id: $project_id, uid: $source_uid})" in query and "DELETE r" not in query:
            if parameters.get("source_uid") == "not-found":
                return FakeResult([])
            return FakeResult([{"uid": parameters.get("source_uid")}])
        if "MATCH (t {project_id: $project_id, uid: $target_uid})" in query and "DELETE r" not in query:
            if parameters.get("target_uid") == "not-found":
                return FakeResult([])
            return FakeResult([{"uid": parameters.get("target_uid")}])
        if "DELETE r" in query:
            if parameters.get("source_uid") == "nonexistent":
                return FakeResult(count=0)
            return FakeResult(count=1)
        return FakeResult(count=1)


class MockNeo4jDriver:
    def __init__(self, canned_records: list[dict[str, Any]] | None = None):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.canned_records = canned_records or []

    def session(self, **kwargs):
        return MockNeo4jSession(self.calls, self.canned_records)


def test_parse_trello_attachments_with_fixture():
    fixture_data = json.loads(FIXTURE_TRELLO.read_text(encoding="utf-8"))
    cards = fixture_data["cards"]
    project_id = "test-proj-123"

    links = linker.parse_trello_attachments(cards, project_id)

    # Devem existir 2 links a partir dos anexos da fixture:
    # 1. card ab12cd34 -> pull request PepeSlime2/Cognis#2
    # 2. card xy98zw76 -> issue PepeSlime2/Cognis#1
    assert len(links) == 2

    jwt_link = next(l for l in links if "60c72b2f9b1d8b2e1a3f5c93" in l["source_uid"])
    assert jwt_link["target_uid"] == f"{project_id}|pull_request|github|PepeSlime2/Cognis#2"
    assert jwt_link["target_label"] == "PullRequest"
    assert jwt_link["relationship_type"] == "RELACIONADA_A"
    assert jwt_link["properties"] == {"via": "attachment", "confidence": 1.0}

    login_link = next(l for l in links if "60c72b2f9b1d8b2e1a3f5c94" in l["source_uid"])
    assert login_link["target_uid"] == f"{project_id}|task|github|PepeSlime2/Cognis#1"
    assert login_link["target_label"] == "Task"
    assert login_link["relationship_type"] == "RELACIONADA_A"
    assert login_link["properties"] == {"via": "attachment", "confidence": 1.0}


def test_parse_shortlinks_in_github():
    project_id = "proj-shortlink"
    trello_cards_by_shortlink = {
        "ab12cd34": "card-jwt-id",
        "xy98zw76": "card-login-id",
        "ci88cd99": "card-ci-id",
    }

    pulls = [
        {
            "number": 10,
            "repo": "owner/repo",
            "title": "Adicionar JWT trello.com/c/ab12cd34",
            "body": "Corpo da PR sem shortlink",
        },
        {
            "number": 11,
            "repo": "owner/repo",
            "title": "Configurar pipeline",
            "body": "Veja o card no Trello: https://trello.com/c/ci88cd99/configuracao-ci-cd",
        },
        {
            "number": 12,
            "repo": "owner/repo",
            "title": "Branch com ref",
            "body": "",
            "head": {"ref": "feature/trello.com/c/xy98zw76-login"},
        },
        {
            "number": 13,
            "repo": "owner/repo",
            "title": "PR sem Trello",
            "body": "apenas texto normal",
        },
    ]

    issues = [
        {
            "number": 5,
            "repo": "owner/repo",
            "title": "Issue ligada ao login",
            "body": "Detalhes em trello.com/c/xy98zw76",
        },
        {
            "number": 6,
            "repo": "owner/repo",
            "title": "Issue normal",
            "body": "Sem link",
        },
    ]

    links = linker.parse_shortlinks_in_github(
        pulls, issues, trello_cards_by_shortlink, project_id
    )

    assert len(links) == 4  # 3 PRs + 1 issue

    # PR 10
    pr10_link = next(l for l in links if "owner/repo#10" in l["target_uid"])
    assert pr10_link["source_uid"] == f"{project_id}|task|trello|card-jwt-id"
    assert pr10_link["target_label"] == "PullRequest"
    assert pr10_link["properties"] == {"via": "text", "confidence": 1.0}

    # PR 11
    pr11_link = next(l for l in links if "owner/repo#11" in l["target_uid"])
    assert pr11_link["source_uid"] == f"{project_id}|task|trello|card-ci-id"

    # PR 12 via branch
    pr12_link = next(l for l in links if "owner/repo#12" in l["target_uid"])
    assert pr12_link["source_uid"] == f"{project_id}|task|trello|card-login-id"

    # Issue 5
    issue5_link = next(l for l in links if "owner/repo#5" in l["target_uid"])
    assert issue5_link["source_uid"] == f"{project_id}|task|trello|card-login-id"
    assert issue5_link["target_label"] == "Task"


def test_parse_cross_repo_closes():
    project_id = "proj-closes"
    current_repo = "org/frontend"

    pulls = [
        {
            "number": 42,
            "body": "Corrige #15 e também closes org/backend#88",
        },
        {
            "number": 43,
            "body": "resolves other-owner/service-api#101",
        },
        {
            "number": 44,
            "body": "Apenas um PR qualquer",
        },
    ]

    closes = linker.parse_cross_repo_closes(pulls, current_repo, project_id)

    assert len(closes) == 3

    # Fechamento local #15
    local_close = next(l for l in closes if "org/frontend#15" in l["target_uid"])
    assert local_close["source_uid"] == f"{project_id}|pull_request|github|org/frontend#42"
    assert local_close["relationship_type"] == "FECHA"
    assert local_close["properties"] == {"via": "text"}

    # Fechamento cross-repo org/backend#88
    cross1 = next(l for l in closes if "org/backend#88" in l["target_uid"])
    assert cross1["source_uid"] == f"{project_id}|pull_request|github|org/frontend#42"
    assert cross1["relationship_type"] == "FECHA"

    # Fechamento cross-repo other-owner/service-api#101
    cross2 = next(l for l in closes if "other-owner/service-api#101" in l["target_uid"])
    assert cross2["source_uid"] == f"{project_id}|pull_request|github|org/frontend#43"
    assert cross2["relationship_type"] == "FECHA"


def test_write_links_to_graph():
    driver = MockNeo4jDriver()
    project_id = "proj-write"
    rows = [
        {
            "source_uid": f"{project_id}|task|trello|c1",
            "target_uid": f"{project_id}|pull_request|github|org/repo#1",
            "source_label": "Task",
            "target_label": "PullRequest",
            "relationship_type": "RELACIONADA_A",
            "properties": {"via": "attachment", "confidence": 1.0},
        }
    ]

    result = linker.write_links_to_graph(driver, project_id, rows)
    assert result["written"] == 1
    assert len(driver.calls) == 1
    assert "MERGE (s)-[r:`RELACIONADA_A`]->(t)" in driver.calls[0][0]


def test_link_project_in_graph():
    driver = MockNeo4jDriver()
    stats = linker.link_project_in_graph(driver, "proj-123")
    assert "text_links" in stats
    assert len(driver.calls) == 2


def test_manual_links_crud():
    driver = MockNeo4jDriver()
    project_id = "proj-manual"

    # List
    links_data = linker.list_project_links(driver, project_id)
    assert len(links_data["links"]) == 1
    assert len(links_data["unlinked_tasks"]) == 1
    assert len(links_data["candidates"]) == 1

    # Create manual link
    created = linker.create_manual_link(
        driver,
        project_id,
        source_uid=f"{project_id}|task|trello|c1",
        target_uid=f"{project_id}|pull_request|github|org/repo#2",
    )
    assert created["via"] == "manual"
    assert created["confidence"] == 1.0

    # Create manual link with nonexistent source
    with pytest.raises(ValueError, match="Tarefa de origem não encontrada"):
        linker.create_manual_link(
            driver, project_id, source_uid="not-found", target_uid="valid"
        )

    # Delete link
    deleted = linker.delete_manual_link(
        driver,
        project_id,
        source_uid=f"{project_id}|task|trello|c1",
        target_uid=f"{project_id}|pull_request|github|org/repo#2",
    )
    assert deleted is True


# API Integration Tests with TestClient
@pytest.fixture
def test_setup(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(db_session, "SessionLocal", TestingSessionLocal)

    driver = MockNeo4jDriver()
    monkeypatch.setattr(main, "create_neo4j_driver", lambda: driver)
    main.app.state.neo4j_driver = driver

    with TestingSessionLocal() as session:
        user = User(id="user-linker", email="user@example.test", password_hash="hash")
        project = Project(id="proj-linker", user_id="user-linker", name="Linker Proj")
        other_user = User(id="user-other", email="other@example.test", password_hash="hash")
        other_project = Project(id="proj-other", user_id="user-other", name="Other Proj")
        session.add_all([user, project, other_user, other_project])
        session.commit()

    return {
        "engine": engine,
        "driver": driver,
        "SessionLocal": TestingSessionLocal,
    }


def test_api_links_crud(test_setup, monkeypatch):
    client = TestClient(main.app)
    reg_res = client.post(
        "/auth/register",
        json={"email": "linker_user@example.test", "password": "password123"},
        headers={"Origin": config.app_config.frontend_url},
    )
    assert reg_res.status_code == 200
    user_id = reg_res.json()["user_id"]

    with test_setup["SessionLocal"]() as session:
        proj = session.get(Project, "proj-linker")
        assert proj is not None
        proj.user_id = user_id
        session.commit()

    # 1. GET /projects/{pid}/links
    resp = client.get("/projects/proj-linker/links")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == "proj-linker"
    assert len(data["links"]) == 1
    assert len(data["unlinked_tasks"]) == 1
    assert len(data["candidates"]) == 1

    # 2. POST /projects/{pid}/links
    create_resp = client.post(
        "/projects/proj-linker/links",
        json={
            "task_uid": "proj-linker|task|trello|card-1",
            "target_uid": "proj-linker|pull_request|github|owner/repo#2",
        },
        headers={"Origin": config.app_config.frontend_url},
    )
    assert create_resp.status_code == 201
    create_data = create_resp.json()
    assert create_data["via"] == "manual"
    assert create_data["confidence"] == 1.0

    # 3. DELETE /projects/{pid}/links (com query params)
    del_resp = client.delete(
        "/projects/proj-linker/links",
        params={
            "source_uid": "proj-linker|task|trello|card-1",
            "target_uid": "proj-linker|pull_request|github|owner/repo#2",
        },
        headers={"Origin": config.app_config.frontend_url},
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    # 4. Multi-tenant isolation: Acessar projeto de outro usuário -> 404
    forbidden_resp = client.get("/projects/proj-other/links")
    assert forbidden_resp.status_code == 404
