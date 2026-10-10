"""
Camada de acesso ao Neo4j.

Todas as escritas usam MERGE, então rodar o coletor várias vezes não
duplica nós nem relacionamentos — só atualiza propriedades. Isso é
importante porque o /sync pode ser chamado periodicamente.
"""
from __future__ import annotations

from neo4j import Driver

from .database import create_neo4j_driver


class Neo4jWriter:
    def __init__(self, driver: Driver | None = None) -> None:
        self._driver = driver if driver is not None else create_neo4j_driver()
        self._owns_driver = driver is None

    def close(self) -> None:
        if self._owns_driver:
            self._driver.close()

    def __enter__(self) -> "Neo4jWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _run(self, query: str, **params) -> None:
        with self._driver.session() as session:
            session.run(query, **params)

    def ensure_constraints(self) -> None:
        """Roda uma vez (idempotente) para garantir unicidade e performance."""
        constraints = [
            "CREATE CONSTRAINT dev_username IF NOT EXISTS FOR (d:Developer) REQUIRE d.username IS UNIQUE",
            "CREATE CONSTRAINT repo_name IF NOT EXISTS FOR (r:Repository) REQUIRE r.full_name IS UNIQUE",
            "CREATE CONSTRAINT commit_sha IF NOT EXISTS FOR (c:Commit) REQUIRE c.sha IS UNIQUE",
            "CREATE CONSTRAINT pr_id IF NOT EXISTS FOR (p:PullRequest) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT task_id IF NOT EXISTS FOR (t:Task) REQUIRE t.id IS UNIQUE",
            "CREATE CONSTRAINT board_id IF NOT EXISTS FOR (b:Board) REQUIRE b.id IS UNIQUE",
            "CREATE CONSTRAINT sprint_id IF NOT EXISTS FOR (s:Sprint) REQUIRE s.id IS UNIQUE",
        ]
        for c in constraints:
            self._run(c)

    # ---------- Developer ----------
    def upsert_developer(self, username: str, name: str | None = None,
                          avatar_url: str | None = None, source: str | None = None) -> None:
        self._run(
            """
            MERGE (d:Developer {username: $username})
            SET d.name = coalesce($name, d.name),
                d.avatar_url = coalesce($avatar_url, d.avatar_url),
                d.source = coalesce($source, d.source)
            """,
            username=username, name=name, avatar_url=avatar_url, source=source,
        )

    # ---------- GitHub: Repository / Commit / PR ----------
    def upsert_repository(self, full_name: str) -> None:
        self._run("MERGE (r:Repository {full_name: $full_name})", full_name=full_name)

    def upsert_commit(self, sha: str, message: str, date: str, url: str,
                       author_username: str | None, repo_full_name: str) -> None:
        self._run(
            """
            MERGE (c:Commit {sha: $sha})
            SET c.message = $message, c.date = $date, c.url = $url
            WITH c
            MATCH (r:Repository {full_name: $repo_full_name})
            MERGE (c)-[:NO_REPOSITORIO]->(r)
            """,
            sha=sha, message=message, date=date, url=url, repo_full_name=repo_full_name,
        )
        if author_username:
            self._run(
                """
                MATCH (d:Developer {username: $username})
                MATCH (c:Commit {sha: $sha})
                MERGE (d)-[:REALIZOU]->(c)
                """,
                username=author_username, sha=sha,
            )

    def upsert_pull_request(self, pr_id: str, number: int, title: str, state: str,
                             created_at: str, merged_at: str | None, url: str,
                             author_username: str | None, repo_full_name: str) -> None:
        self._run(
            """
            MERGE (p:PullRequest {id: $pr_id})
            SET p.number = $number, p.title = $title, p.state = $state,
                p.created_at = $created_at, p.merged_at = $merged_at, p.url = $url
            WITH p
            MATCH (r:Repository {full_name: $repo_full_name})
            MERGE (p)-[:NO_REPOSITORIO]->(r)
            """,
            pr_id=pr_id, number=number, title=title, state=state,
            created_at=created_at, merged_at=merged_at, url=url, repo_full_name=repo_full_name,
        )
        if author_username:
            self._run(
                """
                MATCH (d:Developer {username: $username})
                MATCH (p:PullRequest {id: $pr_id})
                MERGE (d)-[:ABRIU]->(p)
                """,
                username=author_username, pr_id=pr_id,
            )

    def upsert_review(self, reviewer_username: str, pr_id: str, state: str, submitted_at: str) -> None:
        self._run(
            """
            MATCH (d:Developer {username: $reviewer_username})
            MATCH (p:PullRequest {id: $pr_id})
            MERGE (d)-[rel:REVISOU]->(p)
            SET rel.state = $state, rel.submitted_at = $submitted_at
            """,
            reviewer_username=reviewer_username, pr_id=pr_id, state=state, submitted_at=submitted_at,
        )

    def link_pr_closes_task(self, pr_id: str, task_id: str) -> None:
        self._run(
            """
            MATCH (p:PullRequest {id: $pr_id})
            MATCH (t:Task {id: $task_id})
            MERGE (p)-[:FECHA]->(t)
            """,
            pr_id=pr_id, task_id=task_id,
        )

    # ---------- Task genérica (GitHub Issue ou Trello Card) ----------
    def upsert_task(self, task_id: str, title: str, status: str, url: str | None,
                     source: str, assignee_username: str | None = None) -> None:
        self._run(
            """
            MERGE (t:Task {id: $task_id})
            SET t.title = $title, t.status = $status, t.url = $url, t.source = $source
            """,
            task_id=task_id, title=title, status=status, url=url, source=source,
        )
        if assignee_username:
            self._run(
                """
                MATCH (d:Developer {username: $username})
                MATCH (t:Task {id: $task_id})
                MERGE (d)-[:RESPONSAVEL_POR]->(t)
                """,
                username=assignee_username, task_id=task_id,
            )

    # ---------- Trello: Board / Sprint (lista) ----------
    def upsert_board(self, board_id: str, name: str) -> None:
        self._run("MERGE (b:Board {id: $board_id}) SET b.name = $name", board_id=board_id, name=name)

    def upsert_sprint(self, sprint_id: str, name: str, board_id: str) -> None:
        self._run(
            """
            MERGE (s:Sprint {id: $sprint_id})
            SET s.name = $name
            WITH s
            MATCH (b:Board {id: $board_id})
            MERGE (s)-[:NO_QUADRO]->(b)
            """,
            sprint_id=sprint_id, name=name, board_id=board_id,
        )

    def link_task_to_sprint(self, task_id: str, sprint_id: str) -> None:
        self._run(
            """
            MATCH (t:Task {id: $task_id})
            MATCH (s:Sprint {id: $sprint_id})
            MERGE (t)-[:PARTE_DE]->(s)
            """,
            task_id=task_id, sprint_id=sprint_id,
        )
