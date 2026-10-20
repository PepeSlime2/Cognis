from __future__ import annotations

import datetime as dt
import pytest

from app.graph.collab_graph import CollabGraph, build_collab_graph
from app.graph.facts import (
    CommentFact,
    CommitFact,
    GraphFacts,
    ModuleCommitFact,
    PersonFact,
    PRFact,
    ReviewFact,
    TaskAssignmentFact,
)
from app.metrics.person_metrics import (
    compute_all_person_metrics,
    compute_collaboration,
    compute_delivery,
    compute_overall,
    compute_participation,
    compute_person_counters,
    compute_quality,
    log_norm,
)
from app.metrics.windows import parse_window


def test_log_norm_values():
    """Valida normalização logarítmica com log1p."""
    assert log_norm(0, 10) == 0.0
    assert log_norm(5, 0) == 0.0
    assert log_norm(10, 10) == 1.0
    assert 0.0 < log_norm(5, 10) < 1.0


def test_edge_case_equipe_sem_atividade():
    """Critério de aceite: equipe sem atividade total retorna status 'insufficient_data' em participation."""
    facts = GraphFacts(
        project_id="p-empty",
        people=[
            PersonFact(uid="u1", display_name="Dev 1"),
            PersonFact(uid="u2", display_name="Dev 2"),
            PersonFact(uid="u3", display_name="Dev 3"),
        ],
    )
    collab = build_collab_graph(facts)
    _, counters = compute_person_counters(facts, collab)

    part_res = compute_participation(collab, counters)
    assert part_res.status == "insufficient_data"
    assert part_res.values is None
    assert "sem atividade" in part_res.reason


def test_edge_case_planned_zero_returns_null():
    """Critério de aceite: planned = 0 resulta em null (None) para delivery."""
    window = parse_window("2026-03-01", "2026-03-14")
    t0 = dt.datetime(2026, 3, 5, 12, 0, 0, tzinfo=dt.timezone.utc)

    facts = GraphFacts(
        project_id="p-tasks",
        window=window,
        people=[
            PersonFact(uid="u_planned", display_name="Dev Planejado"),
            PersonFact(uid="u_no_planned", display_name="Dev Sem Tarefa"),
        ],
        commits=[
            CommitFact("sha_nop", "u_no_planned", t0),
        ],
        task_assignments=[
            # 4 tarefas planejadas para u_planned, 3 concluídas
            TaskAssignmentFact("t1", ["u_planned"], "done", due_at=t0),
            TaskAssignmentFact("t2", ["u_planned"], "done", due_at=t0),
            TaskAssignmentFact("t3", ["u_planned"], "done", due_at=t0),
            TaskAssignmentFact("t4", ["u_planned"], "doing", due_at=t0),
            # u_no_planned não tem nenhuma tarefa
        ],
    )
    collab = build_collab_graph(facts)
    deliv_res = compute_delivery(facts, collab)

    assert deliv_res.status == "ok"
    # u_no_planned tem planned = 0 -> deve ser None (null no JSON)
    assert deliv_res.values["u_no_planned"] is None

    # u_planned tem 3 concluídas de 4 planejadas = 75.0%
    assert deliv_res.values["u_planned"] == 75.0


def test_edge_case_pesos_renormalizados():
    """
    Critério de aceite: pesos renormalizados em person.overall quando índices são nulos.
    Exemplo:
    Pesos padrão:
      participation: 0.25
      collaboration: 0.30
      delivery: 0.30
      quality: 0.15
    Se delivery é None:
      pesos ativos: 0.25 (part), 0.30 (collab), 0.15 (qual) -> soma = 0.70.
      Valores: part = 80.0, collab = 90.0, qual = 100.0.
      Cálculo esperado:
        (0.25 * 80 + 0.30 * 90 + 0.15 * 100) / 0.70
        = (20.0 + 27.0 + 15.0) / 0.70 = 62.0 / 0.70 = 88.5714... -> 88.57.
    """
    collab = CollabGraph(
        G_d=None,
        G_u=None,
        G_u_prime=None,
        active_nodes=["u_renorm"],
        edge_breakdown={},
        config={},
    )

    from app.metrics.graph_metrics import MetricResult

    part = MetricResult("person.participation", "person", "ok", "0-100", {"u_renorm": 80.0})
    collab_m = MetricResult("person.collaboration", "person", "ok", "0-100", {"u_renorm": 90.0})
    deliv = MetricResult("person.delivery", "person", "ok", "0-100", {"u_renorm": None})  # Nulo!
    qual = MetricResult("person.quality", "person", "ok", "0-100", {"u_renorm": 100.0})

    overall = compute_overall(collab, part, collab_m, deliv, qual)
    assert overall.status == "ok"
    assert overall.values["u_renorm"] == pytest.approx(88.57, abs=0.01)
    assert overall.inputs["used_components"]["u_renorm"] == ["participation", "collaboration", "quality"]


def test_quality_proxy_components():
    """Valida componentes de proxy de qualidade e descarte de amostras pequenas (< 3)."""
    t0 = dt.datetime(2026, 3, 5, 12, 0, 0, tzinfo=dt.timezone.utc)
    facts = GraphFacts(
        project_id="p-qual",
        people=[
            PersonFact(uid="dev_few_prs", display_name="Poucos PRs"),
            PersonFact(uid="dev_many_prs", display_name="Muitos PRs"),
        ],
        prs=[
            # dev_few_prs tem apenas 2 PRs (< 3) -> qualidade deve ser None
            PRFact("pr1", "dev_few_prs", t0),
            PRFact("pr2", "dev_few_prs", t0),
            # dev_many_prs tem 4 PRs, 1 com CHANGES_REQUESTED -> ratio = 0.25 -> quality = 75.0
            PRFact("pr3", "dev_many_prs", t0, has_changes_requested=True),
            PRFact("pr4", "dev_many_prs", t0),
            PRFact("pr5", "dev_many_prs", t0),
            PRFact("pr6", "dev_many_prs", t0),
        ],
    )
    collab = build_collab_graph(facts)
    qual_res = compute_quality(facts, collab)

    assert qual_res.values["dev_few_prs"] is None
    assert qual_res.values["dev_many_prs"] == 75.0


def test_compute_all_person_metrics_integration():
    """Valida execução unificada das 6 métricas individuais para uma equipe de 3 pessoas."""
    t0 = dt.datetime(2026, 3, 5, 12, 0, 0, tzinfo=dt.timezone.utc)
    facts = GraphFacts(
        project_id="p-team",
        people=[
            PersonFact(uid="ana", display_name="Ana"),
            PersonFact(uid="bruno", display_name="Bruno"),
            PersonFact(uid="carla", display_name="Carla"),
        ],
        commits=[
            CommitFact("sha1", "ana", t0),
            CommitFact("sha2", "bruno", t0),
        ],
        prs=[
            PRFact("pr1", "ana", t0, state="merged", merged_at=t0),
        ],
        reviews=[
            ReviewFact("bruno", "ana", "pr1", "APPROVED", t0),
            ReviewFact("carla", "ana", "pr1", "COMMENTED", t0),
        ],
        comments=[
            CommentFact("ana", "bruno", "pr1", t0),
        ],
        task_assignments=[
            TaskAssignmentFact("t1", ["ana", "bruno"], "done", is_planned=True),
            TaskAssignmentFact("t2", ["carla"], "done", is_planned=True),
        ],
    )
    collab = build_collab_graph(facts)
    metrics = compute_all_person_metrics(facts, collab)

    expected = {
        "person.counters",
        "person.participation",
        "person.collaboration",
        "person.delivery",
        "person.quality",
        "person.overall",
    }
    assert set(metrics.keys()) == expected

    # Todas as métricas devem estar no estado ok
    for name in expected:
        res = metrics[name]
        assert res.status == "ok", f"{name} falhou com status {res.status}: {res.reason}"
        assert isinstance(res.values, dict)
