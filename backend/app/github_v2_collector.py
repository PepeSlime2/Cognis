from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import re
from collections.abc import Callable, Iterable, Iterator
from typing import Any
from urllib.parse import quote, urlsplit

import requests
from fastapi import HTTPException
from neo4j.exceptions import Neo4jError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .db import repository
from .db.models import ProjectSource, ProviderConnection
from .neo4j_v2_writer import Neo4jV2Writer, make_uid

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
DEFAULT_IGNORE_GLOBS = (
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "*.min.js",
    "dist/**",
    "build/**",
    "node_modules/**",
    "*.svg",
    "*.png",
    "*.jpg",
    "*.pdf",
)
REVIEW_STATES = frozenset(
    {"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING"}
)
OPTIONAL_REFERENCE_RELATIONSHIPS = frozenset(
    {"FECHA", "BLOQUEADA_POR", "RELACIONADA_A"}
)
CLOSES_RE = re.compile(
    r"\b(closes|close|closed|fixes|fix|fixed|resolves|resolve|resolved|"
    r"fecha|fechando|corrige)\s+"
    r"(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(?P<number>\d+)",
    re.IGNORECASE,
)
BLOCKED_BY_RE = re.compile(
    r"\b(blocked by|depends on|bloqueado por|depende de)\s+"
    r"(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(?P<number>\d+)",
    re.IGNORECASE,
)
ISSUE_NUMBER_RE = re.compile(r"/issues/(\d+)/?$")
PULL_NUMBER_RE = re.compile(r"/pulls/(\d+)/?$")
NEXT_CURSOR_KEYS = (
    "commits",
    "issues",
    "pulls",
    "pull_comments",
    "issue_comments",
)
RelationshipKey = tuple[str, str, str]


def _headers(token: str) -> dict[str, str]:
    headers = dict(GITHUB_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _paginated_get(
    token: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    url = f"{GITHUB_API}{path}"
    current_params = dict(params or {})
    current_params.setdefault("per_page", 100)
    while url:
        response = requests.get(
            url,
            headers=_headers(token),
            params=current_params,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("A resposta paginada do GitHub deve ser uma lista.")
        yield from payload
        url = response.links.get("next", {}).get("url", "")
        current_params = {}


def _github_get(token: str, path: str) -> dict[str, Any]:
    response = requests.get(
        f"{GITHUB_API}{path}",
        headers=_headers(token),
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("A resposta detalhada do GitHub deve ser um objeto.")
    return payload


def _parse_datetime(value: str | None) -> dt.datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Datas do GitHub devem estar em formato ISO 8601.")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Datas do GitHub devem incluir fuso horário.")
    return parsed.astimezone(dt.timezone.utc)


def _iso_utc(value: dt.datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("O cursor do GitHub deve incluir fuso horário.")
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _incremental_since(
    cursor: dict[str, Any],
    key: str,
    initial_since: str,
) -> str:
    value = cursor.get(key, initial_since)
    if not isinstance(value, str) or _parse_datetime(value) is None:
        raise ValueError(f"Cursor incremental inválido para {key}.")
    return value


def fetch_github_repo(
    token: str,
    full_name: str,
    cursor: dict[str, Any] | None = None,
    history_days: int = 90,
    now: dt.datetime | None = None,
    max_commit_details: int = 1000,
) -> tuple[dict[str, Any], dict[str, str]]:
    if full_name.count("/") != 1 or any(
        not part for part in full_name.split("/", 1)
    ):
        raise ValueError("Repositório deve estar no formato owner/repo.")
    if (
        not isinstance(history_days, int)
        or isinstance(history_days, bool)
        or history_days < 1
    ):
        raise ValueError("history_days deve ser positivo.")
    if (
        not isinstance(max_commit_details, int)
        or isinstance(max_commit_details, bool)
        or max_commit_details < 0
    ):
        raise ValueError("max_commit_details não pode ser negativo.")

    sync_started_at = now or dt.datetime.now(dt.timezone.utc)
    sync_cursor = _iso_utc(sync_started_at)
    initial_since = _iso_utc(
        sync_started_at - dt.timedelta(days=history_days)
    )
    if cursor is not None and not isinstance(cursor, dict):
        raise ValueError("O cursor do GitHub deve ser um objeto.")
    previous_cursor = cursor or {}
    repository_path = f"/repos/{quote(full_name, safe='/')}"

    commits = list(
        _paginated_get(
            token,
            f"{repository_path}/commits",
            {"since": _incremental_since(previous_cursor, "commits", initial_since)},
        )
    )
    commit_details = [
        _github_get(
            token,
            f"{repository_path}/commits/{quote(commit['sha'], safe='')}",
        )
        for commit in commits[:max_commit_details]
    ]
    issues = list(
        _paginated_get(
            token,
            f"{repository_path}/issues",
            {
                "state": "all",
                "since": _incremental_since(previous_cursor, "issues", initial_since),
            },
        )
    )

    pull_since = _parse_datetime(
        _incremental_since(previous_cursor, "pulls", initial_since)
    )
    pulls: list[dict[str, Any]] = []
    for pull in _paginated_get(
        token,
        f"{repository_path}/pulls",
        {"state": "all", "sort": "updated", "direction": "desc"},
    ):
        updated_at = _parse_datetime(pull.get("updated_at"))
        if updated_at is None:
            raise ValueError("A resposta do GitHub não contém updated_at na PR.")
        if pull_since is not None and updated_at < pull_since:
            break
        pulls.append(pull)

    pull_details: list[dict[str, Any]] = []
    reviews: list[list[dict[str, Any]]] = []
    for pull in pulls:
        number = pull["number"]
        pull_details.append(
            _github_get(token, f"{repository_path}/pulls/{number}")
        )
        reviews.append(
            list(
                _paginated_get(
                    token,
                    f"{repository_path}/pulls/{number}/reviews",
                )
            )
        )

    pull_comments = list(
        _paginated_get(
            token,
            f"{repository_path}/pulls/comments",
            {
                "since": _incremental_since(
                    previous_cursor, "pull_comments", initial_since
                )
            },
        )
    )
    issue_comments = list(
        _paginated_get(
            token,
            f"{repository_path}/issues/comments",
            {
                "since": _incremental_since(
                    previous_cursor, "issue_comments", initial_since
                )
            },
        )
    )
    payload = {
        "commits": commits,
        "commit_details": commit_details,
        "issues": issues,
        "pulls": pulls,
        "pull_details": pull_details,
        "reviews": reviews,
        "pull_comments": pull_comments,
        "issue_comments": issue_comments,
    }
    next_cursor = {key: sync_cursor for key in NEXT_CURSOR_KEYS}
    return payload, next_cursor


def _add_node(
    nodes: dict[str, dict[str, dict[str, Any]]],
    project_id: str,
    label: str,
    kind: str,
    provider: str,
    external_id: str,
    properties: dict[str, Any],
) -> str:
    uid = make_uid(project_id, kind, provider, external_id)
    row = {
        "uid": uid,
        "project_id": project_id,
        **properties,
    }
    nodes.setdefault(label, {})[uid] = row
    return uid


def _add_relationship(
    relationships: dict[RelationshipKey, dict[tuple[str, str], dict[str, Any]]],
    relationship: RelationshipKey,
    source_uid: str,
    target_uid: str,
    properties: dict[str, Any] | None = None,
) -> None:
    relationships.setdefault(relationship, {})[(source_uid, target_uid)] = {
        "source_uid": source_uid,
        "target_uid": target_uid,
        "properties": properties or {},
    }


def _account_node(
    nodes: dict[str, dict[str, dict[str, Any]]],
    project_id: str,
    user: dict[str, Any] | None,
    provider: str = "github",
) -> str | None:
    if user is None:
        return None
    login = user.get("login")
    if not isinstance(login, str) or not login:
        return None
    is_bot = user.get("type") == "Bot" or login.casefold().endswith("[bot]")
    return _add_node(
        nodes,
        project_id,
        "Account",
        "account",
        provider,
        login.casefold(),
        {
            "provider": provider,
            "login": login,
            "display_name": user.get("name") or login,
            "avatar_url": user.get("avatar_url"),
            "is_bot": is_bot,
            "linked": True,
        },
    )


def _git_author_node(
    nodes: dict[str, dict[str, dict[str, Any]]],
    project_id: str,
    author: dict[str, Any] | None,
) -> str | None:
    if author is None:
        return None
    name = author.get("name")
    email = author.get("email")
    if not isinstance(name, str) or not name:
        return None
    email_hash = (
        hashlib.sha256(email.strip().casefold().encode("utf-8")).hexdigest()
        if isinstance(email, str) and email.strip()
        else None
    )
    external_id = email_hash or name.casefold()
    return _add_node(
        nodes,
        project_id,
        "Account",
        "account",
        "git",
        external_id,
        {
            "provider": "git",
            "login": name,
            "display_name": name,
            "avatar_url": None,
            "is_bot": False,
            "linked": False,
            "email_hash": email_hash,
        },
    )


def _account_relation(
    relationships: dict[RelationshipKey, dict[tuple[str, str], dict[str, Any]]],
    account_uid: str | None,
    relation: str,
    target_label: str,
    target_uid: str,
) -> None:
    if account_uid is not None:
        _add_relationship(
            relationships,
            ("Account", relation, target_label),
            account_uid,
            target_uid,
        )


def _category_for_issue(issue: dict[str, Any]) -> str:
    if issue.get("state") == "open":
        return "todo"
    if issue.get("state") == "closed":
        return "ignored" if issue.get("state_reason") == "not_planned" else "done"
    raise ValueError(f"Estado de issue não suportado: {issue.get('state')!r}")


def _target_issue_url(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    match = ISSUE_NUMBER_RE.search(parts.path)
    if match is None:
        raise ValueError("URL de comentário GitHub não aponta para uma issue.")
    repo_match = re.search(r"/repos/([^/]+/[^/]+)/issues/", parts.path)
    if repo_match is None:
        raise ValueError("URL de comentário GitHub não contém owner/repo.")
    return repo_match.group(1), int(match.group(1))


def _target_pull_url(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    match = PULL_NUMBER_RE.search(parts.path)
    if match is None:
        raise ValueError("URL de comentário GitHub não aponta para uma PR.")
    repo_match = re.search(r"/repos/([^/]+/[^/]+)/pulls/", parts.path)
    if repo_match is None:
        raise ValueError("URL de comentário GitHub não contém owner/repo.")
    return repo_match.group(1), int(match.group(1))


def _reference_uid(
    project_id: str,
    repository: str,
    match: re.Match[str],
) -> str:
    target_repo = match.group("repo") or repository
    return make_uid(
        project_id,
        "task",
        "github",
        f"{target_repo}#{match.group('number')}",
    )


def _module_path(filename: str, module_depth: int) -> str:
    parts = filename.replace("\\", "/").split("/")[:-1]
    return "/".join(parts[:module_depth]) if parts else "."


def _is_ignored(filename: str, patterns: Iterable[str]) -> bool:
    normalized = filename.replace("\\", "/")
    return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in patterns)


def build_github_graph(
    project_id: str,
    full_name: str,
    payload: dict[str, Any],
    settings: dict[str, Any] | None = None,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[RelationshipKey, list[dict[str, Any]]],
]:
    options = settings or {}
    module_depth = options.get("module_depth", 1)
    max_commit_details = options.get("max_commit_details", 1000)
    ignore_globs = options.get("ignore_globs", DEFAULT_IGNORE_GLOBS)
    if (
        not isinstance(module_depth, int)
        or isinstance(module_depth, bool)
        or module_depth < 1
    ):
        raise ValueError("module_depth deve ser um inteiro positivo.")
    if (
        not isinstance(max_commit_details, int)
        or isinstance(max_commit_details, bool)
        or max_commit_details < 0
    ):
        raise ValueError("max_commit_details deve ser um inteiro não negativo.")
    if not isinstance(ignore_globs, (list, tuple)) or not all(
        isinstance(pattern, str) for pattern in ignore_globs
    ):
        raise ValueError("ignore_globs deve ser uma lista de padrões de texto.")

    nodes: dict[str, dict[str, dict[str, Any]]] = {}
    relationships: dict[
        RelationshipKey, dict[tuple[str, str], dict[str, Any]]
    ] = {}
    repo_uid = _add_node(
        nodes,
        project_id,
        "Repo",
        "repo",
        "github",
        full_name,
        {
            "full_name": full_name,
            "url": f"https://github.com/{full_name}",
        },
    )

    commit_details = {
        detail["sha"]: detail
        for detail in payload["commit_details"][:max_commit_details]
    }
    for commit in payload["commits"]:
        details = commit_details.get(commit["sha"], {})
        git_commit = commit["commit"]
        author_data = git_commit.get("author")
        authored_at = _parse_datetime(
            author_data.get("date") if isinstance(author_data, dict) else None
        )
        if authored_at is None:
            raise ValueError("O commit não contém a data de autoria.")
        message = git_commit.get("message")
        if not isinstance(message, str):
            raise ValueError("O commit não contém uma mensagem válida.")
        first_line = message.splitlines()[0][:200]
        files = details.get("files")
        commit_uid = _add_node(
            nodes,
            project_id,
            "Commit",
            "commit",
            "github",
            commit["sha"],
            {
                "sha": commit["sha"],
                "message": first_line,
                "authored_at": authored_at,
                "additions": details.get("stats", {}).get("additions"),
                "deletions": details.get("stats", {}).get("deletions"),
                "files_changed": len(files) if isinstance(files, list) else None,
                "url": commit.get("html_url"),
            },
        )
        github_account_uid = _account_node(nodes, project_id, commit.get("author"))
        git_account_uid = (
            _git_author_node(
                nodes,
                project_id,
                author_data if isinstance(author_data, dict) else None,
            )
            if github_account_uid is None
            else None
        )
        _account_relation(
            relationships,
            github_account_uid or git_account_uid,
            "REALIZOU",
            "Commit",
            commit_uid,
        )
        _add_relationship(
            relationships,
            ("Commit", "NO_REPOSITORIO", "Repo"),
            commit_uid,
            repo_uid,
        )

        parents = commit.get("parents", [])
        if len(parents) > 1:
            continue
        for changed_file in files or []:
            filename = changed_file.get("filename")
            if not isinstance(filename, str) or _is_ignored(filename, ignore_globs):
                continue
            module_path = _module_path(filename, module_depth)
            module_uid = _add_node(
                nodes,
                project_id,
                "Module",
                "module",
                "github",
                f"{full_name}#{module_path}",
                {"repo_full_name": full_name, "path": module_path},
            )
            _add_relationship(
                relationships,
                ("Commit", "ALTEROU", "Module"),
                commit_uid,
                module_uid,
                {
                    "additions": changed_file.get("additions", 0),
                    "deletions": changed_file.get("deletions", 0),
                },
            )
            _add_relationship(
                relationships,
                ("Module", "NO_REPOSITORIO", "Repo"),
                module_uid,
                repo_uid,
            )

    for issue in payload["issues"]:
        if "pull_request" in issue:
            continue
        status_category = _category_for_issue(issue)
        task_external_id = f"{full_name}#{issue['number']}"
        task_uid = _add_node(
            nodes,
            project_id,
            "Task",
            "task",
            "github",
            task_external_id,
            {
                "kind": "issue",
                "provider": "github",
                "title": issue["title"],
                "status_category": status_category,
                "created_at": _parse_datetime(issue["created_at"]),
                "updated_at": _parse_datetime(issue["updated_at"]),
                "due_at": None,
                "done_at": (
                    _parse_datetime(issue.get("closed_at"))
                    if status_category == "done"
                    else None
                ),
                "started_at": None,
                "blocked": False,
                "labels": [label["name"] for label in issue.get("labels", [])],
                "transitions_json": "[]",
                "url": issue.get("html_url"),
            },
        )
        _add_relationship(
            relationships,
            ("Task", "NO_REPOSITORIO", "Repo"),
            task_uid,
            repo_uid,
        )
        creator_uid = _account_node(nodes, project_id, issue.get("user"))
        _account_relation(
            relationships, creator_uid, "CRIOU", "Task", task_uid
        )
        for assignee in issue.get("assignees", []):
            assignee_uid = _account_node(nodes, project_id, assignee)
            _account_relation(
                relationships,
                assignee_uid,
                "RESPONSAVEL_POR",
                "Task",
                task_uid,
            )
        body = issue.get("body") or ""
        for match in BLOCKED_BY_RE.finditer(body):
            _add_relationship(
                relationships,
                ("Task", "BLOQUEADA_POR", "Task"),
                task_uid,
                _reference_uid(project_id, full_name, match),
                {"via": "text"},
            )

    pull_details = payload["pull_details"]
    review_batches = payload["reviews"]
    pull_numbers = {pull["number"] for pull in payload["pulls"]}
    pull_uids: dict[int, str] = {}
    first_reviews: dict[int, dt.datetime] = {}
    for index, pull in enumerate(pull_details):
        pull_list_data = next(
            (item for item in payload["pulls"] if item["number"] == pull["number"]),
            pull,
        )
        merged_at = _parse_datetime(pull.get("merged_at"))
        if merged_at is not None:
            state = "merged"
        elif pull.get("state") in {"open", "closed"}:
            state = pull["state"]
        else:
            raise ValueError(f"Estado de PR não suportado: {pull.get('state')!r}")

        reviews = review_batches[index] if index < len(review_batches) else []
        pull_author = pull_list_data.get("user") or pull.get("user")
        pull_author_login = (
            pull_author.get("login", "").casefold()
            if isinstance(pull_author, dict)
            else None
        )
        for review in reviews:
            review_state = review.get("state")
            if review_state not in REVIEW_STATES:
                raise ValueError(f"Estado de review não suportado: {review_state!r}")
            submitted_at = _parse_datetime(review.get("submitted_at"))
            reviewer = review.get("user")
            if (
                submitted_at is not None
                and isinstance(reviewer, dict)
                and reviewer.get("login", "").casefold() != pull_author_login
            ):
                current = first_reviews.get(pull["number"])
                if current is None or submitted_at < current:
                    first_reviews[pull["number"]] = submitted_at

        pull_uid = _add_node(
            nodes,
            project_id,
            "PullRequest",
            "pull_request",
            "github",
            f"{full_name}#{pull['number']}",
            {
                "number": pull["number"],
                "title": pull["title"],
                "state": state,
                "created_at": _parse_datetime(pull["created_at"]),
                "closed_at": _parse_datetime(pull.get("closed_at")),
                "merged_at": merged_at,
                "additions": pull.get("additions"),
                "deletions": pull.get("deletions"),
                "changed_files": pull.get("changed_files"),
                "first_review_at": None,
                "url": pull.get("html_url"),
            },
        )
        pull_uids[pull["number"]] = pull_uid
        author_uid = _account_node(nodes, project_id, pull_author)
        _account_relation(
            relationships, author_uid, "ABRIU", "PullRequest", pull_uid
        )
        merged_by_uid = _account_node(nodes, project_id, pull.get("merged_by"))
        _account_relation(
            relationships, merged_by_uid, "MESCLOU", "PullRequest", pull_uid
        )
        _add_relationship(
            relationships,
            ("PullRequest", "NO_REPOSITORIO", "Repo"),
            pull_uid,
            repo_uid,
        )

        for review in reviews:
            review_uid = _add_node(
                nodes,
                project_id,
                "Review",
                "review",
                "github",
                f"{full_name}#{pull['number']}#{review['id']}",
                {
                    "state": review["state"],
                    "submitted_at": _parse_datetime(review.get("submitted_at")),
                },
            )
            reviewer_uid = _account_node(nodes, project_id, review.get("user"))
            _account_relation(
                relationships, reviewer_uid, "ENVIOU", "Review", review_uid
            )
            _add_relationship(
                relationships,
                ("Review", "SOBRE", "PullRequest"),
                review_uid,
                pull_uid,
            )

    for pull_number, reviewed_at in first_reviews.items():
        pull_uid = pull_uids[pull_number]
        nodes["PullRequest"][pull_uid]["first_review_at"] = reviewed_at

    for comment in payload["pull_comments"]:
        target_repo, pull_number = _target_pull_url(comment["pull_request_url"])
        if target_repo.casefold() != full_name.casefold():
            raise ValueError("Comentário inline referencia outro repositório.")
        pull_uid = pull_uids.get(pull_number)
        if pull_uid is None:
            raise ValueError("A PR do comentário inline não foi incluída na coleta.")
        _add_comment(
            nodes,
            relationships,
            project_id,
            full_name,
            comment,
            pull_uid,
            "PullRequest",
            "pull",
        )

    for comment in payload["issue_comments"]:
        target_repo, issue_number = _target_issue_url(comment["issue_url"])
        if target_repo.casefold() != full_name.casefold():
            raise ValueError("Comentário de conversa referencia outro repositório.")
        if issue_number in pull_numbers:
            target_uid = pull_uids.get(issue_number)
            target_label = "PullRequest"
        else:
            target_uid = make_uid(
                project_id,
                "task",
                "github",
                f"{target_repo}#{issue_number}",
            )
            target_label = "Task"
        if target_uid is None:
            raise ValueError("O alvo do comentário não foi incluído na coleta.")
        _add_comment(
            nodes,
            relationships,
            project_id,
            full_name,
            comment,
            target_uid,
            target_label,
            "issue",
        )

    for pull in pull_details:
        body = pull.get("body") or ""
        pull_uid = pull_uids[pull["number"]]
        for match in CLOSES_RE.finditer(body):
            _add_relationship(
                relationships,
                ("PullRequest", "FECHA", "Task"),
                pull_uid,
                _reference_uid(project_id, full_name, match),
                {"via": "text"},
            )

    node_rows = {
        label: list(rows.values())
        for label, rows in nodes.items()
    }
    relationship_rows = {
        relation: list(rows.values())
        for relation, rows in relationships.items()
    }
    return node_rows, relationship_rows


def _add_comment(
    nodes: dict[str, dict[str, dict[str, Any]]],
    relationships: dict[RelationshipKey, dict[tuple[str, str], dict[str, Any]]],
    project_id: str,
    full_name: str,
    comment: dict[str, Any],
    target_uid: str,
    target_label: str,
    external_kind: str,
) -> None:
    body = comment.get("body")
    if not isinstance(body, str):
        raise ValueError("O comentário GitHub não contém um corpo textual.")
    comment_uid = _add_node(
        nodes,
        project_id,
        "Comment",
        "comment",
        "github",
        f"{full_name}#{external_kind}-{comment['id']}",
        {
            "created_at": _parse_datetime(comment["created_at"]),
            "length": len(body),
        },
    )
    _add_relationship(
        relationships,
        ("Comment", "SOBRE", target_label),
        comment_uid,
        target_uid,
    )
    author_uid = _account_node(nodes, project_id, comment.get("user"))
    _account_relation(
        relationships, author_uid, "COMENTOU", "Comment", comment_uid
    )


def write_github_graph(
    project_id: str,
    nodes: dict[str, list[dict[str, Any]]],
    relationships: dict[RelationshipKey, list[dict[str, Any]]],
    writer: Neo4jV2Writer,
) -> dict[str, Any]:
    node_counts: dict[str, int] = {}
    for label, rows in nodes.items():
        node_counts[label] = writer.upsert_nodes(project_id, label, rows)

    relationship_counts: dict[str, int] = {}
    unresolved_relationships = 0
    for (source_label, relationship, target_label), rows in relationships.items():
        key = f"{source_label}:{relationship}:{target_label}"
        if relationship in OPTIONAL_REFERENCE_RELATIONSHIPS:
            written, skipped = writer.upsert_relationships_if_present(
                project_id,
                source_label,
                relationship,
                target_label,
                rows,
            )
            unresolved_relationships += skipped
            relationship_counts[key] = written
        else:
            relationship_counts[key] = writer.upsert_relationships(
                project_id,
                source_label,
                relationship,
                target_label,
                rows,
            )
    return {
        "nodes": node_counts,
        "relationships": relationship_counts,
        "unresolved_relationships": unresolved_relationships,
    }


def sync_github_project(
    session: Session,
    user_id: str,
    project_id: str,
    writer: Neo4jV2Writer,
    now: dt.datetime | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    project = repository.get_project_for_user(session, project_id, user_id)
    sources = session.scalars(
        select(ProjectSource).where(
            ProjectSource.project_id == project.id,
            ProjectSource.provider == "github",
            ProjectSource.enabled.is_(True),
        )
    ).all()
    if not sources:
        return {"completed": [], "errors": []}

    token = repository.get_provider_token(session, user_id, "github")
    if not token:
        raise HTTPException(400, "GitHub não conectado")

    completed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    total = len(sources)
    for index, source in enumerate(sources, start=1):
        try:
            settings = project.settings_json or {}
            if not isinstance(settings, dict):
                raise ValueError("As configurações do projeto devem ser um objeto.")
            max_commit_details = settings.get("max_commit_details", 1000)
            payload, next_cursor = fetch_github_repo(
                token,
                source.external_id,
                source.cursor_json,
                project.history_days,
                now,
                max_commit_details,
            )
            nodes, relationships = build_github_graph(
                project.id,
                source.external_id,
                payload,
                settings,
            )
            counts = write_github_graph(project.id, nodes, relationships, writer)
            source.cursor_json = next_cursor
            session.commit()
        except (
            requests.RequestException,
            Neo4jError,
            SQLAlchemyError,
            ValueError,
            KeyError,
            TypeError,
        ) as error:
            session.rollback()
            if (
                isinstance(error, requests.HTTPError)
                and error.response is not None
                and error.response.status_code == 401
            ):
                connection = session.scalar(
                    select(ProviderConnection).where(
                        ProviderConnection.user_id == user_id,
                        ProviderConnection.provider == "github",
                    )
                )
                if connection is not None:
                    connection.status = "needs_reconnect"
                    session.commit()
            errors.append(
                {
                    "source_id": source.external_id,
                    "code": type(error).__name__,
                    "message": "Não foi possível sincronizar este repositório GitHub.",
                }
            )
            if progress_callback is not None:
                progress_callback(
                    index,
                    total,
                    "Falha ao sincronizar um repositório GitHub.",
                )
            continue

        completed.append(
            {
                "repository": source.external_id,
                "counts": counts,
            }
        )
        if progress_callback is not None:
            progress_callback(index, total, "Repositório GitHub sincronizado.")
    return {"completed": completed, "errors": errors}
