from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


GITHUB_API = "https://api.github.com"
FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PRIVATE_TEXT_FIELDS = {
    "bio",
    "body",
    "blog",
    "company",
    "description",
    "diff_hunk",
    "location",
    "message",
    "name",
    "patch",
    "title",
}
PRIVATE_URL_FIELDS = {"avatar_url", "avatarurl", "html_url", "url"}


def redact_payload(value: Any, token: str, users: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [redact_payload(item, token, users) for item in value]
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized_key = key.lower()
            if normalized_key == "email":
                redacted[key] = None
            elif normalized_key in PRIVATE_TEXT_FIELDS and isinstance(item, str):
                redacted[key] = "[redacted]"
            elif (
                normalized_key in PRIVATE_URL_FIELDS or normalized_key.endswith("_url")
            ) and isinstance(item, str):
                redacted[key] = "https://example.invalid/redacted"
            elif normalized_key in {"login", "username", "fullname"} and isinstance(item, str):
                redacted[key] = users.setdefault(item, f"user-{chr(97 + len(users))}")
            else:
                redacted[key] = redact_payload(item, token, users)
        return redacted
    if isinstance(value, str):
        redacted = value.replace(token, "[redacted-token]") if token else value
        return EMAIL_RE.sub("[redacted-email]", redacted)
    return value


def _github_get(token: str, path: str, **params: Any) -> Any:
    if not token:
        response = requests.get(
            f"{GITHUB_API}{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    response = requests.get(
        f"{GITHUB_API}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def capture_github(token: str, repository: str) -> dict[str, Any]:
    encoded_repository = quote(repository, safe="/")
    commits = _github_get(token, f"/repos/{encoded_repository}/commits", per_page=5)
    issues = _github_get(
        token, f"/repos/{encoded_repository}/issues", state="all", per_page=5
    )
    pulls = _github_get(
        token,
        f"/repos/{encoded_repository}/pulls",
        state="all",
        sort="updated",
        direction="desc",
        per_page=5,
    )

    commit_details = []
    if commits:
        commit_details.append(
            _github_get(
                token,
                f"/repos/{encoded_repository}/commits/{quote(commits[0]['sha'], safe='')}",
            )
        )

    pull_details = []
    reviews = []
    for pull in pulls[:3]:
        number = pull["number"]
        pull_details.append(
            _github_get(token, f"/repos/{encoded_repository}/pulls/{number}")
        )
        reviews.append(
            _github_get(
                token,
                f"/repos/{encoded_repository}/pulls/{number}/reviews",
                per_page=5,
            )
        )

    inline_comments = _github_get(
        token, f"/repos/{encoded_repository}/pulls/comments", per_page=5
    )
    issue_comments = _github_get(
        token, f"/repos/{encoded_repository}/issues/comments", per_page=5
    )

    payload = {
        "commits": commits,
        "commit_details": commit_details,
        "issues": issues,
        "pulls": pulls,
        "pull_details": pull_details,
        "reviews": reviews,
        "pull_comments": inline_comments,
        "issue_comments": issue_comments,
    }
    return redact_payload(payload, token, {})


def capture_trello(token: str, board_id: str) -> dict[str, Any]:
    backend_root = str(Path(__file__).resolve().parents[1] / "backend")
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    from app.trello_collector import _get

    board_path = f"/boards/{quote(board_id, safe='')}"
    payload = {
        "board": _get(token, board_path, fields="name,url,shortLink"),
        "members": _get(
            token,
            f"{board_path}/members",
            fields="username,fullName,avatarUrl",
        ),
        "lists": _get(
            token,
            f"{board_path}/lists",
            fields="name,closed,pos",
        ),
        "cards": _get(
            token,
            f"{board_path}/cards",
            filter="all",
            fields="name,idList,idMembers,url,shortLink,closed,due,dueComplete,dateLastActivity,idLabels",
            members="true",
            member_fields="username",
        ),
    }
    return redact_payload(payload, token, {})


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Defina a variável de ambiente {name}.")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Captura amostras reais das APIs e grava fixtures redigidas."
    )
    parser.add_argument("--github-repo", help="Repositório no formato owner/repo.")
    parser.add_argument("--trello-board-id", help="ID do board do Trello.")
    args = parser.parse_args()

    if not args.github_repo and not args.trello_board_id:
        parser.error("Informe --github-repo e/ou --trello-board-id.")

    captures = []
    if args.github_repo:
        if not re.fullmatch(r"[^/\s]+/[^/\s]+", args.github_repo):
            parser.error("--github-repo deve usar o formato owner/repo.")
        token = os.environ.get("COGNIS_FIXTURE_GITHUB_TOKEN", "").strip()
        payload = capture_github(token, args.github_repo)
        destination = FIXTURE_ROOT / "github" / "capture.json"
        _write_fixture(destination, payload)
        captures.append(destination)

    if args.trello_board_id:
        token = _required_environment("COGNIS_FIXTURE_TRELLO_TOKEN")
        payload = capture_trello(token, args.trello_board_id)
        destination = FIXTURE_ROOT / "trello" / "capture.json"
        _write_fixture(destination, payload)
        captures.append(destination)

    for destination in captures:
        print(f"Fixture redigida salva em {destination}")


def _write_fixture(destination: Path, payload: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
