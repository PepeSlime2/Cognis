import datetime as dt
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth_router, main, config, projects_router
from app.db import repository, session as db_session
from app.db.models import Base, ProviderConnection, User
from app import trello_tokens


def register_user(client: TestClient, email: str = "oauth@example.test") -> str:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "password123"},
        headers={"Origin": config.app_config.frontend_url},
    )
    assert response.status_code == 200
    return response.json()["user_id"]


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
    yield
    engine.dispose()


class FakeDriver:
    def __init__(self, unavailable: bool = False):
        self.unavailable = unavailable
        self.close_count = 0

    def verify_connectivity(self):
        if self.unavailable:
            raise ServiceUnavailable("Neo4j indisponível")

    def close(self):
        self.close_count += 1


def test_auth_smoke(monkeypatch):
    drivers = []

    def create_driver():
        driver = FakeDriver()
        drivers.append(driver)
        return driver

    monkeypatch.setattr(main, "create_neo4j_driver", create_driver)

    with TestClient(
        main.app, headers={"Origin": config.app_config.frontend_url}
    ) as client:
        health_data = client.get("/health").json()
        assert health_data["status"] == "ok"
        assert health_data["neo4j"] == "connected"
        assert "ollama" in health_data
        registered = client.post(
            "/auth/register",
            json={
                "email": "smoke@example.test",
                "password": "password123",
                "name": "Smoke",
            },
        )
        assert registered.status_code == 200

        logged_in = client.post(
            "/auth/login",
            json={"email": "smoke@example.test", "password": "password123"},
        )
        assert logged_in.status_code == 200

        current_user = client.get("/auth/me")
        assert current_user.status_code == 200
        assert current_user.json()["user_id"] == registered.json()["user_id"]
        assert current_user.json()["email"] == "smoke@example.test"
        assert current_user.json()["name"] == "Smoke"
        assert current_user.json()["connections"] == {}
        assert len(drivers) == 1
        assert drivers[0].close_count == 0
    assert drivers[0].close_count == 1


def test_sqlite_models_create_all_and_preserve_utc_datetimes():
    db_session.create_database()
    created_at = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    with db_session.SessionLocal() as session:
        user = User(email="utc@example.test", password_hash="hash", created_at=created_at)
        session.add(user)
        session.commit()
        user_id = user.id

    with db_session.SessionLocal() as session:
        saved_user = session.get(User, user_id)

    assert saved_user is not None
    assert saved_user.created_at == created_at
    assert saved_user.created_at.tzinfo == dt.timezone.utc
    assert {
        "users",
        "provider_connections",
        "projects",
        "project_sources",
        "column_mappings",
        "sprints",
        "person_overrides",
        "sync_runs",
        "metric_snapshots",
        "analyses",
        "reports",
    } <= set(Base.metadata.tables)


def test_provider_tokens_are_encrypted_and_not_returned(monkeypatch):
    db_session.create_database()
    token = "test-provider-token"
    monkeypatch.setattr(repository, "encrypt_token", lambda value: f"encrypted:{value}")
    monkeypatch.setattr(
        repository,
        "decrypt_token",
        lambda value: value.removeprefix("encrypted:"),
    )

    with db_session.SessionLocal() as session:
        user = User(email="provider@example.test", password_hash="hash")
        session.add(user)
        session.flush()
        repository.save_provider_connection(
            session,
            user_id=user.id,
            provider="github",
            external_login="test-user",
            access_token=token,
            scope="read:user",
        )
        session.commit()
        connection = session.scalar(
            select(ProviderConnection).where(ProviderConnection.user_id == user.id)
        )

        assert connection is not None
        assert connection.access_token_enc == f"encrypted:{token}"
        assert repository.get_provider_token(session, user.id, "github") == token
        assert token not in str(repository.get_connections(session, user.id))


def test_project_crud_and_owner_isolation():
    with TestClient(main.app, follow_redirects=False) as client:
        register_user(client, "project-owner@example.test")
        created = client.post(
            "/projects",
            json={
                "name": "Projeto de teste",
                "timezone": "America/Sao_Paulo",
                "history_days": 90,
                "auto_sync": True,
                "sync_interval_min": 360,
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert created.status_code == 201, created.text
        project_id = created.json()["id"]
        assert created.json()["name"] == "Projeto de teste"

        listed = client.get("/projects")
        assert listed.status_code == 200
        assert [project["id"] for project in listed.json()] == [project_id]

        updated = client.put(
            f"/projects/{project_id}",
            json={
                "name": "Projeto atualizado",
                "timezone": "UTC",
                "history_days": 180,
                "auto_sync": False,
                "sync_interval_min": 60,
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Projeto atualizado"
        assert updated.json()["history_days"] == 180

        register_user(client, "project-other@example.test")
        assert client.get(f"/projects/{project_id}").status_code == 404
        assert client.put(
            f"/projects/{project_id}",
            json={
                "name": "Tentativa de invasão",
                "timezone": "UTC",
                "history_days": 90,
                "auto_sync": False,
                "sync_interval_min": 60,
            },
            headers={"Origin": config.app_config.frontend_url},
        ).status_code == 404
        assert client.put(
            f"/projects/{project_id}/sources",
            json={"github_repos": [], "trello_boards": []},
            headers={"Origin": config.app_config.frontend_url},
        ).status_code == 404
        assert client.delete(
            f"/projects/{project_id}",
            headers={"Origin": config.app_config.frontend_url},
        ).status_code == 404
        assert client.get("/projects").json() == []

        login = client.post(
            "/auth/login",
            json={"email": "project-owner@example.test", "password": "password123"},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert login.status_code == 200
        owned_project = client.get(f"/projects/{project_id}")
        assert owned_project.status_code == 200
        assert owned_project.json()["name"] == "Projeto atualizado"

        deleted = client.delete(
            f"/projects/{project_id}",
            headers={"Origin": config.app_config.frontend_url},
        )
        assert deleted.status_code == 204
        assert client.get(f"/projects/{project_id}").status_code == 404

def test_put_project_sources_validates_provider_availability(monkeypatch):
    with TestClient(main.app) as client:
        register_user(client, "sources@example.test")
        project_response = client.post(
            "/projects",
            json={"name": "Fontes", "timezone": "America/Sao_Paulo"},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert project_response.status_code == 201, project_response.text
        project_id = project_response.json()["id"]

        with db_session.SessionLocal() as session:
            user = session.scalar(
                select(User).where(User.email == "sources@example.test")
            )
            assert user is not None
            session.add_all(
                [
                    ProviderConnection(
                        user_id=user.id,
                        provider="github",
                        external_login="alice",
                        access_token_enc="encrypted:fake-github-token",
                    ),
                    ProviderConnection(
                        user_id=user.id,
                        provider="trello",
                        external_login="alice",
                        access_token_enc="encrypted:fake-trello-token",
                        refresh_token_enc="encrypted:fake-refresh-token",
                        expires_at=dt.datetime.now(dt.timezone.utc)
                        + dt.timedelta(hours=1),
                    ),
                ]
            )
            session.commit()

        monkeypatch.setattr(
            repository,
            "get_provider_token",
            lambda _session, _user_id, provider: f"{provider}-token",
        )
        monkeypatch.setattr(
            projects_router,
            "fetch_user_repos",
            lambda token: [{"full_name": "alice/repo", "private": True}],
        )
        monkeypatch.setattr(
            projects_router,
            "refresh_if_needed",
            lambda _session, _user_id: "trello-token",
        )
        monkeypatch.setattr(
            projects_router,
            "fetch_user_boards",
            lambda token: [{"id": "board-123", "name": "Board de teste"}],
        )

        saved = client.put(
            f"/projects/{project_id}/sources",
            json={
                "github_repos": ["alice/repo"],
                "trello_boards": ["board-123"],
            },
            headers={"Origin": config.app_config.frontend_url},
        )
        assert saved.status_code == 200
        assert saved.json()["sources"] == [
            {
                "provider": "github",
                "external_id": "alice/repo",
                "display_name": "alice/repo",
                "enabled": True,
            },
            {
                "provider": "trello",
                "external_id": "board-123",
                "display_name": "Board de teste",
                "enabled": True,
            },
        ]

        invalid_source = client.put(
            f"/projects/{project_id}/sources",
            json={"github_repos": ["alice/not-available"]},
            headers={"Origin": config.app_config.frontend_url},
        )
        assert invalid_source.status_code == 422
        assert client.get(f"/projects/{project_id}").json()["sources"] == saved.json()[
            "sources"
        ]


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "  ", "timezone": "UTC"},
        {"name": "x" * 81, "timezone": "UTC"},
        {"name": "Projeto", "timezone": "Not/A_Zone"},
        {"name": "Projeto", "timezone": "UTC", "history_days": 6},
        {"name": "Projeto", "timezone": "UTC", "history_days": 366},
        {"name": "Projeto", "timezone": "UTC", "sync_interval_min": 45},
    ],
)
def test_project_input_limits_are_validated(payload):
    with TestClient(main.app) as client:
        register_user(client, "limits@example.test")
        response = client.post(
            "/projects",
            json=payload,
            headers={"Origin": config.app_config.frontend_url},
        )

    assert response.status_code == 422


def test_health_reports_neo4j_unavailable(monkeypatch):
    driver = FakeDriver(unavailable=True)
    monkeypatch.setattr(main, "create_neo4j_driver", lambda: driver)

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "neo4j": "unavailable"}
    assert driver.close_count == 1


def test_non_get_requests_require_matching_origin():
    with TestClient(main.app) as client:
        wrong_origin = client.post(
            "/auth/logout", headers={"Origin": "https://attacker.example"}
        )
        missing_origin = client.post("/auth/logout")

    assert wrong_origin.status_code == 403
    assert missing_origin.status_code == 403


def test_non_get_request_accepts_matching_referer():
    with TestClient(main.app) as client:
        response = client.post(
            "/auth/logout",
            headers={"Referer": f"{config.app_config.frontend_url}/settings"},
        )

    assert response.status_code == 200


def test_provider_connections_require_an_authenticated_session():
    with TestClient(main.app) as client:
        responses = [
            client.get("/auth/github/login"),
            client.get("/auth/github/callback?code=code&state=state"),
            client.get("/auth/trello/authorize-url"),
            client.get("/auth/trello/exchange?code=code&state=state"),
        ]

    assert [response.status_code for response in responses] == [401, 401, 401, 401]
    assert all("access_token" not in response.text for response in responses)
    with db_session.SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


def test_localhost_origin_is_allowed_only_in_development(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(main, "create_neo4j_driver", lambda: driver)
    development_config = replace(
        config.app_config, environment="dev", frontend_url="https://cognis.app"
    )
    monkeypatch.setattr(
        main,
        "app_config",
        development_config,
    )
    assert "http://localhost:5173" in development_config.allowed_frontend_origins

    with TestClient(main.app) as client:
        dev_response = client.post(
            "/auth/logout", headers={"Origin": "http://localhost:5173"}
        )

    assert dev_response.status_code == 200
    assert driver.close_count == 1

    production_config = replace(
        config.app_config, environment="production", frontend_url="https://cognis.app"
    )
    monkeypatch.setattr(main, "app_config", production_config)
    assert "http://localhost:5173" not in production_config.allowed_frontend_origins
    assert not main._matches_frontend_origin("http://localhost:5173")


def test_github_login_encodes_authorization_parameters(monkeypatch):
    monkeypatch.setattr(
        auth_router,
        "github_oauth",
        SimpleNamespace(
            authorize_url="https://github.example/authorize",
            client_id="client id",
            redirect_uri="https://cognis.example/callback?source=dev",
            scope="read:user repo",
        ),
    )

    with TestClient(main.app, follow_redirects=False) as client:
        register_user(client)
        response = client.get("/auth/github/login")

    authorize_url = urlsplit(response.json()["authorize_url"])
    assert parse_qs(authorize_url.query) == {
        "client_id": ["client id"],
        "redirect_uri": ["https://cognis.example/callback?source=dev"],
        "scope": ["read:user repo"],
        "state": [client.cookies.get("cognis_oauth_state")],
    }


def test_trello_authorize_url_encodes_state_and_pkce(monkeypatch):
    monkeypatch.setattr(
        auth_router,
        "trello_oauth",
        SimpleNamespace(
            authorize_url="https://auth.atlassian.com/authorize",
            client_id="trello-client-id",
            scope="read:member:trello read:board:trello offline_access",
            workspace_id="areadetrabalho74169937",
        ),
    )

    with TestClient(main.app, follow_redirects=False) as client:
        register_user(client)
        response = client.get("/auth/trello/authorize-url")

    assert response.status_code == 200
    authorize_url = urlsplit(response.json()["authorize_url"])
    query = parse_qs(authorize_url.query)
    assert query["client_id"] == ["trello-client-id"]
    assert query["state"] == [client.cookies.get("trello_oauth_state")]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert "code_challenge" in query
    assert query["resource"] == ["ari:cloud:trello::workspace/areadetrabalho74169937"]
    assert client.cookies.get("trello_pkce_verifier") is not None


def test_github_callback_saves_token_for_authenticated_user_without_exposing_it(
    monkeypatch, caplog
):
    token = "github-access-token-secret"
    monkeypatch.setattr(
        auth_router,
        "github_oauth",
        SimpleNamespace(
            authorize_url="https://github.example/authorize",
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://cognis.example/callback",
            token_url="https://github.example/token",
            scope="read:user repo",
        ),
    )
    def github_token_response(url, **kwargs):
        assert url == "https://github.example/token"
        assert kwargs["timeout"] == 15
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"access_token": token},
        )

    def github_username(access_token):
        assert access_token == token
        return "alice"

    monkeypatch.setattr(auth_router.requests, "post", github_token_response)
    monkeypatch.setattr(auth_router, "get_github_username", github_username)
    monkeypatch.setattr(repository, "encrypt_token", lambda value: f"encrypted:{value}")

    with TestClient(main.app, follow_redirects=False) as client:
        user_id = register_user(client)
        client.get("/auth/github/login")
        state = client.cookies.get("cognis_oauth_state")
        response = client.get(
            f"/auth/github/callback?code=code&state={state}"
        )
        session_response = client.get("/auth/me")

    assert response.status_code == 302
    assert token not in response.text
    assert token not in str(response.headers)
    assert session_response.status_code == 200
    assert token not in session_response.text
    assert token not in caplog.text

    with db_session.SessionLocal() as session:
        connection = session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.user_id == user_id,
                ProviderConnection.provider == "github",
            )
        )
        assert connection is not None
        assert connection.access_token_enc == f"encrypted:{token}"


def test_expired_trello_token_is_rotated_and_persisted_before_api_call(monkeypatch):
    db_session.create_database()
    old_access = "old-access-token"
    old_refresh = "old-refresh-token"
    new_access = "new-access-token"
    new_refresh = "new-refresh-token"
    monkeypatch.setattr(
        trello_tokens,
        "decrypt_token",
        lambda value: value.removeprefix("encrypted:"),
    )
    monkeypatch.setattr(
        trello_tokens,
        "encrypt_token",
        lambda value: f"encrypted:{value}",
    )

    with db_session.SessionLocal() as session:
        user = User(
            email="refresh@example.test",
            password_hash=auth_router.hash_password("password123"),
        )
        session.add(user)
        session.flush()
        connection = ProviderConnection(
            user_id=user.id,
            provider="trello",
            external_login="alice",
            access_token_enc=f"encrypted:{old_access}",
            refresh_token_enc=f"encrypted:{old_refresh}",
            expires_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1),
            status="ok",
        )
        session.add(connection)
        session.commit()
        user_id = user.id

    def refresh_response(url, **kwargs):
        assert url == auth_router.trello_oauth.token_url
        assert kwargs["json"] == {
            "grant_type": "refresh_token",
            "client_id": auth_router.trello_oauth.client_id,
            "client_secret": auth_router.trello_oauth.client_secret,
            "refresh_token": old_refresh,
        }
        return SimpleNamespace(
            ok=True,
            json=lambda: {
                "access_token": new_access,
                "refresh_token": new_refresh,
                "expires_in": 3600,
            },
        )

    monkeypatch.setattr(trello_tokens.requests, "post", refresh_response)
    api_tokens = []

    def list_boards(access_token):
        api_tokens.append(access_token)
        return []

    monkeypatch.setattr(main, "fetch_user_boards", list_boards)
    with TestClient(main.app) as client:
        client.post(
            "/auth/login",
            json={"email": "refresh@example.test", "password": "password123"},
            headers={"Origin": config.app_config.frontend_url},
        )
        response = client.get("/trello/boards")

    assert response.status_code == 200
    assert api_tokens == [new_access]
    assert new_access not in response.text
    assert new_refresh not in response.text
    with db_session.SessionLocal() as session:
        connection = session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.user_id == user_id,
                ProviderConnection.provider == "trello",
            )
        )
        assert connection is not None
        assert connection.access_token_enc == f"encrypted:{new_access}"
        assert connection.refresh_token_enc == f"encrypted:{new_refresh}"
        assert connection.expires_at is not None
        assert connection.expires_at > dt.datetime.now(dt.timezone.utc)


def test_invalid_grant_marks_trello_connection_for_reconnect(monkeypatch):
    db_session.create_database()
    monkeypatch.setattr(
        trello_tokens,
        "decrypt_token",
        lambda value: value.removeprefix("encrypted:"),
    )
    with db_session.SessionLocal() as session:
        user = User(
            email="invalid-grant@example.test",
            password_hash=auth_router.hash_password("password123"),
        )
        session.add(user)
        session.flush()
        session.add(
            ProviderConnection(
                user_id=user.id,
                provider="trello",
                external_login="alice",
                access_token_enc="encrypted:old-access",
                refresh_token_enc="encrypted:old-refresh",
                expires_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1),
                status="ok",
            )
        )
        session.commit()

    provider_error = "provider-private-error-details"
    monkeypatch.setattr(
        trello_tokens.requests,
        "post",
        lambda *args, **kwargs: SimpleNamespace(
            ok=False,
            json=lambda: {
                "error": "invalid_grant",
                "error_description": provider_error,
            },
        ),
    )
    with TestClient(main.app) as client:
        client.post(
            "/auth/login",
            json={"email": "invalid-grant@example.test", "password": "password123"},
            headers={"Origin": config.app_config.frontend_url},
        )
        response = client.get("/trello/boards")

    assert response.status_code == 401
    assert response.json() == {"detail": "Trello precisa ser conectado novamente"}
    assert provider_error not in response.text
    with db_session.SessionLocal() as session:
        connection = session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.provider == "trello"
            )
        )
        assert connection is not None
        assert connection.status == "needs_reconnect"


def test_oauth_callback_cannot_be_transferred_to_another_signed_in_user():
    with TestClient(main.app, follow_redirects=False) as client:
        register_user(client, "first@example.test")
        client.get("/auth/github/login")
        state = client.cookies.get("cognis_oauth_state")
        register_user(client, "second@example.test")
        response = client.get(
            f"/auth/github/callback?code=code&state={state}"
        )

    assert response.status_code == 400
    with db_session.SessionLocal() as session:
        assert session.scalar(select(ProviderConnection)) is None


def test_trello_callback_saves_token_for_authenticated_user_without_exposing_it(
    monkeypatch, caplog
):
    token = "trello-access-token-secret"
    refresh_token = "trello-refresh-token-secret"
    monkeypatch.setattr(
        auth_router,
        "trello_oauth",
        SimpleNamespace(
            client_id="client-id",
            client_secret="client-secret",
            authorize_url="https://trello.example/authorize",
            token_url="https://trello.example/token",
            scope="read:member:trello offline_access",
        ),
    )

    def trello_token_response(url, **kwargs):
        assert url == "https://trello.example/token"
        assert kwargs["timeout"] == 15
        return SimpleNamespace(
            ok=True,
            json=lambda: {
                "access_token": token,
                "refresh_token": refresh_token,
                "expires_in": 3600,
            },
        )

    def trello_member(access_token):
        assert access_token == token
        return {
            "username": "alice",
            "fullName": "Alice",
            "avatarUrl": None,
        }

    monkeypatch.setattr(auth_router.requests, "post", trello_token_response)
    monkeypatch.setattr(auth_router, "get_trello_member", trello_member)
    monkeypatch.setattr(repository, "encrypt_token", lambda value: f"encrypted:{value}")

    with TestClient(main.app) as client:
        user_id = register_user(client)
        authorize_response = client.get("/auth/trello/authorize-url")
        assert authorize_response.status_code == 200
        state = client.cookies.get("trello_oauth_state")
        response = client.get(
            f"/auth/trello/exchange?code=code&state={state}"
        )
        session_response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {"connected": "trello", "username": "alice"}
    assert session_response.status_code == 200
    assert token not in session_response.text
    assert token not in response.text
    assert refresh_token not in response.text
    assert token not in caplog.text
    assert refresh_token not in caplog.text

    with db_session.SessionLocal() as session:
        connection = session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.user_id == user_id,
                ProviderConnection.provider == "trello",
            )
        )
        assert connection is not None
        assert connection.access_token_enc == f"encrypted:{token}"
        assert connection.refresh_token_enc is not None
        assert connection.expires_at is not None
        assert connection.expires_at.tzinfo == dt.timezone.utc


def test_oauth_errors_do_not_return_provider_payloads(monkeypatch):
    payload_marker = "PROVIDER_RESPONSE_SECRET"
    driver = FakeDriver()
    monkeypatch.setattr(main, "create_neo4j_driver", lambda: driver)
    monkeypatch.setattr(
        auth_router,
        "github_oauth",
        SimpleNamespace(
            authorize_url="https://github.example/authorize",
            token_url="https://github.example/token",
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://cognis.example/callback",
            scope="read:user",
        ),
    )

    class GithubResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"error_description": payload_marker}

    monkeypatch.setattr(auth_router.requests, "post", lambda *args, **kwargs: GithubResponse())

    with TestClient(main.app) as client:
        register_user(client)
        client.get("/auth/github/login")
        state = client.cookies.get("cognis_oauth_state")
        github_response = client.get(
            f"/auth/github/callback?code=code&state={state}"
        )

    assert github_response.status_code == 400
    assert payload_marker not in github_response.text
    assert driver.close_count == 1


def test_trello_exchange_error_does_not_return_provider_payload(monkeypatch):
    payload_marker = "PROVIDER_RESPONSE_SECRET"
    driver = FakeDriver()
    monkeypatch.setattr(main, "create_neo4j_driver", lambda: driver)
    monkeypatch.setattr(
        auth_router,
        "trello_oauth",
        SimpleNamespace(
            client_id="client-id",
            client_secret="client-secret",
            authorize_url="https://trello.example/authorize",
            token_url="https://trello.example/token",
            scope="read:member:trello",
        ),
    )

    class TrelloResponse:
        ok = False
        status_code = 400
        text = payload_marker

    monkeypatch.setattr(auth_router.requests, "post", lambda *args, **kwargs: TrelloResponse())

    with TestClient(main.app) as client:
        register_user(client)
        client.get("/auth/trello/authorize-url")
        state = client.cookies.get("trello_oauth_state")
        response = client.get(
            f"/auth/trello/exchange?code=code&state={state}"
        )

    assert response.status_code == 400
    assert payload_marker not in response.text
    assert driver.close_count == 1
