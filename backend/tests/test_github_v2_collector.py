from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import github_v2_collector as collector
from app.neo4j_v2_writer import Neo4jV2Writer, make_uid

UTC = dt.timezone.utc
GITHUB_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "github" / "capture.json"
)


def _user(login: str, user_type: str = "User") -> dict:
    return {
        "login": login,
        "type": user_type,
        "avatar_url": "https://example.invalid/avatar",
    }


def _payload() -> dict:
    return {
        "commits": [
            {
                "sha": "commit-1",
                "author": _user("contributor[bot]", "Bot"),
                "html_url": "https://example.invalid/commit/commit-1",
                "parents": [{"sha": "parent-1"}],
                "commit": {
                    "author": {
                        "name": "Commit Author",
                        "email": "author@example.test",
                        "date": "2026-10-10T12:00:00Z",
                    },
                    "message": "change module\nprivate details",
                },
            },
            {
                "sha": "merge-commit",
                "author": None,
                "html_url": "https://example.invalid/commit/merge-commit",
                "parents": [{"sha": "parent-1"}, {"sha": "parent-2"}],
                "commit": {
                    "author": {
                        "name": "Merge Author",
                        "email": "merge@example.test",
                        "date": "2026-10-10T13:00:00Z",
                    },
                    "message": "merge change",
                },
            },
        ],
        "commit_details": [
            {
                "sha": "commit-1",
                "stats": {"additions": 4, "deletions": 2},
                "files": [
                    {
                        "filename": "src/core/service.py",
                        "additions": 4,
                        "deletions": 2,
                    },
                    {
                        "filename": "dist/bundle.js",
                        "additions": 50,
                        "deletions": 0,
                    },
                ],
            },
            {
                "sha": "merge-commit",
                "stats": {"additions": 0, "deletions": 0},
                "files": [
                    {
                        "filename": "src/merged.py",
                        "additions": 0,
                        "deletions": 0,
                    }
                ],
            },
        ],
        "issues": [
            {
                "number": 3,
                "title": "Issue title",
                "state": "open",
                "state_reason": None,
                "created_at": "2026-10-09T08:00:00Z",
                "updated_at": "2026-10-10T08:00:00Z",
                "closed_at": None,
                "html_url": "https://example.invalid/issues/3",
                "labels": [{"name": "bug"}],
                "assignees": [_user("assignee"), _user("contributor[bot]", "Bot")],
                "user": _user("creator"),
                "body": "blocked by #9",
            },
            {
                "number": 4,
                "pull_request": {
                    "url": "https://api.github.com/repos/owner/repo/pulls/4"
                },
            },
        ],
        "pulls": [
            {
                "number": 4,
                "title": "Pull title",
                "state": "closed",
                "user": _user("pull-author"),
                "updated_at": "2026-10-10T15:00:00Z",
            }
        ],
        "pull_details": [
            {
                "number": 4,
                "title": "Pull title",
                "state": "closed",
                "user": _user("pull-author"),
                "created_at": "2026-10-08T08:00:00Z",
                "closed_at": "2026-10-10T15:00:00Z",
                "merged_at": "2026-10-10T15:00:00Z",
                "additions": 8,
                "deletions": 2,
                "changed_files": 2,
                "html_url": "https://example.invalid/pulls/4",
                "merged_by": _user("merger"),
                "body": "Closes #3",
            }
        ],
        "reviews": [
            [
                {
                    "id": 11,
                    "state": "APPROVED",
                    "submitted_at": "2026-10-09T10:00:00Z",
                    "user": _user("reviewer"),
                    "body": "review body is not retained",
                },
                {
                    "id": 12,
                    "state": "COMMENTED",
                    "submitted_at": "2026-10-09T09:00:00Z",
                    "user": _user("pull-author"),
                    "body": "author self-review",
                },
                {
                    "id": 13,
                    "state": "PENDING",
                    "submitted_at": None,
                    "user": None,
                    "body": "pending body is not retained",
                },
            ]
        ],
        "pull_comments": [
            {
                "id": 21,
                "pull_request_url": (
                    "https://api.github.com/repos/owner/repo/pulls/4"
                ),
                "created_at": "2026-10-09T11:00:00Z",
                "user": _user("inline-author"),
                "body": "inline comment body",
            }
        ],
        "issue_comments": [
            {
                "id": 31,
                "issue_url": (
                    "https://api.github.com/repos/owner/repo/issues/3"
                ),
                "created_at": "2026-10-09T12:00:00Z",
                "user": None,
                "body": "issue comment body",
            }
        ],
    }


def _find_node(nodes: dict[str, list[dict]], label: str, uid: str) -> dict:
    return next(row for row in nodes[label] if row["uid"] == uid)


def test_build_graph_maps_github_contract_without_persisting_text_bodies():
    project_id = "project-a"
    nodes, relationships = collector.build_github_graph(
        project_id,
        "owner/repo",
        _payload(),
    )

    commit_uid = make_uid(project_id, "commit", "github", "commit-1")
    merge_uid = make_uid(project_id, "commit", "github", "merge-commit")
    issue_uid = make_uid(project_id, "task", "github", "owner/repo#3")
    pull_uid = make_uid(project_id, "pull_request", "github", "owner/repo#4")
    commit = _find_node(nodes, "Commit", commit_uid)
    assert commit["authored_at"] == dt.datetime(2026, 10, 10, 12, tzinfo=UTC)
    assert commit["message"] == "change module"
    assert commit["files_changed"] == 2

    assert len(relationships[("Commit", "ALTEROU", "Module")]) == 1
    module_uid = make_uid(
        project_id, "module", "github", "owner/repo#src"
    )
    module = _find_node(nodes, "Module", module_uid)
    assert module["path"] == "src"
    assert all(
        edge["source_uid"] != merge_uid
        for edge in relationships[("Commit", "ALTEROU", "Module")]
    )

    task = _find_node(nodes, "Task", issue_uid)
    assert task["status_category"] == "todo"
    assert task["labels"] == ["bug"]
    assert task["transitions_json"] == "[]"
    assert "body" not in task

    pull = _find_node(nodes, "PullRequest", pull_uid)
    assert pull["state"] == "merged"
    assert pull["first_review_at"] == dt.datetime(2026, 10, 9, 10, tzinfo=UTC)
    review_nodes = nodes["Review"]
    assert len(review_nodes) == 3
    assert all("body" not in review for review in review_nodes)

    comment_nodes = nodes["Comment"]
    assert len(comment_nodes) == 2
    assert {comment["length"] for comment in comment_nodes} == {
        len("inline comment body"),
        len("issue comment body"),
    }
    assert all("body" not in comment for comment in comment_nodes)
    assert all(row["project_id"] == project_id for rows in nodes.values() for row in rows)
    assert all(
        edge["source_uid"].startswith(f"{project_id}|")
        and edge["target_uid"].startswith(f"{project_id}|")
        for rows in relationships.values()
        for edge in rows
    )

    close_edge = relationships[("PullRequest", "FECHA", "Task")][0]
    assert close_edge["source_uid"] == pull_uid
    assert close_edge["target_uid"] == issue_uid
    assert close_edge["properties"] == {"via": "text"}
    blocked_edge = relationships[("Task", "BLOQUEADA_POR", "Task")][0]
    assert blocked_edge["target_uid"] == make_uid(
        project_id, "task", "github", "owner/repo#9"
    )


def test_redacted_songs_mix_fixture_preserves_contract_counts():
    payload = json.loads(GITHUB_FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["pull_comments"] = []
    payload["issue_comments"] = []

    nodes, _ = collector.build_github_graph(
        "project-a",
        "PepeSlime2/SongsMix",
        payload,
    )

    assert len(nodes["Commit"]) == len(payload["commits"])
    assert len(nodes["Task"]) == sum(
        "pull_request" not in issue for issue in payload["issues"]
    )
    assert len(nodes["PullRequest"]) == len(payload["pulls"])
    assert nodes.get("Review", []) == []
    detailed_shas = {item["sha"] for item in payload["commit_details"]}
    assert all(
        commit["files_changed"] is None
        for commit in nodes["Commit"]
        if commit["sha"] not in detailed_shas
    )


def test_account_normalization_handles_bots_and_unlinked_git_authors():
    nodes, _ = collector.build_github_graph(
        "project-a",
        "owner/repo",
        _payload(),
    )

    bot = next(row for row in nodes["Account"] if row["login"] == "contributor[bot]")
    assert bot["is_bot"] is True
    assert bot["provider"] == "github"

    git_author = next(
        row for row in nodes["Account"] if row["login"] == "Merge Author"
    )
    assert git_author["provider"] == "git"
    assert git_author["linked"] is False
    assert git_author["email_hash"] is not None
    assert "email" not in git_author
    assert "merge@example.test" not in str(nodes)

    assert not any(row["login"] == "Commit Author" for row in nodes["Account"])


def test_initial_and_incremental_fetch_use_independent_cursors(monkeypatch):
    calls: list[tuple[str, dict | None]] = []

    def fake_pages(_token, path, params=None):
        assert _token == "token"
        calls.append((path, params))
        if path.endswith("/commits"):
            return iter([])
        if path.endswith("/issues"):
            return iter([])
        if path.endswith("/pulls"):
            return iter(
                [
                    {
                        "number": 7,
                        "updated_at": "2026-10-13T12:00:00Z",
                        "state": "open",
                        "title": "Pull title",
                        "user": None,
                    },
                    {
                        "number": 6,
                        "updated_at": "2026-10-11T12:00:00Z",
                        "state": "closed",
                        "title": "Old pull",
                        "user": None,
                    },
                ]
            )
        return iter([])

    def fake_detail(_token, path):
        assert _token == "token"
        if "/pulls/7" in path:
            return {
                "number": 7,
                "state": "open",
                "title": "Pull title",
                "user": None,
            }
        raise AssertionError(f"Unexpected details request: {path}")

    monkeypatch.setattr(collector, "_paginated_get", fake_pages)
    monkeypatch.setattr(collector, "_github_get", fake_detail)
    now = dt.datetime(2026, 10, 14, 12, tzinfo=UTC)
    cursor = {
        key: "2026-10-12T12:00:00Z"
        for key in collector.NEXT_CURSOR_KEYS
    }

    payload, next_cursor = collector.fetch_github_repo(
        "token",
        "owner/repo",
        cursor,
        now=now,
    )

    assert [pull["number"] for pull in payload["pulls"]] == [7]
    assert calls[0][1] == {"since": "2026-10-12T12:00:00Z"}
    assert next_cursor == {
        key: "2026-10-14T12:00:00Z"
        for key in collector.NEXT_CURSOR_KEYS
    }


def test_project_ownership_is_checked_before_any_graph_work(monkeypatch):
    def reject_project(_session, _project_id, _user_id):
        assert (_session, _project_id, _user_id) == (
            None,
            "project-a",
            "user-b",
        )
        raise HTTPException(404, "Projeto não encontrado")

    class UnusedWriter:
        def __getattr__(self, name):
            raise AssertionError(f"Graph access attempted: {name}")

    monkeypatch.setattr(
        collector.repository,
        "get_project_for_user",
        reject_project,
    )

    with pytest.raises(HTTPException) as error:
        collector.sync_github_project(
            session=None,
            user_id="user-b",
            project_id="project-a",
            writer=UnusedWriter(),
        )

    assert error.value.status_code == 404


def test_graph_writer_reports_unresolved_references_without_failing_sync():
    class FakeResult:
        def __init__(self, written):
            self.written = written

        def single(self, strict=False):
            assert strict is True
            return {"written": self.written}

    class FakeTransaction:
        def run(self, query, **params):
            if "OPTIONAL MATCH" in query:
                return FakeResult(0)
            return FakeResult(len(params["rows"]))

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            assert len(_args) == 3
            return None

        def execute_write(self, callback, *args):
            return callback(FakeTransaction(), *args)

    class FakeDriver:
        def session(self):
            return FakeSession()

    project_id = "project-a"
    nodes, relationships = collector.build_github_graph(
        project_id,
        "owner/repo",
        _payload(),
    )

    counts = collector.write_github_graph(
        project_id,
        nodes,
        relationships,
        Neo4jV2Writer(FakeDriver()),
    )

    assert counts["unresolved_relationships"] == 2
    assert counts["relationships"]["PullRequest:FECHA:Task"] == 0
    assert counts["relationships"]["Task:BLOQUEADA_POR:Task"] == 0
