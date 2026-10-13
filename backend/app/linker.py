from __future__ import annotations

import re
from typing import Any

from neo4j import Driver

from .neo4j_v2_writer import make_uid

TRELLO_SHORTLINK_RE = re.compile(r"trello\.com/c/([A-Za-z0-9]{8})", re.IGNORECASE)
GITHUB_ATTACHMENT_RE = re.compile(
    r"https?://(?:www\.)?github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/(?P<kind>pull|issues)/(?P<number>\d+)",
    re.IGNORECASE,
)
CLOSES_RE = re.compile(
    r"\b(closes|close|closed|fixes|fix|fixed|resolves|resolve|resolved|"
    r"fecha|fechando|corrige)\s+"
    r"(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(?P<number>\d+)",
    re.IGNORECASE,
)


def extract_shortlink(text: str) -> str | None:
    """Extrai o shortLink de 8 caracteres do Trello a partir de um texto ou URL."""
    match = TRELLO_SHORTLINK_RE.search(text)
    return match.group(1) if match else None


def parse_trello_attachments(
    cards: list[dict[str, Any]],
    project_id: str,
) -> list[dict[str, Any]]:
    """
    Analisa anexos de cards do Trello para identificar links apontando para PRs ou Issues no GitHub.
    Retorna linhas de relacionamento (:Task)-[:RELACIONADA_A {via: 'attachment', confidence: 1.0}]->(:PullRequest|:Task).
    """
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for card in cards:
        card_id = card.get("id")
        if not card_id:
            continue
        source_uid = make_uid(project_id, "task", "trello", card_id)

        attachments = card.get("attachments") or []
        for att in attachments:
            url = att.get("url") if isinstance(att, dict) else ""
            if not url or not isinstance(url, str):
                continue

            match = GITHUB_ATTACHMENT_RE.search(url)
            if not match:
                continue

            owner = match.group("owner")
            repo = match.group("repo")
            kind = match.group("kind").lower()
            number = match.group("number")
            ref = f"{owner}/{repo}#{number}"

            if kind == "pull":
                target_uid = make_uid(project_id, "pull_request", "github", ref)
                target_label = "PullRequest"
            else:
                target_uid = make_uid(project_id, "task", "github", ref)
                target_label = "Task"

            key = (source_uid, target_uid)
            if key in seen:
                continue
            seen.add(key)

            links.append(
                {
                    "source_uid": source_uid,
                    "target_uid": target_uid,
                    "source_label": "Task",
                    "target_label": target_label,
                    "relationship_type": "RELACIONADA_A",
                    "properties": {
                        "via": "attachment",
                        "confidence": 1.0,
                    },
                }
            )

    return links


def parse_shortlinks_in_github(
    pulls: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    trello_cards_by_shortlink: dict[str, str],
    project_id: str,
    default_repo: str = "",
) -> list[dict[str, Any]]:
    """
    Identifica menções a 'trello.com/c/<shortLink>' em títulos, corpos ou branches do GitHub.
    Retorna linhas de relacionamento (:Task)-[:RELACIONADA_A {via: 'text', confidence: 1.0}]->(:PullRequest|:Task).
    """
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for pull in pulls:
        pull_number = pull.get("number")
        if not pull_number:
            continue
        repo = pull.get("repo") or default_repo
        if not repo:
            continue
        pull_uid = make_uid(project_id, "pull_request", "github", f"{repo}#{pull_number}")

        texts_to_search = [
            pull.get("title") or "",
            pull.get("body") or "",
        ]
        head = pull.get("head")
        if isinstance(head, dict) and head.get("ref"):
            texts_to_search.append(head["ref"])

        for text in texts_to_search:
            for match in TRELLO_SHORTLINK_RE.finditer(text):
                shortlink = match.group(1)
                card_id = trello_cards_by_shortlink.get(shortlink)
                if not card_id:
                    continue
                source_uid = make_uid(project_id, "task", "trello", card_id)
                key = (source_uid, pull_uid)
                if key in seen:
                    continue
                seen.add(key)

                links.append(
                    {
                        "source_uid": source_uid,
                        "target_uid": pull_uid,
                        "source_label": "Task",
                        "target_label": "PullRequest",
                        "relationship_type": "RELACIONADA_A",
                        "properties": {
                            "via": "text",
                            "confidence": 1.0,
                        },
                    }
                )

    for issue in issues:
        if "pull_request" in issue:
            continue
        issue_number = issue.get("number")
        if not issue_number:
            continue
        repo = issue.get("repo") or default_repo
        if not repo:
            continue
        issue_uid = make_uid(project_id, "task", "github", f"{repo}#{issue_number}")

        texts_to_search = [
            issue.get("title") or "",
            issue.get("body") or "",
        ]
        for text in texts_to_search:
            for match in TRELLO_SHORTLINK_RE.finditer(text):
                shortlink = match.group(1)
                card_id = trello_cards_by_shortlink.get(shortlink)
                if not card_id:
                    continue
                source_uid = make_uid(project_id, "task", "trello", card_id)
                key = (source_uid, issue_uid)
                if key in seen:
                    continue
                seen.add(key)

                links.append(
                    {
                        "source_uid": source_uid,
                        "target_uid": issue_uid,
                        "source_label": "Task",
                        "target_label": "Task",
                        "relationship_type": "RELACIONADA_A",
                        "properties": {
                            "via": "text",
                            "confidence": 1.0,
                        },
                    }
                )

    return links


def parse_cross_repo_closes(
    pulls: list[dict[str, Any]],
    current_repo: str,
    project_id: str,
) -> list[dict[str, Any]]:
    """
    Identifica padrões de fechamento 'closes owner/repo#N' em corpos de PRs (mesmo repo ou cross-repo).
    Retorna linhas de relacionamento (:PullRequest)-[:FECHA {via: 'text'}]->(:Task).
    """
    closes: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for pull in pulls:
        pull_number = pull.get("number")
        if not pull_number:
            continue
        pull_uid = make_uid(project_id, "pull_request", "github", f"{current_repo}#{pull_number}")
        body = pull.get("body") or ""

        for match in CLOSES_RE.finditer(body):
            target_repo = match.group("repo") or current_repo
            target_number = match.group("number")
            target_uid = make_uid(project_id, "task", "github", f"{target_repo}#{target_number}")

            key = (pull_uid, target_uid)
            if key in seen:
                continue
            seen.add(key)

            closes.append(
                {
                    "source_uid": pull_uid,
                    "target_uid": target_uid,
                    "source_label": "PullRequest",
                    "target_label": "Task",
                    "relationship_type": "FECHA",
                    "properties": {
                        "via": "text",
                    },
                }
            )

    return closes


def write_links_to_graph(
    driver: Driver,
    project_id: str,
    link_rows: list[dict[str, Any]],
) -> dict[str, int]:
    """Grava as relações RELACIONADA_A ou FECHA geradas no Neo4j."""
    if not link_rows:
        return {"written": 0}

    written_count = 0
    with driver.session() as session:
        for row in link_rows:
            source_label = row["source_label"]
            target_label = row["target_label"]
            rel_type = row["relationship_type"]
            query = (
                f"MATCH (s:`{source_label}` {{uid: $source_uid, project_id: $project_id}}) "
                f"MATCH (t:`{target_label}` {{uid: $target_uid, project_id: $project_id}}) "
                f"MERGE (s)-[r:`{rel_type}`]->(t) "
                f"SET r += $properties "
                f"RETURN count(r) AS count"
            )
            result = session.run(
                query,
                source_uid=row["source_uid"],
                target_uid=row["target_uid"],
                project_id=project_id,
                properties=row.get("properties", {}),
            )
            record = result.single()
            if record:
                written_count += record.get("count", 0)

    return {"written": written_count}


def link_project_in_graph(
    driver: Driver,
    project_id: str,
) -> dict[str, int]:
    """
    Executa a resolução automática de vínculos dentro do grafo Neo4j:
    1. Vincula Trello Task a GitHub PullRequest/Task via menções a 'trello.com/c/<shortLink>' nos corpos e títulos.
    2. Vincula PullRequest a Task via 'closes/fixes' cross-repo em corpos de PR.
    """
    stats = {"text_links": 0, "cross_repo_closes": 0}

    with driver.session() as session:
        # 1. PR mentions Trello card shortLink
        query_pr_trello = (
            "MATCH (pr:PullRequest {project_id: $project_id}) "
            "MATCH (t:Task {project_id: $project_id, provider: 'trello'}) "
            "WHERE (t.short_link IS NOT NULL AND ("
            "  (pr.body IS NOT NULL AND pr.body CONTAINS t.short_link) OR "
            "  (pr.title IS NOT NULL AND pr.title CONTAINS t.short_link)"
            ")) OR ("
            "  t.url IS NOT NULL AND ("
            "    (pr.body IS NOT NULL AND pr.body CONTAINS t.url) OR "
            "    (pr.title IS NOT NULL AND pr.title CONTAINS t.url)"
            "  )"
            ") "
            "MERGE (t)-[r:RELACIONADA_A]->(pr) "
            "ON CREATE SET r.via = 'text', r.confidence = 1.0 "
            "RETURN count(r) AS linked"
        )
        res = session.run(query_pr_trello, project_id=project_id).single()
        if res:
            stats["text_links"] += res.get("linked", 0)

        # 2. GitHub Issue mentions Trello card shortLink
        query_issue_trello = (
            "MATCH (gh:Task {project_id: $project_id, provider: 'github'}) "
            "MATCH (t:Task {project_id: $project_id, provider: 'trello'}) "
            "WHERE (t.short_link IS NOT NULL AND ("
            "  (gh.title IS NOT NULL AND gh.title CONTAINS t.short_link)"
            ")) OR ("
            "  t.url IS NOT NULL AND ("
            "    (gh.title IS NOT NULL AND gh.title CONTAINS t.url)"
            "  )"
            ") "
            "MERGE (t)-[r:RELACIONADA_A]->(gh) "
            "ON CREATE SET r.via = 'text', r.confidence = 1.0 "
            "RETURN count(r) AS linked"
        )
        res = session.run(query_issue_trello, project_id=project_id).single()
        if res:
            stats["text_links"] += res.get("linked", 0)

    return stats


def list_project_links(
    driver: Driver,
    project_id: str,
) -> dict[str, Any]:
    """
    Lista os vínculos Trello ↔ GitHub existentes (:Task)-[:RELACIONADA_A]->(:PullRequest|:Task),
    bem como as tarefas Trello sem vínculo e os candidatos disponíveis (PRs e Tarefas GitHub).
    """
    with driver.session() as session:
        # Existing links
        query_links = (
            "MATCH (s:Task {project_id: $project_id})-[r:RELACIONADA_A]->(t) "
            "WHERE (t:PullRequest OR t:Task) AND t.project_id = $project_id "
            "RETURN s.uid AS source_uid, s.title AS source_title, s.provider AS source_provider, s.url AS source_url, "
            "t.uid AS target_uid, t.title AS target_title, t.provider AS target_provider, t.url AS target_url, "
            "labels(t) AS target_labels, r.via AS via, r.confidence AS confidence "
            "ORDER BY s.title ASC"
        )
        link_records = session.run(query_links, project_id=project_id).data()

        links = [
            {
                "source_uid": rec["source_uid"],
                "source_title": rec.get("source_title") or rec["source_uid"],
                "source_provider": rec.get("source_provider") or "trello",
                "source_url": rec.get("source_url"),
                "target_uid": rec["target_uid"],
                "target_title": rec.get("target_title") or rec["target_uid"],
                "target_provider": rec.get("target_provider") or "github",
                "target_kind": "pull_request" if "PullRequest" in rec.get("target_labels", []) else "issue",
                "target_url": rec.get("target_url"),
                "via": rec.get("via") or "manual",
                "confidence": float(rec.get("confidence", 1.0)),
            }
            for rec in link_records
        ]

        # Unlinked Trello tasks
        query_unlinked = (
            "MATCH (t:Task {project_id: $project_id, provider: 'trello'}) "
            "WHERE NOT (t)-[:RELACIONADA_A]->() "
            "RETURN t.uid AS uid, t.title AS title, t.url AS url, t.short_link AS short_link "
            "ORDER BY t.title ASC"
        )
        unlinked_records = session.run(query_unlinked, project_id=project_id).data()
        unlinked_tasks = [
            {
                "uid": rec["uid"],
                "title": rec.get("title") or rec["uid"],
                "provider": "trello",
                "url": rec.get("url"),
                "short_link": rec.get("short_link"),
            }
            for rec in unlinked_records
        ]

        # Candidates (GitHub PRs and issues)
        query_candidates = (
            "MATCH (c {project_id: $project_id}) "
            "WHERE (c:PullRequest OR (c:Task AND c.provider = 'github')) "
            "RETURN c.uid AS uid, c.title AS title, labels(c) AS labels, c.url AS url "
            "ORDER BY c.title ASC"
        )
        candidate_records = session.run(query_candidates, project_id=project_id).data()
        candidates = [
            {
                "uid": rec["uid"],
                "title": rec.get("title") or rec["uid"],
                "kind": "pull_request" if "PullRequest" in rec.get("labels", []) else "issue",
                "provider": "github",
                "url": rec.get("url"),
            }
            for rec in candidate_records
        ]

        return {
            "project_id": project_id,
            "links": links,
            "unlinked_tasks": unlinked_tasks,
            "candidates": candidates,
        }


def create_manual_link(
    driver: Driver,
    project_id: str,
    source_uid: str,
    target_uid: str,
) -> dict[str, Any]:
    """Cria manualmente a relação (:Task)-[:RELACIONADA_A {via: 'manual', confidence: 1.0}]->(:PullRequest|:Task)."""
    with driver.session() as session:
        # Check source exists
        source_rec = session.run(
            "MATCH (s:Task {project_id: $project_id, uid: $source_uid}) RETURN s.uid AS uid",
            project_id=project_id,
            source_uid=source_uid,
        ).single()
        if not source_rec:
            raise ValueError(f"Tarefa de origem não encontrada: {source_uid}")

        # Check target exists
        target_rec = session.run(
            "MATCH (t {project_id: $project_id, uid: $target_uid}) "
            "WHERE t:PullRequest OR t:Task "
            "RETURN t.uid AS uid",
            project_id=project_id,
            target_uid=target_uid,
        ).single()
        if not target_rec:
            raise ValueError(f"Alvo do vínculo não encontrado: {target_uid}")

        # Create relationship
        query = (
            "MATCH (s:Task {project_id: $project_id, uid: $source_uid}) "
            "MATCH (t {project_id: $project_id, uid: $target_uid}) "
            "WHERE t:PullRequest OR t:Task "
            "MERGE (s)-[r:RELACIONADA_A]->(t) "
            "SET r.via = 'manual', r.confidence = 1.0 "
            "RETURN r.via AS via, r.confidence AS confidence"
        )
        record = session.run(
            query,
            project_id=project_id,
            source_uid=source_uid,
            target_uid=target_uid,
        ).single()

        return {
            "source_uid": source_uid,
            "target_uid": target_uid,
            "via": record.get("via", "manual") if record else "manual",
            "confidence": float(record.get("confidence", 1.0)) if record else 1.0,
        }


def delete_manual_link(
    driver: Driver,
    project_id: str,
    source_uid: str,
    target_uid: str,
) -> bool:
    """Remove a relação (:Task)-[:RELACIONADA_A]->(:PullRequest|:Task)."""
    with driver.session() as session:
        query = (
            "MATCH (s:Task {project_id: $project_id, uid: $source_uid})-[r:RELACIONADA_A]->"
            "(t {project_id: $project_id, uid: $target_uid}) "
            "DELETE r "
            "RETURN count(r) AS deleted"
        )
        record = session.run(
            query,
            project_id=project_id,
            source_uid=source_uid,
            target_uid=target_uid,
        ).single()
        return bool(record and record.get("deleted", 0) > 0)
