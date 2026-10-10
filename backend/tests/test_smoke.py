from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from app import auth_router, main, config


class FakeDriver:
    def __init__(self, unavailable: bool = False):
        self.unavailable = unavailable
        self.close_count = 0

    def verify_connectivity(self):
        if self.unavailable:
            raise ServiceUnavailable("Neo4j indisponível")

    def close(self):
        self.close_count += 1


class FakeUserStore:
    users: dict[str, dict[str, str | None]] = {}

    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def ensure_constraints(self):
        return None

    def get_local_user(self, email: str):
        return self.users.get(email)

    def create_local_user(
        self, email: str, password_hash: str, name: str | None = None
    ) -> str:
        user = {
            "id": "smoke-user",
            "email": email,
            "name": name,
            "password_hash": password_hash,
        }
        self.users[email] = user
        return user["id"]

    def get_connections(self, user_id: str):
        return {}


def test_auth_smoke(monkeypatch):
    FakeUserStore.users = {}
    drivers = []

    def create_driver():
        driver = FakeDriver()
        drivers.append(driver)
        return driver

    monkeypatch.setattr(main, "create_neo4j_driver", create_driver)
    monkeypatch.setattr(auth_router, "UserStore", FakeUserStore)
    monkeypatch.setattr(main, "UserStore", FakeUserStore)
    main.app.dependency_overrides[auth_router.get_current_user_id] = (
        lambda: "smoke-user"
    )

    try:
        with TestClient(
            main.app, headers={"Origin": config.app_config.frontend_url}
        ) as client:
            assert client.get("/health").json() == {
                "status": "ok",
                "neo4j": "connected",
            }
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
            assert current_user.json()["user_id"] == "smoke-user"
            assert len(drivers) == 1
            assert drivers[0].close_count == 0
    finally:
        main.app.dependency_overrides.clear()
    assert drivers[0].close_count == 1


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

    with TestClient(main.app) as client:
        response = client.get("/auth/github/login")

    authorize_url = urlsplit(response.json()["authorize_url"])
    assert parse_qs(authorize_url.query) == {
        "client_id": ["client id"],
        "redirect_uri": ["https://cognis.example/callback?source=dev"],
        "scope": ["read:user repo"],
        "state": [client.cookies.get("cognis_oauth_state")],
    }


def test_oauth_errors_do_not_return_provider_payloads(monkeypatch):
    payload_marker = "PROVIDER_RESPONSE_SECRET"
    driver = FakeDriver()
    monkeypatch.setattr(main, "create_neo4j_driver", lambda: driver)
    monkeypatch.setattr(
        auth_router,
        "github_oauth",
        SimpleNamespace(
            token_url="https://github.example/token",
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://cognis.example/callback",
        ),
    )

    class GithubResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"error_description": payload_marker}

    monkeypatch.setattr(auth_router.requests, "post", lambda *args, **kwargs: GithubResponse())

    with TestClient(main.app) as client:
        client.cookies.set("cognis_oauth_state", "github-state")
        github_response = client.get(
            "/auth/github/callback?code=code&state=github-state"
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
            token_url="https://trello.example/token",
        ),
    )

    class TrelloResponse:
        ok = False
        status_code = 400
        text = payload_marker

    monkeypatch.setattr(auth_router.requests, "post", lambda *args, **kwargs: TrelloResponse())

    with TestClient(main.app) as client:
        client.cookies.set("trello_oauth_state", "trello-state")
        client.cookies.set("trello_pkce_verifier", "verifier")
        response = client.get(
            "/auth/trello/exchange?code=code&state=trello-state"
        )

    assert response.status_code == 400
    assert payload_marker not in response.text
    assert driver.close_count == 1
