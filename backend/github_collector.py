"""
Coletor de dados do GitHub — versão multiusuário.

Diferença pro protótipo anterior: em vez de ler um GITHUB_TOKEN fixo
do .env, toda função recebe o `token` do usuário logado (obtido via
OAuth e descriptografado na hora do /sync). Isso significa que cada
usuário só coleta os repos aos quais ELE tem acesso.

IDs usados no grafo:
  - Task (issue):  "gh-{owner}/{repo}#{number}"
  - PullRequest:   "gh-{owner}/{repo}#{number}"
"""
from __future__ import annotations

import re
from typing import Iterator

import requests

from neo4j_writer import Neo4jWriter

GITHUB_API = "https://api.github.com"
CLOSES_RE = re.compile(r"\b(closes|close|closed|fixes|fix|fixed|resolves|resolve|resolved)\s+#(\d+)", re.I)


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _paginated_get(token: str, url: str, params: dict | None = None) -> Iterator[dict]:
    params = dict(params or {})
    params.setdefault("per_page", 100)
    while url:
        resp = requests.get(url, headers=_headers(token), params=params, timeout=30)
        resp.raise_for_status()
        yield from resp.json()
        params = None
        url = resp.links.get("next", {}).get("url")


def get_authenticated_username(token: str) -> str:
    resp = requests.get(f"{GITHUB_API}/user", headers=_headers(token), timeout=15)
    resp.raise_for_status()
    return resp.json()["login"]


def fetch_user_repos(token: str) -> list[dict]:
    """Repos que o usuário logado pode ver — pra ele escolher quais sincronizar na UI."""
    repos = list(_paginated_get(token, f"{GITHUB_API}/user/repos", params={"affiliation": "owner,collaborator,organization_member"}))
    return [{"full_name": r["full_name"], "private": r["private"]} for r in repos]


def collect_repo(token: str, full_name: str, writer: Neo4jWriter) -> None:
    print(f"[github] coletando {full_name}...")
    writer.upsert_repository(full_name)
    _collect_commits(token, full_name, writer)
    _collect_issues(token, full_name, writer)
    _collect_pull_requests(token, full_name, writer)


def _collect_commits(token: str, full_name: str, writer: Neo4jWriter) -> None:
    url = f"{GITHUB_API}/repos/{full_name}/commits"
    count = 0
    for c in _paginated_get(token, url):
        author = c.get("author")
        username = author["login"] if author else None
        if username:
            writer.upsert_developer(username=username, source="github")
        writer.upsert_commit(
            sha=c["sha"], message=c["commit"]["message"].split("\n")[0][:200],
            date=c["commit"]["author"]["date"], url=c["html_url"],
            author_username=username, repo_full_name=full_name,
        )
        count += 1
    print(f"[github]   {count} commits")


def _collect_issues(token: str, full_name: str, writer: Neo4jWriter) -> None:
    url = f"{GITHUB_API}/repos/{full_name}/issues"
    count = 0
    for issue in _paginated_get(token, url, params={"state": "all"}):
        if "pull_request" in issue:
            continue
        task_id = f"gh-{full_name}#{issue['number']}"
        assignee = issue.get("assignee")
        assignee_username = assignee["login"] if assignee else None
        if assignee_username:
            writer.upsert_developer(username=assignee_username, source="github")
        writer.upsert_task(
            task_id=task_id, title=issue["title"], status=issue["state"],
            url=issue["html_url"], source="github", assignee_username=assignee_username,
        )
        count += 1
    print(f"[github]   {count} issues")


def _collect_pull_requests(token: str, full_name: str, writer: Neo4jWriter) -> None:
    url = f"{GITHUB_API}/repos/{full_name}/pulls"
    count = 0
    for pr in _paginated_get(token, url, params={"state": "all"}):
        pr_id = f"gh-{full_name}#{pr['number']}"
        author_username = pr["user"]["login"] if pr.get("user") else None
        if author_username:
            writer.upsert_developer(username=author_username, source="github")

        writer.upsert_pull_request(
            pr_id=pr_id, number=pr["number"], title=pr["title"], state=pr["state"],
            created_at=pr["created_at"], merged_at=pr.get("merged_at"), url=pr["html_url"],
            author_username=author_username, repo_full_name=full_name,
        )

        for match in CLOSES_RE.finditer(pr.get("body") or ""):
            writer.link_pr_closes_task(pr_id=pr_id, task_id=f"gh-{full_name}#{match.group(2)}")

        _collect_reviews(token, full_name, pr["number"], pr_id, writer)
        count += 1
    print(f"[github]   {count} pull requests")


def _collect_reviews(token: str, full_name: str, pr_number: int, pr_id: str, writer: Neo4jWriter) -> None:
    url = f"{GITHUB_API}/repos/{full_name}/pulls/{pr_number}/reviews"
    for review in _paginated_get(token, url):
        reviewer = review.get("user")
        if not reviewer:
            continue
        writer.upsert_developer(username=reviewer["login"], source="github")
        writer.upsert_review(
            reviewer_username=reviewer["login"], pr_id=pr_id,
            state=review["state"], submitted_at=review.get("submitted_at"),
        )
