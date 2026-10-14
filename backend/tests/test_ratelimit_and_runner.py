from __future__ import annotations

import datetime as dt
import time
from unittest.mock import MagicMock

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import session as db_session
from app.db.models import Project, ProjectSource, SyncRun, User
from app.github_v2_collector import _incremental_since, _iso_utc
from app.ingest import ratelimit
from app.ingest.ratelimit import RateLimitPaused, check_github_rate_limit, request_with_retry
from app.ingest.runner import run_project_sync_job
from app import project_sync

UTC = dt.timezone.utc


@pytest.fixture
def isolated_db(monkeypatch):
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
    db_session.create_database()
    yield
    engine.dispose()


def test_incremental_since_overlap_five_minutes():
    initial = "2026-07-15T12:00:00Z"
    cursor = {"commits": "2026-10-10T12:00:00Z"}

    # Quando a chave não está no cursor: usa initial_since
    result_initial = _incremental_since({}, "commits", initial)
    assert result_initial == initial

    # Quando a chave está no cursor: recua 5 minutos (overlap)
    result_overlap = _incremental_since(cursor, "commits", initial, overlap_minutes=5)
    assert result_overlap == "2026-10-10T11:55:00Z"


def test_rate_limit_checks_remaining_threshold(monkeypatch):
    now = dt.datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    now_ts = now.timestamp()

    # Caso 1: remaining >= 200 -> OK
    def fake_get_ok(url, headers, timeout):
        resp = MagicMock()
        resp.json.return_value = {
            "resources": {"core": {"remaining": 4500, "reset": now_ts + 3600}}
        }
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr(ratelimit.requests, "get", fake_get_ok)
    result_ok = check_github_rate_limit("token", now=now)
    assert result_ok["status"] == "ok"
    assert result_ok["remaining"] == 4500

    # Caso 2: remaining < 200 e reset em <= 5 min (300s) -> espera e ok
    waited = []
    def fake_get_soon(url, headers, timeout):
        resp = MagicMock()
        resp.json.return_value = {
            "resources": {"core": {"remaining": 50, "reset": now_ts + 120}}
        }
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr(ratelimit.requests, "get", fake_get_soon)
    result_soon = check_github_rate_limit(
        "token", now=now, sleeper=lambda secs: waited.append(secs)
    )
    assert result_soon["status"] == "waited"
    assert len(waited) == 1
    assert waited[0] == 120

    # Caso 3: remaining < 200 e reset em > 5 min -> levanta RateLimitPaused
    def fake_get_exhausted(url, headers, timeout):
        resp = MagicMock()
        resp.json.return_value = {
            "resources": {"core": {"remaining": 10, "reset": now_ts + 1800}}
        }
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr(ratelimit.requests, "get", fake_get_exhausted)
    with pytest.raises(RateLimitPaused) as exc_info:
        check_github_rate_limit("token", now=now)
    assert exc_info.value.remaining == 10
    assert exc_info.value.reset_at == dt.datetime.fromtimestamp(now_ts + 1800, tz=UTC)


def test_request_with_retry_on_5xx(monkeypatch):
    attempts = []

    def fake_request(method, url, **kwargs):
        attempts.append(len(attempts) + 1)
        resp = MagicMock()
        if len(attempts) < 3:
            resp.status_code = 502
        else:
            resp.status_code = 200
        return resp

    monkeypatch.setattr(ratelimit.requests, "request", fake_request)
    waited = []
    res = request_with_retry("GET", "https://api.github.com/test", sleeper=lambda s: waited.append(s))
    assert res.status_code == 200
    assert len(attempts) == 3
    assert len(waited) == 2


def test_runner_handles_paused_rate_limit(isolated_db, monkeypatch):
    with db_session.SessionLocal() as session:
        user = User(email="rl@example.test", password_hash="hash")
        session.add(user)
        session.flush()
        project = Project(user_id=user.id, name="RateLimit Project", sync_interval_min=60)
        session.add(project)
        session.flush()
        source = ProjectSource(
            project_id=project.id,
            provider="github",
            external_id="owner/repo",
            enabled=True,
        )
        session.add(source)
        run = SyncRun(project_id=project.id, status="queued")
        session.add(run)
        session.commit()
        run_id, project_id, user_id = run.id, project.id, user.id

    reset_time = dt.datetime(2026, 10, 10, 14, 0, tzinfo=UTC)

    def fake_sync_github(*args, **kwargs):
        raise RateLimitPaused(reset_at=reset_time, remaining=12)

    monkeypatch.setattr("app.ingest.runner.ensure_graph_schema", lambda driver: None)
    monkeypatch.setattr("app.ingest.runner.sync_github_project", fake_sync_github)

    run_project_sync_job(run_id, project_id, user_id, object())

    with db_session.SessionLocal() as session:
        saved_run = session.get(SyncRun, run_id)
        saved_project = session.get(Project, project_id)
        assert saved_run is not None
        assert saved_run.status == "paused_rate_limit"
        assert saved_run.progress_json["stage"] == "paused_rate_limit"
        assert saved_project is not None
        assert saved_project.next_sync_at == reset_time
