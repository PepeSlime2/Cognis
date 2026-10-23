from __future__ import annotations

import datetime as dt
import random
import time
import uuid

import pytest
from sqlalchemy.orm import Session

from app.db import session as db_session_module
from app.db.models import Project, User
from app.graph.collab_graph import build_collab_graph
from app.graph.facts import (
    CommentFact,
    GraphFacts,
    ModuleCommitFact,
    PersonFact,
    PRCloseTaskFact,
    PRFact,
    ReviewFact,
    TaskAssignmentFact,
    TaskDependencyFact,
)
from app.graph_service import build_cytoscape_elements
from app.metrics.flow_metrics import compute_all_flow_metrics
from app.metrics.graph_metrics import compute_all_graph_metrics
from app.metrics.person_metrics import compute_all_person_metrics
from app.metrics.service import get_metrics_bundle
from app.metrics.signals import detect_signals
from app.metrics.team_metrics import compute_all_team_metrics
from app.metrics.windows import parse_window


def _utc(year: int, month: int, day: int, hour: int = 0) -> dt.datetime:
    return dt.datetime(year, month, day, hour, tzinfo=dt.timezone.utc)


def create_dense_facts(num_people: int = 40, num_tasks: int = 400, num_prs: int = 250) -> GraphFacts:
    """Gera fatos densos e realistas de um projeto com grande volume de dados para teste de performance."""
    rng = random.Random(42)
    win = parse_window("2026-03-01", "2026-03-31", timezone="UTC")

    people = [PersonFact(uid=f"p_{i}", display_name=f"Developer {i}") for i in range(num_people)]

    tasks: list[TaskAssignmentFact] = []
    for i in range(num_tasks):
        # 1 a 3 pessoas por tarefa
        num_assignees = rng.randint(1, 3)
        assignees = [f"p_{p}" for p in rng.sample(range(num_people), num_assignees)]
        category = "done" if i < 260 else ("doing" if i < 350 else "todo")
        done_dt = _utc(2026, 3, rng.randint(5, 28)) if category == "done" else None
        started_dt = _utc(2026, 3, rng.randint(1, 10)) if category in ("done", "doing") else None
        due_dt = _utc(2026, 3, rng.randint(10, 30))

        tasks.append(
            TaskAssignmentFact(
                task_uid=f"task_{i}",
                person_uids=assignees,
                status_category=category,
                created_at=_utc(2026, 3, 1),
                started_at=started_dt,
                done_at=done_dt,
                due_at=due_dt,
                has_rework=(i % 8 == 0),
                is_planned=True,
                blocked=(i % 15 == 0),
                blocked_since=_utc(2026, 3, 20) if (i % 15 == 0) else None,
            )
        )

    deps = [
        TaskDependencyFact(blocking_task_uid=f"task_{i}", blocked_task_uid=f"task_{i+1}")
        for i in range(0, min(num_tasks - 1, 50))
    ]

    prs: list[PRFact] = []
    reviews: list[ReviewFact] = []
    comments: list[CommentFact] = []
    pr_close_tasks: list[PRCloseTaskFact] = []

    for i in range(num_prs):
        author_idx = rng.randint(0, num_people - 1)
        author_uid = f"p_{author_idx}"
        pr_uid = f"pr_{i}"
        created_at = _utc(2026, 3, rng.randint(1, 15))
        merged_at = _utc(2026, 3, rng.randint(16, 28)) if (i % 4 != 0) else None
        closed_at = merged_at or (_utc(2026, 3, 25) if (i % 8 == 0) else None)
        state = "merged" if merged_at else ("closed" if closed_at else "open")

        # 2 a 4 reviews por PR
        rev_indices = [idx for idx in rng.sample(range(num_people), rng.randint(2, 4)) if idx != author_idx]
        rev_uids = [f"p_{idx}" for idx in rev_indices]

        for rev_uid in rev_uids:
            rev_state = rng.choice(["APPROVED", "APPROVED", "CHANGES_REQUESTED", "COMMENTED"])
            reviews.append(
                ReviewFact(
                    reviewer_person_uid=rev_uid,
                    pr_author_person_uid=author_uid,
                    pr_uid=pr_uid,
                    state=rev_state,
                    submitted_at=_utc(2026, 3, rng.randint(10, 20)),
                )
            )

        prs.append(
            PRFact(
                pr_uid=pr_uid,
                author_person_uid=author_uid,
                created_at=created_at,
                closed_at=closed_at,
                merged_at=merged_at,
                state=state,
                has_changes_requested=(i % 5 == 0),
                first_review_at=_utc(2026, 3, rng.randint(2, 16)),
                changes_requested_count=1 if (i % 5 == 0) else 0,
                reviewers=rev_uids,
            )
        )

        # PR fecha tarefa
        if i < num_tasks:
            pr_close_tasks.append(
                PRCloseTaskFact(
                    pr_author_person_uid=author_uid,
                    task_assignee_person_uid=tasks[i].person_uids[0],
                    pr_uid=pr_uid,
                    task_uid=tasks[i].task_uid,
                    merged_at=merged_at,
                )
            )

    # Comentários
    for i in range(300):
        c_author = f"p_{rng.randint(0, num_people - 1)}"
        t_author = f"p_{rng.randint(0, num_people - 1)}"
        if c_author != t_author:
            comments.append(
                CommentFact(
                    commenter_person_uid=c_author,
                    target_author_person_uid=t_author,
                    target_uid=f"target_{i}",
                    created_at=_utc(2026, 3, rng.randint(5, 25)),
                )
            )

    # Módulos compartilhados
    module_commits: list[ModuleCommitFact] = []
    modules = ["api/auth", "api/billing", "frontend/components", "core/db", "infra/docker"]
    for p_idx in range(num_people):
        for mod in rng.sample(modules, rng.randint(1, 3)):
            for c_idx in range(rng.randint(2, 6)):
                module_commits.append(
                    ModuleCommitFact(
                        person_uid=f"p_{p_idx}",
                        module_path=mod,
                        commit_sha=f"sha_{p_idx}_{c_idx}_{mod[:3]}",
                        authored_at=_utc(2026, 3, rng.randint(2, 25)),
                        additions=rng.randint(10, 100),
                        deletions=rng.randint(2, 40),
                    )
                )

    return GraphFacts(
        project_id="perf_project",
        window=win,
        people=people,
        task_assignments=tasks,
        task_dependencies=deps,
        prs=prs,
        reviews=reviews,
        comments=comments,
        pr_closes_tasks=pr_close_tasks,
        module_commits=module_commits,
    )


def test_cytoscape_elements_performance_400_nodes():
    """Valida que o backend agrega e formata 400 nós e 1.500 arestas para Cytoscape em < 200 ms."""
    rng = random.Random(101)
    labels = ["Account", "Task", "PullRequest", "Repo", "Module", "Column"]

    nodes = []
    for i in range(400):
        lbl = labels[i % len(labels)]
        nodes.append(
            {
                "label": lbl,
                "properties": {
                    "uid": f"uid_{i}",
                    "display_name": f"Node {i} - {lbl}",
                    "community": i % 5,
                    "is_bot": False,
                },
                "degree": rng.randint(1, 60),
            }
        )

    relationships = []
    for i in range(1500):
        src = f"uid_{rng.randint(0, 399)}"
        tgt = f"uid_{rng.randint(0, 399)}"
        if src != tgt:
            relationships.append(
                {
                    "source": src,
                    "target": tgt,
                    "relationship": "review",
                    "weight": rng.randint(1, 5),
                    "properties": {"count": 1},
                }
            )

    t0 = time.perf_counter()
    res = build_cytoscape_elements(nodes, relationships, max_nodes=400, min_weight=1)
    duration_ms = (time.perf_counter() - t0) * 1000.0

    assert len(res["elements"]["nodes"]) == 400
    assert len(res["elements"]["edges"]) <= 1500
    assert res["stats"]["nodes"] == 400
    # O processamento deve ser praticamente instantâneo (< 200 ms)
    assert duration_ms < 200.0, f"Tempo de serialização do Cytoscape excedeu 200ms: {duration_ms:.2f} ms"


def test_metrics_bundle_dense_graph_under_2_seconds():
    """Valida o critério de aceite F10.3: cálculo do bundle de métricas em grafo denso < 2.0 s."""
    facts = create_dense_facts(num_people=40, num_tasks=400, num_prs=250)

    with db_session_module.SessionLocal() as session:
        user = User(email=f"perf_{uuid.uuid4().hex[:8]}@example.com", password_hash="hash")
        session.add(user)
        session.commit()

        project = Project(user_id=user.id, name="Perf Proj", timezone="UTC")
        session.add(project)
        session.commit()

        t0 = time.perf_counter()
        bundle = get_metrics_bundle(
            db=session,
            neo4j_driver=None,
            project=project,
            window=facts.window,
            force_refresh=True,
            raw_facts=facts,
        )
        total_duration = time.perf_counter() - t0

        # Verificação rigorosa do critério de aceite
        assert total_duration < 2.0, f"Bundle demorou {total_duration:.3f} s (limite: 2.0 s)"

        # Integridade do bundle
        assert bundle["cached"] is False
        metrics = bundle["metrics"]
        assert len(metrics) >= 25
        assert "graph.degree" in metrics
        assert "graph.pagerank" in metrics
        assert "graph.betweenness" in metrics
        assert "team.knowledge_concentration" in metrics
        assert "team.activity_distribution" in metrics
        assert "team.review_coverage" in metrics
        assert "flow.completion_rate" in metrics
        assert "flow.lead_time" in metrics
        assert "flow.cycle_time" in metrics

        # Teste de cache subsequente (snapshot hit)
        t_cache_0 = time.perf_counter()
        cached_bundle = get_metrics_bundle(
            db=session,
            neo4j_driver=None,
            project=project,
            window=facts.window,
            force_refresh=False,
            raw_facts=facts,
        )
        cache_duration = time.perf_counter() - t_cache_0

        assert cached_bundle["cached"] is True
        assert cache_duration < 0.1, f"Recuperação de cache demorou {cache_duration*1000:.2f} ms (limite: 100 ms)"


def test_individual_metrics_components_breakdown():
    """Mede e valida o tempo de cada etapa do pipeline isoladamente para relatório em docs/perf.md."""
    facts = create_dense_facts(num_people=40, num_tasks=400, num_prs=250)

    # 1. Collab Graph
    t0 = time.perf_counter()
    collab = build_collab_graph(facts)
    t_collab = (time.perf_counter() - t0) * 1000.0

    # 2. Graph Metrics (NetworkX)
    t0 = time.perf_counter()
    graph_m = compute_all_graph_metrics(collab)
    t_graph = (time.perf_counter() - t0) * 1000.0

    # 3. Person Metrics
    t0 = time.perf_counter()
    person_m = compute_all_person_metrics(facts, collab)
    t_person = (time.perf_counter() - t0) * 1000.0

    # 4. Team Metrics
    t0 = time.perf_counter()
    team_m = compute_all_team_metrics(facts, collab)
    t_team = (time.perf_counter() - t0) * 1000.0

    # 5. Flow Metrics
    t0 = time.perf_counter()
    flow_m = compute_all_flow_metrics(facts, window=facts.window)
    t_flow = (time.perf_counter() - t0) * 1000.0

    # 6. Signals
    all_metrics = {**graph_m, **person_m, **team_m, **flow_m}
    t0 = time.perf_counter()
    signals = detect_signals(
        metrics=all_metrics,
        facts=facts,
        collab=collab,
        window=facts.window,
    )
    t_signals = (time.perf_counter() - t0) * 1000.0

    total_sum_ms = t_collab + t_graph + t_person + t_team + t_flow + t_signals

    # Garantir que todos retornam dados válidos
    assert len(graph_m) > 0
    assert len(person_m) > 0
    assert len(team_m) > 0
    assert len(flow_m) > 0
    assert isinstance(signals, list)

    # O pipeline em partes soma muito menos que 2000 ms
    assert total_sum_ms < 2000.0
