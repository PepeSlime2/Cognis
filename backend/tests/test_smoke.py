from fastapi.testclient import TestClient

from app import auth_router, main


class FakeUserStore:
    users: dict[str, dict[str, str | None]] = {}

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
    monkeypatch.setattr(auth_router, "UserStore", FakeUserStore)
    monkeypatch.setattr(main, "UserStore", FakeUserStore)
    main.app.dependency_overrides[auth_router.get_current_user_id] = (
        lambda: "smoke-user"
    )

    try:
        with TestClient(main.app) as client:
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
    finally:
        main.app.dependency_overrides.clear()
