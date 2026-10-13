from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config, main, project_sync
from app.db import session as db_session
from app.db.models import Project, ProjectSource, SyncRun, User


class EmptyGraphSession:
    def __init__(self, calls):
        self.calls = calls

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        return []


class GraphDriver:
    def __init__(self):
        self.calls = []
        self.close_count = 0

    @contextmanager
    def session(self):
        yield EmptyGraphSession(self.calls)

    def close(self):
        self.close_count += 1


class FakeExecutor:
    def submit(self, function, *args):
        return None

    def shutdown(self, wait=True):
        return None


@pytest.fixture
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
    yield
    engine.dispose()


def _register(client, email):
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "password123"},
        headers={"Origin": config.app_config.frontend_url},
    )
    assert response.status_code == 200
    return response.json()["user_id"]


def test_project_graph_and_async_sync_are_owner_scoped(isolated_database, monkeypatch):
    monkeypatch.setattr(project_sync, "_active_project_ids", set())
    drivers = []

    def create_driver():
        driver = GraphDriver()
        drivers.append(driver)
        return driver

    monkeypatch.setattr(main, "create_neo4j_driver", create_driver)
    monkeypatch.setattr(
        "app.project_sync.repository.get_provider_token",
        lambda session, user_id, provider: "test-token",
    )

    with TestClient(
        main.app, headers={"Origin": config.app_config.frontend_url}
    ) as client:
        owner_id = _register(client, "graph-owner@example.test")
        project_response = client.post(
            "/projects",
            json={"name": "Projeto do grafo"},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]
        with db_session.SessionLocal() as session:
            session.add(
                ProjectSource(
                    project_id=project_id,
                    provider="github",
                    external_id="owner/repo",
                    display_name="owner/repo",
                    enabled=True,
                )
            )
            session.commit()

        client.app.state.sync_executor = FakeExecutor()
        graph_response = client.get(f"/projects/{project_id}/graph")
        assert graph_response.status_code == 200
        assert graph_response.json() == {
            "elements": {"nodes": [], "edges": []},
            "truncated": False,
            "stats": {"nodes": 0, "edges": 0},
        }
        assert len(drivers[0].calls) == 1
        graph_query, graph_parameters = drivers[0].calls[0]
        assert "n.project_id = $project_id" in graph_query
        assert graph_parameters["project_id"] == project_id

        start_response = client.post(
            f"/projects/{project_id}/sync",
            headers={"Origin": config.app_config.frontend_url},
        )
        assert start_response.status_code == 202
        run_id = start_response.json()["run_id"]
        assert start_response.json()["status"] == "queued"
        assert client.post(
            f"/projects/{project_id}/sync",
            headers={"Origin": config.app_config.frontend_url},
        ).status_code == 409
        assert client.get(
            f"/projects/{project_id}/sync-runs/{run_id}"
        ).json()["status"] == "queued"

        _register(client, "graph-other@example.test")
        assert client.get(f"/projects/{project_id}/graph").status_code == 404
        assert client.get(
            f"/projects/{project_id}/sync-runs/{run_id}"
        ).status_code == 404
        assert len(drivers[0].calls) == 1

    assert owner_id
    with project_sync._active_projects_lock:
        project_sync._active_project_ids.discard(project_id)


def test_sync_worker_persists_partial_completion(isolated_database, monkeypatch):
    db_session.create_database()
    with db_session.SessionLocal() as session:
        user = User(email="worker@example.test", password_hash="hash")
        session.add(user)
        session.flush()
        project = Project(user_id=user.id, name="Worker")
        session.add(project)
        session.flush()
        run = SyncRun(project_id=project.id, status="queued")
        session.add(run)
        session.commit()
        run_id, project_id, user_id = run.id, project.id, user.id

    class FakeWriter:
        def __init__(self, driver):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setattr(project_sync, "Neo4jV2Writer", FakeWriter)
    monkeypatch.setattr(project_sync, "ensure_graph_schema", lambda driver: None)
    monkeypatch.setattr(
        project_sync,
        "sync_github_project",
        lambda *args, **kwargs: {
            "completed": [
                {
                    "repository": "owner/repo",
                    "counts": {
                        "nodes": {"Task": 3},
                        "relationships": {"Account:CRIOU:Task": 1},
                        "unresolved_relationships": 0,
                    },
                }
            ],
            "errors": [
                {
                    "source_id": "owner/other",
                    "code": "HTTPError",
                    "message": "Não foi possível sincronizar este repositório GitHub.",
                }
            ],
        },
    )

    project_sync._run_project_sync(run_id, project_id, user_id, object())

    with db_session.SessionLocal() as session:
        saved_run = session.get(SyncRun, run_id)
        saved_project = session.get(Project, project_id)
        assert saved_run is not None
        assert saved_run.status == "partial"
        assert saved_run.stats_json["repositories_succeeded"] == 1
        assert saved_run.stats_json["repositories_failed"] == 1
        assert saved_run.progress_json["stage"] == "done"
        assert saved_project is not None and saved_project.next_sync_at is not None
