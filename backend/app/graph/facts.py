from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from ..metrics.windows import TimeWindow


@dataclass(frozen=True)
class PersonFact:
    uid: str
    display_name: str
    excluded: bool = False
    is_bot: bool = False


@dataclass(frozen=True)
class ReviewFact:
    reviewer_person_uid: str
    pr_author_person_uid: str
    pr_uid: str
    state: str
    submitted_at: dt.datetime


@dataclass(frozen=True)
class CommentFact:
    commenter_person_uid: str
    target_author_person_uid: str
    target_uid: str
    created_at: dt.datetime


@dataclass(frozen=True)
class TaskAssignmentFact:
    task_uid: str
    person_uids: list[str]
    status_category: str
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    started_at: dt.datetime | None = None
    done_at: dt.datetime | None = None
    due_at: dt.datetime | None = None
    has_rework: bool = False
    is_planned: bool | None = None
    blocked: bool = False
    blocked_since: dt.datetime | None = None


@dataclass(frozen=True)
class TaskDependencyFact:
    blocking_task_uid: str
    blocked_task_uid: str


@dataclass(frozen=True)
class PRCloseTaskFact:
    pr_author_person_uid: str
    task_assignee_person_uid: str
    pr_uid: str
    task_uid: str
    merged_at: dt.datetime | None = None


@dataclass(frozen=True)
class PRFact:
    pr_uid: str
    author_person_uid: str
    created_at: dt.datetime
    closed_at: dt.datetime | None = None
    merged_at: dt.datetime | None = None
    state: str = "open"
    has_changes_requested: bool = False
    first_review_at: dt.datetime | None = None
    changes_requested_count: int = 0
    reviewers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CommitFact:
    sha: str
    author_person_uid: str
    authored_at: dt.datetime
    is_merge: bool = False


@dataclass(frozen=True)
class ModuleCommitFact:
    person_uid: str
    module_path: str
    commit_sha: str
    authored_at: dt.datetime
    additions: int = 0
    deletions: int = 0


@dataclass
class GraphFacts:
    """
    Coleção pura de fatos coletados na janela temporal para um projeto.
    Serve de entrada determinística para collab_graph.py e para o motor de métricas.
    """

    project_id: str
    window: TimeWindow | None = None
    people: list[PersonFact] = field(default_factory=list)
    reviews: list[ReviewFact] = field(default_factory=list)
    comments: list[CommentFact] = field(default_factory=list)
    task_assignments: list[TaskAssignmentFact] = field(default_factory=list)
    task_dependencies: list[TaskDependencyFact] = field(default_factory=list)
    pr_closes_tasks: list[PRCloseTaskFact] = field(default_factory=list)
    module_commits: list[ModuleCommitFact] = field(default_factory=list)
    commits: list[CommitFact] = field(default_factory=list)
    prs: list[PRFact] = field(default_factory=list)


def _to_utc_dt(val: Any) -> dt.datetime | None:
    if val is None:
        return None
    if hasattr(val, "to_native"):
        val = val.to_native()
    if isinstance(val, dt.datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=dt.timezone.utc)
        return val.astimezone(dt.timezone.utc)
    if isinstance(val, str):
        try:
            d = dt.datetime.fromisoformat(val)
            if d.tzinfo is None:
                return d.replace(tzinfo=dt.timezone.utc)
            return d.astimezone(dt.timezone.utc)
        except Exception:
            return None
    return None


def load_facts_from_neo4j(
    driver: Any,
    project_id: str,
    window: TimeWindow | None = None,
) -> GraphFacts:
    """
    Carrega todos os fatos do grafo Neo4j para um projeto e janela temporal.
    Garante isolamento por project_id (SPEC §13).
    """
    if driver is None:
        return GraphFacts(project_id=project_id, window=window)

    people: list[PersonFact] = []
    reviews: list[ReviewFact] = []
    comments: list[CommentFact] = []
    task_assignments: list[TaskAssignmentFact] = []
    task_dependencies: list[TaskDependencyFact] = []
    pr_closes_tasks: list[PRCloseTaskFact] = []
    module_commits: list[ModuleCommitFact] = []
    commits: list[CommitFact] = []
    prs: list[PRFact] = []

    with driver.session() as session:
        # 1. Pessoas
        p_res = session.run(
            """
            MATCH (p:Person)
            WHERE p.project_id = $project_id
            RETURN p.uid AS uid, p.display_name AS display_name,
                   coalesce(p.excluded, false) AS excluded,
                   coalesce(p.is_bot, false) AS is_bot
            """,
            project_id=project_id,
        )
        for record in p_res:
            people.append(
                PersonFact(
                    uid=record["uid"],
                    display_name=record["display_name"] or record["uid"],
                    excluded=bool(record["excluded"]),
                    is_bot=bool(record["is_bot"]),
                )
            )

        # 2. Reviews
        rev_res = session.run(
            """
            MATCH (rev:Review)
            WHERE rev.project_id = $project_id
            OPTIONAL MATCH (rev)<-[:ENVIOU]-(rev_acc:Account)<-[:TEM_CONTA]-(rev_p:Person)
            OPTIONAL MATCH (rev)-[:SOBRE]->(pr:PullRequest)<-[:ABRIU]-(pr_acc:Account)<-[:TEM_CONTA]-(pr_p:Person)
            RETURN coalesce(rev_p.uid, rev_acc.uid) AS reviewer_uid,
                   coalesce(pr_p.uid, pr_acc.uid) AS pr_author_uid,
                   pr.uid AS pr_uid,
                   rev.state AS state,
                   rev.submitted_at AS submitted_at
            """,
            project_id=project_id,
        )
        for record in rev_res:
            sub_at = _to_utc_dt(record["submitted_at"])
            if (
                sub_at is not None
                and record["reviewer_uid"]
                and record["pr_author_uid"]
                and record["pr_uid"]
            ):
                if window is None or (window.start_utc <= sub_at < window.end_utc):
                    reviews.append(
                        ReviewFact(
                            reviewer_person_uid=record["reviewer_uid"],
                            pr_author_person_uid=record["pr_author_uid"],
                            pr_uid=record["pr_uid"],
                            state=record["state"] or "APPROVED",
                            submitted_at=sub_at,
                        )
                    )

        # 3. Comentários
        c_res = session.run(
            """
            MATCH (c:Comment)
            WHERE c.project_id = $project_id
            OPTIONAL MATCH (c)<-[:COMENTOU]-(c_acc:Account)<-[:TEM_CONTA]-(c_p:Person)
            OPTIONAL MATCH (c)-[:SOBRE]->(target)
            OPTIONAL MATCH (target)<-[:ABRIU|CRIOU|RESPONSAVEL_POR]-(t_acc:Account)<-[:TEM_CONTA]-(t_p:Person)
            RETURN coalesce(c_p.uid, c_acc.uid) AS commenter_uid,
                   coalesce(t_p.uid, t_acc.uid) AS target_author_uid,
                   target.uid AS target_uid,
                   c.created_at AS created_at
            """,
            project_id=project_id,
        )
        for record in c_res:
            c_at = _to_utc_dt(record["created_at"])
            if (
                c_at is not None
                and record["commenter_uid"]
                and record["target_author_uid"]
                and record["target_uid"]
            ):
                if window is None or (window.start_utc <= c_at < window.end_utc):
                    comments.append(
                        CommentFact(
                            commenter_person_uid=record["commenter_uid"],
                            target_author_person_uid=record["target_author_uid"],
                            target_uid=record["target_uid"],
                            created_at=c_at,
                        )
                    )

        # 4. Tarefas
        t_res = session.run(
            """
            MATCH (t:Task)
            WHERE t.project_id = $project_id
            OPTIONAL MATCH (t)<-[:RESPONSAVEL_POR]-(acc:Account)<-[:TEM_CONTA]-(p:Person)
            RETURN t.uid AS task_uid,
                   collect(DISTINCT coalesce(p.uid, acc.uid)) AS person_uids,
                   t.status_category AS status_category,
                   t.created_at AS created_at,
                   t.updated_at AS updated_at,
                   t.started_at AS started_at,
                   t.done_at AS done_at,
                   t.due_at AS due_at,
                   coalesce(t.has_rework, false) AS has_rework,
                   t.is_planned AS is_planned,
                   coalesce(t.blocked, false) AS blocked,
                   t.blocked_since AS blocked_since
            """,
            project_id=project_id,
        )
        for record in t_res:
            p_uids = [u for u in record["person_uids"] if u]
            task_assignments.append(
                TaskAssignmentFact(
                    task_uid=record["task_uid"],
                    person_uids=p_uids,
                    status_category=record["status_category"] or "todo",
                    created_at=_to_utc_dt(record["created_at"]),
                    updated_at=_to_utc_dt(record["updated_at"]),
                    started_at=_to_utc_dt(record["started_at"]),
                    done_at=_to_utc_dt(record["done_at"]),
                    due_at=_to_utc_dt(record["due_at"]),
                    has_rework=bool(record["has_rework"]),
                    is_planned=record["is_planned"],
                    blocked=bool(record["blocked"]),
                    blocked_since=_to_utc_dt(record["blocked_since"]),
                )
            )

        # 5. Dependências entre tarefas
        dep_res = session.run(
            """
            MATCH (t1:Task)-[r:BLOQUEADA_POR]->(t2:Task)
            WHERE t1.project_id = $project_id AND t2.project_id = $project_id
            RETURN t2.uid AS blocking_uid, t1.uid AS blocked_uid
            """,
            project_id=project_id,
        )
        for record in dep_res:
            task_dependencies.append(
                TaskDependencyFact(
                    blocking_task_uid=record["blocking_uid"],
                    blocked_task_uid=record["blocked_uid"],
                )
            )

        # 6. PR fecha tarefas
        close_res = session.run(
            """
            MATCH (pr:PullRequest)-[r:FECHA]->(t:Task)
            WHERE pr.project_id = $project_id AND t.project_id = $project_id
            OPTIONAL MATCH (pr)<-[:ABRIU]-(pr_acc:Account)<-[:TEM_CONTA]-(pr_p:Person)
            OPTIONAL MATCH (t)<-[:RESPONSAVEL_POR]-(t_acc:Account)<-[:TEM_CONTA]-(t_p:Person)
            RETURN coalesce(pr_p.uid, pr_acc.uid) AS pr_author_uid,
                   coalesce(t_p.uid, t_acc.uid) AS task_assignee_uid,
                   pr.uid AS pr_uid,
                   t.uid AS task_uid,
                   pr.merged_at AS merged_at
            """,
            project_id=project_id,
        )
        for record in close_res:
            if record["pr_author_uid"] and record["task_assignee_uid"]:
                pr_closes_tasks.append(
                    PRCloseTaskFact(
                        pr_author_person_uid=record["pr_author_uid"],
                        task_assignee_person_uid=record["task_assignee_uid"],
                        pr_uid=record["pr_uid"],
                        task_uid=record["task_uid"],
                        merged_at=_to_utc_dt(record["merged_at"]),
                    )
                )

        # 7. Commits em Módulos
        mc_res = session.run(
            """
            MATCH (c:Commit)-[:ALTEROU]->(m:Module)
            WHERE c.project_id = $project_id AND m.project_id = $project_id
              AND NOT coalesce(c.is_merge, false)
            OPTIONAL MATCH (c)<-[:REALIZOU]-(acc:Account)<-[:TEM_CONTA]-(p:Person)
            RETURN coalesce(p.uid, acc.uid) AS person_uid,
                   coalesce(m.path, m.uid) AS module_path,
                   c.sha AS commit_sha,
                   c.authored_at AS authored_at,
                   coalesce(c.additions, 0) AS additions,
                   coalesce(c.deletions, 0) AS deletions
            """,
            project_id=project_id,
        )
        for record in mc_res:
            a_at = _to_utc_dt(record["authored_at"])
            if a_at is not None and record["person_uid"]:
                if window is None or (window.start_utc <= a_at < window.end_utc):
                    module_commits.append(
                        ModuleCommitFact(
                            person_uid=record["person_uid"],
                            module_path=record["module_path"],
                            commit_sha=record["commit_sha"],
                            authored_at=a_at,
                            additions=int(record["additions"]),
                            deletions=int(record["deletions"]),
                        )
                    )

        # 8. Commits gerais
        com_res = session.run(
            """
            MATCH (c:Commit)
            WHERE c.project_id = $project_id
            OPTIONAL MATCH (c)<-[:REALIZOU]-(acc:Account)<-[:TEM_CONTA]-(p:Person)
            RETURN c.sha AS sha,
                   coalesce(p.uid, acc.uid) AS author_person_uid,
                   c.authored_at AS authored_at,
                   coalesce(c.is_merge, false) AS is_merge
            """,
            project_id=project_id,
        )
        for record in com_res:
            a_at = _to_utc_dt(record["authored_at"])
            if a_at is not None and record["author_person_uid"]:
                if window is None or (window.start_utc <= a_at < window.end_utc):
                    commits.append(
                        CommitFact(
                            sha=record["sha"],
                            author_person_uid=record["author_person_uid"],
                            authored_at=a_at,
                            is_merge=bool(record["is_merge"]),
                        )
                    )

        # 9. Pull Requests
        prs_res = session.run(
            """
            MATCH (pr:PullRequest)
            WHERE pr.project_id = $project_id
            OPTIONAL MATCH (pr)<-[:ABRIU]-(acc:Account)<-[:TEM_CONTA]-(p:Person)
            OPTIONAL MATCH (pr)<-[:SOBRE]-(rev:Review)
            RETURN pr.uid AS pr_uid,
                   coalesce(p.uid, acc.uid) AS author_person_uid,
                   pr.created_at AS created_at,
                   pr.closed_at AS closed_at,
                   pr.merged_at AS merged_at,
                   coalesce(pr.state, 'open') AS state,
                   coalesce(pr.has_changes_requested, false) AS has_changes_requested,
                   pr.first_review_at AS first_review_at,
                   count(DISTINCT CASE WHEN rev.state = 'CHANGES_REQUESTED' THEN rev.uid END) AS changes_requested_count
            """,
            project_id=project_id,
        )
        for record in prs_res:
            c_at = _to_utc_dt(record["created_at"])
            if c_at is not None and record["author_person_uid"]:
                prs.append(
                    PRFact(
                        pr_uid=record["pr_uid"],
                        author_person_uid=record["author_person_uid"],
                        created_at=c_at,
                        closed_at=_to_utc_dt(record["closed_at"]),
                        merged_at=_to_utc_dt(record["merged_at"]),
                        state=record["state"] or "open",
                        has_changes_requested=bool(record["has_changes_requested"]),
                        first_review_at=_to_utc_dt(record["first_review_at"]),
                        changes_requested_count=int(record["changes_requested_count"] or 0),
                    )
                )

    return GraphFacts(
        project_id=project_id,
        window=window,
        people=people,
        reviews=reviews,
        comments=comments,
        task_assignments=task_assignments,
        task_dependencies=task_dependencies,
        pr_closes_tasks=pr_closes_tasks,
        module_commits=module_commits,
        commits=commits,
        prs=prs,
    )

