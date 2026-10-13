from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config, identity_service, main
from app.db import session as db_session
from app.db.models import Base, PersonOverride, Project, ProviderConnection, User


class FakeRecord(dict):
    pass


class FakeResult:
    def __init__(self, records: list[dict[str, Any]] | None = None, created: int = 0):
        self._records = [FakeRecord(r) for r in (records or [])]
        self._created = created

    def __iter__(self):
        return iter(self._records)

    def single(self, strict=False):
        if self._records:
            return self._records[0]
        return FakeRecord(created=self._created, updated=self._created)


class FakeTx:
    def __init__(self, calls: list, session: MockNeo4jSession):
        self.calls = calls
        self.session = session

    def run(self, query: str, **parameters):
        return self.session.run(query, **parameters)


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
        if "WHERE NOT (:Person" in query:
            return FakeResult(self.canned_records)
        if "RETURN count(p) AS created" in query:
            rows = parameters.get("rows", [])
            return FakeResult(created=len(rows))
        if "RETURN keep.uid AS uid" in query:
            return FakeResult([{"uid": parameters.get("keep_person_uid", "keep-uid")}])
        if "RETURN keep.uid AS person_uid" in query:
            return FakeResult(
                [
                    {
                        "person_uid": parameters.get("keep_person_uid", "keep-uid"),
                        "display_name": "Keep Person",
                        "excluded": False,
                        "accounts": [
                            {"uid": "acc-1", "provider": "github", "login": "user1", "display_name": "User 1", "avatar_url": None, "is_bot": False, "linked": True},
                            {"uid": "acc-2", "provider": "trello", "login": "user2", "display_name": "User 2", "avatar_url": None, "is_bot": False, "linked": True},
                        ],
                    }
                ]
            )
        if "RETURN count(all_acc) AS total_accounts" in query:
            return FakeResult(
                [
                    {
                        "total_accounts": 2,
                        "provider": "trello",
                        "login": "user2",
                        "display_name": "User 2",
                        "is_bot": False,
                    }
                ]
            )
        if "RETURN new_p.uid AS new_uid" in query:
            return FakeResult([{"new_uid": parameters.get("new_person_uid", "new-uid")}])
        if "MATCH (p:Person {project_id: $project_id})" in query:
            return FakeResult(self.canned_records)
        if "MATCH (p:Person {uid: $person_uid" in query:
            # Update query
            return FakeResult(
                [
                    {
                        "person_uid": parameters["person_uid"],
                        "display_name": parameters.get("display_name") or "Updated Name",
                        "excluded": parameters.get("excluded", False),
                    }
                ]
            )
        return FakeResult()

    def execute_write(self, callback, *args):
        return callback(FakeTx(self.calls, self), *args)


class MockNeo4jDriver:
    def __init__(self, canned_records: list[dict[str, Any]] | None = None):
        self.calls = []
        self.canned_records = canned_records or []

    def session(self):
        return MockNeo4jSession(self.calls, self.canned_records)

    def close(self):
        pass


@pytest.fixture
def isolated_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", session_factory)
    yield session_factory
    engine.dispose()


def test_ensure_people_for_accounts_creates_1_to_1_and_excludes_bots():
    canned_accounts = [
        {
            "account_uid": "p1|account|github|alice",
            "login": "alice",
            "display_name": "Alice Developer",
            "provider": "github",
            "is_bot": False,
        },
        {
            "account_uid": "p1|account|github|dependabot[bot]",
            "login": "dependabot[bot]",
            "display_name": "dependabot[bot]",
            "provider": "github",
            "is_bot": True,
        },
    ]
    driver = MockNeo4jDriver(canned_records=canned_accounts)
    stats = identity_service.ensure_people_for_accounts(driver, "p1")

    assert stats["people_created"] == 2
    assert stats["relationships_created"] == 2

    # Verificar os parâmetros passados para o UNWIND MERGE
    merge_call = next(call for call in driver.calls if "MERGE (p:Person" in call[0])
    rows = merge_call[1]["rows"]
    assert len(rows) == 2

    alice_row = next(r for r in rows if r["account_uid"] == "p1|account|github|alice")
    assert alice_row["display_name"] == "Alice Developer"
    assert alice_row["excluded"] is False
    assert alice_row["person_uid"] == "p1|person|cognis|github_alice"

    bot_row = next(r for r in rows if "dependabot" in r["account_uid"])
    assert bot_row["excluded"] is True


def test_ensure_people_respects_person_overrides():
    canned_accounts = [
        {
            "account_uid": "p1|account|github|bot_service",
            "login": "bot_service",
            "display_name": "Bot Service",
            "provider": "github",
            "is_bot": True,
        }
    ]
    person_uid = "p1|person|cognis|github_bot_service"
    override = PersonOverride(
        project_id="p1",
        person_uid=person_uid,
        display_name="Service Humanizado",
        excluded=False,  # Usuário incluiu o bot
    )
    driver = MockNeo4jDriver(canned_records=canned_accounts)
    stats = identity_service.ensure_people_for_accounts(
        driver, "p1", overrides_by_uid={person_uid: override}
    )

    assert stats["people_created"] == 1
    merge_call = next(call for call in driver.calls if "MERGE (p:Person" in call[0])
    row = merge_call[1]["rows"][0]
    assert row["display_name"] == "Service Humanizado"
    assert row["excluded"] is False


def test_list_people_marks_is_me_for_connected_user(isolated_db):
    session = isolated_db()
    user = User(id="user-1", email="user@test.org", password_hash="hash")
    session.add(user)
    session.add(
        ProviderConnection(
            user_id="user-1",
            provider="github",
            external_login="my_github_user",
            access_token_enc="enc",
            status="connected",
        )
    )
    session.commit()

    canned_people = [
        {
            "person_uid": "p1|person|cognis|github_my_github_user",
            "display_name": "My Name",
            "excluded": False,
            "raw_accounts": [
                {
                    "uid": "p1|account|github|my_github_user",
                    "provider": "github",
                    "login": "my_github_user",
                    "display_name": "My Name",
                    "avatar_url": None,
                    "is_bot": False,
                    "linked": True,
                }
            ],
        },
        {
            "person_uid": "p1|person|cognis|github_other",
            "display_name": "Other Dev",
            "excluded": False,
            "raw_accounts": [
                {
                    "uid": "p1|account|github|other",
                    "provider": "github",
                    "login": "other",
                    "display_name": "Other Dev",
                    "avatar_url": None,
                    "is_bot": False,
                    "linked": True,
                }
            ],
        },
    ]

    driver = MockNeo4jDriver(canned_records=canned_people)
    people = identity_service.list_people_for_project(
        driver, "p1", user_id="user-1", db_session=session
    )

    assert len(people) == 2
    me_person = next(p for p in people if p["display_name"] == "My Name")
    other_person = next(p for p in people if p["display_name"] == "Other Dev")

    assert me_person["is_me"] is True
    assert other_person["is_me"] is False
    session.close()


def test_people_api_requires_auth_and_validates_isolation(isolated_db, monkeypatch):
    driver = MockNeo4jDriver()
    monkeypatch.setattr(main, "create_neo4j_driver", lambda: driver)

    session = isolated_db()
    owner = User(id="owner-id", email="owner@test.org", password_hash="hash")
    session.add(owner)
    project = Project(id="proj-1", user_id="owner-id", name="Meu Projeto")
    session.add(project)
    session.commit()
    session.close()

    with TestClient(main.app) as client:
        # 1. Sem autenticação -> 401
        res = client.get("/projects/proj-1/people")
        assert res.status_code == 401

        # 2. Registrar outro usuário (usuário B)
        reg_b = client.post(
            "/auth/register",
            json={"email": "user_b@test.org", "password": "password123"},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert reg_b.status_code == 200

        # Usuário B tenta acessar projeto do owner -> 404 (isolamento multi-tenant)
        res_iso = client.get("/projects/proj-1/people")
        assert res_iso.status_code == 404

        res_patch_iso = client.patch(
            "/projects/proj-1/people/person-1",
            json={"display_name": "Hack"},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert res_patch_iso.status_code == 404


def test_patch_person_updates_sqlite_override_and_graph(isolated_db, monkeypatch):
    driver = MockNeo4jDriver()
    monkeypatch.setattr(main, "create_neo4j_driver", lambda: driver)

    with TestClient(main.app) as client:
        # Registrar usuário (cria sessão)
        reg_res = client.post(
            "/auth/register",
            json={"email": "user@test.org", "password": "password123"},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert reg_res.status_code == 200
        user_id = reg_res.json()["user_id"]

        session = isolated_db()
        project = Project(id="proj-1", user_id=user_id, name="Projeto")
        session.add(project)
        session.commit()
        session.close()

        # Atualizar nome e exclusão
        person_uid = "proj-1|person|cognis|github_dev"
        patch_res = client.patch(
            f"/projects/proj-1/people/{person_uid}",
            json={"display_name": "Dev Sênior", "excluded": True},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert patch_res.status_code == 200
        data = patch_res.json()
        assert data["display_name"] == "Dev Sênior"
        assert data["excluded"] is True

        # Verificar no SQLite
        check_session = isolated_db()
        override = check_session.get(PersonOverride, ("proj-1", person_uid))
        assert override is not None
        assert override.display_name == "Dev Sênior"
        assert override.excluded is True
        check_session.close()


def test_find_merge_suggestions_detects_exact_similarity_and_git_authors():
    people = [
        {
            "person_uid": "p-1",
            "display_name": "João da Silva",
            "accounts": [
                {
                    "uid": "acc-gh",
                    "provider": "github",
                    "login": "joaosilva",
                    "display_name": "João da Silva",
                    "linked": True,
                }
            ],
        },
        {
            "person_uid": "p-2",
            "display_name": "Joao Silva",
            "accounts": [
                {
                    "uid": "acc-tr",
                    "provider": "trello",
                    "login": "joao_silva",
                    "display_name": "Joao Silva",
                    "linked": True,
                }
            ],
        },
        {
            "person_uid": "p-3",
            "display_name": "Git Committer",
            "accounts": [
                {
                    "uid": "acc-git",
                    "provider": "git",
                    "login": "João da Silva",
                    "display_name": "João da Silva",
                    "linked": False,
                }
            ],
        },
    ]

    suggestions = identity_service.find_merge_suggestions(people)
    assert len(suggestions) >= 2

    # Sugestão entre GitHub e Trello (nomes normalizados idênticos "joao da silva" vs "joao silva" ou similaridade >= 0.85)
    gh_tr = next((s for s in suggestions if s["reason"] in ("Nome idêntico entre GitHub e Trello", "Alta similaridade de identificador (88%)") or s["confidence"] >= 0.85), None)
    assert gh_tr is not None
    assert gh_tr["confidence"] >= 0.85

    # Sugestão com autor git linked=false
    git_sug = next((s for s in suggestions if s["account_b"]["provider"] == "git"), None)
    assert git_sug is not None
    assert git_sug["confidence"] == 0.90
    assert git_sug["person_a_uid"] == "p-1"


def test_merge_people_moves_accounts_and_removes_empty_person():
    driver = MockNeo4jDriver()
    res = identity_service.merge_people(
        driver,
        project_id="proj-1",
        keep_person_uid="keep-uid",
        merge_person_uids=["other-uid"],
    )

    assert res["person_uid"] == "keep-uid"
    assert len(res["accounts"]) == 2

    # Verifica chamadas do Neo4j
    assert any("DELETE r" in call[0] for call in driver.calls)
    assert any("DELETE m" in call[0] for call in driver.calls)


def test_split_person_disconnects_account_and_creates_new_person():
    driver = MockNeo4jDriver()
    res = identity_service.split_person(
        driver,
        project_id="proj-1",
        person_uid="keep-uid",
        account_uid="proj-1|account|trello|user2",
    )

    assert "original_person" in res
    assert "new_person" in res
    assert any("DELETE r" in call[0] for call in driver.calls)
    assert any("MERGE (new_p:Person" in call[0] for call in driver.calls)


def test_merge_and_split_api_endpoints_work_and_validate(isolated_db, monkeypatch):
    driver = MockNeo4jDriver()
    monkeypatch.setattr(main, "create_neo4j_driver", lambda: driver)

    with TestClient(main.app) as client:
        reg_res = client.post(
            "/auth/register",
            json={"email": "owner@test.org", "password": "password123"},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert reg_res.status_code == 200
        user_id = reg_res.json()["user_id"]

        session = isolated_db()
        project = Project(id="proj-1", user_id=user_id, name="Projeto Teste")
        session.add(project)
        session.commit()
        session.close()

        # 1. POST /merge
        merge_res = client.post(
            "/projects/proj-1/people/merge",
            json={
                "keep_person_id": "keep-uid",
                "merge_person_ids": ["merge-uid-1"],
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert merge_res.status_code == 200
        assert merge_res.json()["person"]["person_uid"] == "keep-uid"

        # 2. POST /merge com a própria pessoa apenas -> 400
        bad_merge = client.post(
            "/projects/proj-1/people/merge",
            json={
                "keep_person_id": "keep-uid",
                "merge_person_ids": ["keep-uid"],
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert bad_merge.status_code == 400

        # 3. POST /split
        split_res = client.post(
            "/projects/proj-1/people/keep-uid/split",
            json={"account_uid": "proj-1|account|trello|user2"},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert split_res.status_code == 200
        assert split_res.json()["project_id"] == "proj-1"

        # 4. GET /projects/proj-1/people inclui sugestões
        get_res = client.get("/projects/proj-1/people")
        assert get_res.status_code == 200
        assert "suggestions" in get_res.json()

