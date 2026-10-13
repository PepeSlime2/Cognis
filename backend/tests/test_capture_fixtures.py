import importlib.util
import json
from pathlib import Path
import re


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "capture_fixtures.py"
GITHUB_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "github" / "capture.json"
SPEC = importlib.util.spec_from_file_location("capture_fixtures", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
capture_fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture_fixtures)


def test_redact_payload_removes_emails_tokens_and_private_text():
    token = "secret-provider-token"
    payload = {
        "user": {
            "login": "real-login",
            "email": "person@example.test",
            "name": "real-name",
        },
        "commit": {
            "message": f"private text with {token}",
            "author": {"email": "author@example.test"},
        },
        "url": "https://github.com/real-login/private-repo",
    }

    redacted = capture_fixtures.redact_payload(payload, token, {})

    assert redacted["user"]["login"] == "user-a"
    assert redacted["user"]["email"] is None
    assert redacted["user"]["name"] == "[redacted]"
    assert redacted["commit"]["message"] == "[redacted]"
    assert redacted["commit"]["author"]["email"] is None
    assert redacted["url"] == "https://example.invalid/redacted"
    assert token not in str(redacted)
    assert "person@example.test" not in str(redacted)


def test_redact_payload_uses_consistent_user_aliases():
    payload = [
        {"login": "contributor-a"},
        {"username": "contributor-b"},
        {"login": "contributor-a"},
    ]

    redacted = capture_fixtures.redact_payload(payload, "", {})

    assert redacted == [
        {"login": "user-a"},
        {"username": "user-b"},
        {"login": "user-a"},
    ]


def test_github_request_omits_authorization_when_capturing_public_data(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def fake_get(url, headers, params, timeout):
        captured["headers"] = headers
        return Response()

    monkeypatch.setattr(capture_fixtures.requests, "get", fake_get)

    result = capture_fixtures._github_get("", "/repos/owner/repo")

    assert result == {"ok": True}
    assert "Authorization" not in captured["headers"]


def test_redact_payload_removes_profile_and_diff_content():
    payload = {
        "user": {
            "bio": "private profile",
            "location": "private location",
            "avatar_url": "https://example.com/avatar",
        },
        "file": {
            "patch": "@@ private source diff @@",
            "diff_hunk": "@@ private source context @@",
        },
    }

    redacted = capture_fixtures.redact_payload(payload, "", {})

    assert redacted == {
        "user": {
            "bio": "[redacted]",
            "location": "[redacted]",
            "avatar_url": "https://example.invalid/redacted",
        },
        "file": {
            "patch": "[redacted]",
            "diff_hunk": "[redacted]",
        },
    }


def test_captured_github_fixture_has_contract_sections_and_no_direct_identifiers():
    fixture_text = GITHUB_FIXTURE_PATH.read_text(encoding="utf-8")
    fixture = json.loads(fixture_text)

    assert {
        "commits",
        "commit_details",
        "issues",
        "pulls",
        "pull_details",
        "reviews",
        "pull_comments",
        "issue_comments",
    } == set(fixture)
    assert len(fixture["commits"]) > 0
    assert not re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", fixture_text, re.I)

    def assert_redacted(value):
        if isinstance(value, list):
            for item in value:
                assert_redacted(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                normalized_key = key.lower()
                if normalized_key == "email":
                    assert item is None
                elif normalized_key in {"login", "username", "fullname"} and item:
                    assert re.fullmatch(r"user-[a-z]+", item)
                elif (
                    normalized_key in capture_fixtures.PRIVATE_TEXT_FIELDS
                    and isinstance(item, str)
                ):
                    assert item == "[redacted]"
                elif (
                    normalized_key in capture_fixtures.PRIVATE_URL_FIELDS
                    or normalized_key.endswith("_url")
                ) and item:
                    assert item == "https://example.invalid/redacted"
                else:
                    assert_redacted(item)

    assert_redacted(fixture)
