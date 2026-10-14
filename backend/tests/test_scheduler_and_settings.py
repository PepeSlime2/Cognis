from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
from unittest.mock import MagicMock
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config, main, project_sync
from app.db import repository
from app.db import session as db_session
from app.db.models import Project, ProjectSource, SyncRun, User, utc_now
from app.ingest.scheduler import (
    execute_scheduler_tick,
    run_scheduler_tick,
    start_scheduler,
    stop_scheduler,
)

UTC = dt.timezone.utc


def register_user(client: TestClient, email: str) -> None:
    client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "name": "Pedro Test"},
        headers={"Origin": config.app_config.frontend_url},
    )


def test_put_project_settings_and_isolation():
    u_a = f"owner_{uuid.uuid4().hex[:8]}@example.test"
    u_b = f"other_{uuid.uuid4().hex[:8]}@example.test"
    with TestClient(main.app, follow_redirects=False) as client_a:
        register_user(client_a, u_a)
        created = client_a.post(
            "/projects",
            json={
                "name": "Projeto Settings",
                "timezone": "America/Sao_Paulo",
                "history_days": 90,
                "auto_sync": False,
                "sync_interval_min": 60,
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert created.status_code == 201
        project_id = created.json()["id"]
        assert created.json()["auto_sync"] is False
        assert created.json()["next_sync_at"] is None

        # 1. Update settings: enable auto_sync with 15 min interval
        put_res = client_a.put(
            f"/projects/{project_id}/settings",
            json={
                "auto_sync": True,
                "sync_interval_min": 15,
                "timezone": "America/Sao_Paulo",
                "settings_json": {"custom_flag": True},
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert put_res.status_code == 200, put_res.text
        data = put_res.json()
        assert data["auto_sync"] is True
        assert data["sync_interval_min"] == 15
        assert data["next_sync_at"] is not None
        assert data["settings_json"] == {"custom_flag": True}

        # 2. GET /projects/{project_id}/settings
        get_res = client_a.get(f"/projects/{project_id}/settings")
        assert get_res.status_code == 200
        settings_data = get_res.json()
        assert settings_data["auto_sync"] is True
        assert settings_data["sync_interval_min"] == 15
        assert settings_data["settings_json"] == {"custom_flag": True}

        # 3. Disable auto_sync: next_sync_at should become None
        disable_res = client_a.put(
            f"/projects/{project_id}/settings",
            json={
                "auto_sync": False,
                "sync_interval_min": 30,
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert disable_res.status_code == 200
        assert disable_res.json()["auto_sync"] is False
        assert disable_res.json()["next_sync_at"] is None

        # 4. Input validation: invalid interval (e.g. 45 min)
        invalid_interval = client_a.put(
            f"/projects/{project_id}/settings",
            json={
                "auto_sync": True,
                "sync_interval_min": 45,
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert invalid_interval.status_code == 422

        # 5. Input validation: invalid timezone
        invalid_tz = client_a.put(
            f"/projects/{project_id}/settings",
            json={
                "auto_sync": True,
                "sync_interval_min": 60,
                "timezone": "Invalid/Zone",
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert invalid_tz.status_code == 422

    # 6. Isolation test: User B cannot modify User A's settings
    with TestClient(main.app, follow_redirects=False) as client_b:
        register_user(client_b, u_b)
        unauthorized_res = client_b.put(
            f"/projects/{project_id}/settings",
            json={
                "auto_sync": True,
                "sync_interval_min": 60,
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert unauthorized_res.status_code == 404


def test_execute_scheduler_tick_enqueues_and_updates_next_sync_at():
    mock_driver = MagicMock()
    mock_executor = MagicMock()

    now = utc_now()
    user_id: str
    project_id: str

    with db_session.SessionLocal() as session:
        user = User(email=f"sched_{uuid.uuid4().hex[:8]}@example.test", name="Sched User")
        session.add(user)
        session.flush()
        user_id = user.id

        # Add provider token
        repository.save_provider_connection(
            session,
            user_id=user.id,
            provider="github",
            external_login="sched-gh",
            access_token="gh_token_123",
        )

        project = Project(
            user_id=user.id,
            name="Sched Project",
            auto_sync=True,
            sync_interval_min=15,
            next_sync_at=now - dt.timedelta(minutes=5),  # Due!
        )
        session.add(project)
        session.flush()
        project_id = project.id

        source = ProjectSource(
            project_id=project.id,
            provider="github",
            external_id="owner/repo",
            display_name="owner/repo",
            enabled=True,
        )
        session.add(source)
        session.commit()

    # Clear active project set in case of leftover state
    with project_sync._active_projects_lock:
        project_sync._active_project_ids.discard(project_id)

    scheduled = execute_scheduler_tick(mock_driver, mock_executor)
    assert project_id in scheduled
    assert mock_executor.submit.called

    with db_session.SessionLocal() as session:
        updated_project = session.get(Project, project_id)
        assert updated_project is not None
        # next_sync_at was updated to the future
        assert updated_project.next_sync_at > now

        # A queued SyncRun was created
        run = session.scalar(
            select(SyncRun)
            .where(SyncRun.project_id == project_id)
            .order_by(SyncRun.started_at.desc())
        )
        assert run is not None
        assert run.status == "queued"

    # Clean up active state
    with project_sync._active_projects_lock:
        project_sync._active_project_ids.discard(project_id)


def test_execute_scheduler_tick_skips_ineligible_projects():
    mock_driver = MagicMock()
    mock_executor = MagicMock()

    now = utc_now()

    with db_session.SessionLocal() as session:
        user = User(email=f"skip_{uuid.uuid4().hex[:8]}@example.test", name="Skip User")
        session.add(user)
        session.flush()

        # Project 1: auto_sync=False
        p1 = Project(
            user_id=user.id,
            name="Manual Project",
            auto_sync=False,
            next_sync_at=now - dt.timedelta(minutes=10),
        )
        # Project 2: auto_sync=True but next_sync_at in future
        p2 = Project(
            user_id=user.id,
            name="Future Project",
            auto_sync=True,
            next_sync_at=now + dt.timedelta(minutes=30),
        )
        session.add_all([p1, p2])
        session.commit()
        p1_id, p2_id = p1.id, p2.id

    scheduled = execute_scheduler_tick(mock_driver, mock_executor)
    assert p1_id not in scheduled
    assert p2_id not in scheduled


def test_async_scheduler_loop_fires_automatically():
    async def _test():
        mock_driver = MagicMock()
        mock_executor = MagicMock()

        now = utc_now()
        project_id: str

        with db_session.SessionLocal() as session:
            user = User(email=f"async_{uuid.uuid4().hex[:8]}@example.test", name="Async Sched")
            session.add(user)
            session.flush()

            repository.save_provider_connection(
                session,
                user_id=user.id,
                provider="github",
                external_login="async-gh",
                access_token="gh_token_async",
            )

            project = Project(
                user_id=user.id,
                name="Auto Loop Project",
                auto_sync=True,
                sync_interval_min=15,
                next_sync_at=now - dt.timedelta(minutes=2),
            )
            session.add(project)
            session.flush()
            project_id = project.id

            source = ProjectSource(
                project_id=project.id,
                provider="github",
                external_id="async/repo",
                display_name="async/repo",
                enabled=True,
            )
            session.add(source)
            session.commit()

        with project_sync._active_projects_lock:
            project_sync._active_project_ids.discard(project_id)

        app_mock = MagicMock()
        app_mock.state.neo4j_driver = mock_driver
        app_mock.state.sync_executor = mock_executor

        # Start scheduler with short 0.05s interval
        task = start_scheduler(app_mock, poll_interval_seconds=0.05)
        assert task is not None

        try:
            # Give enough time for at least 1-2 ticks
            await asyncio.sleep(0.15)

            with db_session.SessionLocal() as session:
                p = session.get(Project, project_id)
                assert p is not None
                # Verified: scheduler dispatched by itself and updated next_sync_at
                assert p.next_sync_at > now
        finally:
            await stop_scheduler(task)
            with project_sync._active_projects_lock:
                project_sync._active_project_ids.discard(project_id)

    asyncio.run(_test())
