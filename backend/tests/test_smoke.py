from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from app import auth_router, main


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
        with TestClient(main.app) as client:
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
