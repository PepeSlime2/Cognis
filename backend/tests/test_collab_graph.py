from __future__ import annotations

import datetime as dt
import pytest

from app.graph.facts import (
    CommentFact,
    GraphFacts,
    ModuleCommitFact,
    PersonFact,
    PRCloseTaskFact,
    ReviewFact,
    TaskAssignmentFact,
)
from app.graph.collab_graph import DEFAULT_EDGE_WEIGHTS, build_collab_graph


def test_collab_graph_reviews_capping():
    """Valida teto de 3 reviews por (u, PR) e descarte de estados não aprovados/revisados."""
    t0 = dt.datetime(2026, 3, 1, 10, 0, 0, tzinfo=dt.timezone.utc)
    facts = GraphFacts(
        project_id="test-proj",
        people=[
            PersonFact(uid="p1", display_name="Dev 1"),
            PersonFact(uid="p2", display_name="Dev 2"),
        ],
        reviews=[
            # 4 reviews válidos de p1 no PR pr1 de p2 -> deve limitar a 3 (peso 3 * 1.0 = 3.0)
            ReviewFact("p1", "p2", "pr1", "APPROVED", t0),
            ReviewFact("p1", "p2", "pr1", "CHANGES_REQUESTED", t0),
            ReviewFact("p1", "p2", "pr1", "COMMENTED", t0),
            ReviewFact("p1", "p2", "pr1", "APPROVED", t0),
            # 1 review pendente/descartado
            ReviewFact("p1", "p2", "pr1", "PENDING", t0),
        ],
    )

    collab = build_collab_graph(facts)

    assert collab.G_d.has_edge("p1", "p2")
    assert collab.G_d["p1"]["p2"]["weight"] == 3.0
    assert collab.G_u.has_edge("p1", "p2")
    assert collab.G_u["p1"]["p2"]["weight"] == 3.0
    assert collab.G_u["p1"]["p2"]["distance"] == pytest.approx(1.0 / 3.0)


def test_collab_graph_comments_capping():
    """Valida teto de 5 comentários por (u, alvo)."""
    t0 = dt.datetime(2026, 3, 1, 10, 0, 0, tzinfo=dt.timezone.utc)
    facts = GraphFacts(
        project_id="test-proj",
        people=[
            PersonFact(uid="p1", display_name="Dev 1"),
            PersonFact(uid="p2", display_name="Dev 2"),
        ],
        comments=[
            # 7 comentários de p1 no mesmo alvo -> deve limitar a 5 (5 * 0.5 = 2.5)
            CommentFact("p1", "p2", "target1", t0) for _ in range(7)
        ],
    )

    collab = build_collab_graph(facts)
    assert collab.G_d["p1"]["p2"]["weight"] == 2.5
    assert collab.G_u["p1"]["p2"]["weight"] == 2.5


def test_collab_graph_shared_tasks_and_modules():
    """Valida bidirecionalidade de shared_task (1.0) e shared_module (0.25 para >= 2 commits cada)."""
    t0 = dt.datetime(2026, 3, 1, 10, 0, 0, tzinfo=dt.timezone.utc)
    facts = GraphFacts(
        project_id="test-proj",
        people=[
            PersonFact(uid="p1", display_name="Dev 1"),
            PersonFact(uid="p2", display_name="Dev 2"),
        ],
        task_assignments=[
            TaskAssignmentFact(task_uid="t1", person_uids=["p1", "p2"], status_category="doing"),
        ],
        module_commits=[
            ModuleCommitFact("p1", "api/auth", "sha1", t0),
            ModuleCommitFact("p1", "api/auth", "sha2", t0),
            ModuleCommitFact("p2", "api/auth", "sha3", t0),
            ModuleCommitFact("p2", "api/auth", "sha4", t0),
        ],
    )

    collab = build_collab_graph(facts)

    # p1 -> p2: shared_task (1.0) + shared_module (0.25) = 1.25
    # p2 -> p1: shared_task (1.0) + shared_module (0.25) = 1.25
    assert collab.G_d["p1"]["p2"]["weight"] == 1.25
    assert collab.G_d["p2"]["p1"]["weight"] == 1.25

    # G_u soma ambos os sentidos: 1.25 + 1.25 = 2.5
    assert collab.G_u["p1"]["p2"]["weight"] == 2.5
    assert collab.G_u["p1"]["p2"]["distance"] == pytest.approx(1.0 / 2.5)


def test_collab_graph_filters_bots_and_self_loops():
    """Valida descarte de auto-interações e exclusão padrão de bots."""
    t0 = dt.datetime(2026, 3, 1, 10, 0, 0, tzinfo=dt.timezone.utc)
    facts = GraphFacts(
        project_id="test-proj",
        people=[
            PersonFact(uid="human", display_name="Humano"),
            PersonFact(uid="bot", display_name="Bot", is_bot=True),
        ],
        reviews=[
            ReviewFact("human", "human", "pr1", "APPROVED", t0),  # Auto-interação
            ReviewFact("bot", "human", "pr2", "APPROVED", t0),     # Bot
        ],
    )

    collab = build_collab_graph(facts, include_bots=False)

    assert "bot" not in collab.active_nodes
    assert not collab.G_u.has_edge("human", "human")
    assert collab.G_u.number_of_edges() == 0
