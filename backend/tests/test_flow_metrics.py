from __future__ import annotations

import datetime as dt

import pytest

from app.graph.facts import (
    GraphFacts,
    PersonFact,
    PRFact,
    ReviewFact,
    TaskAssignmentFact,
    TaskDependencyFact,
)
from app.metrics.flow_metrics import (
    compute_all_flow_metrics,
    compute_bottleneck_risk,
    compute_completion_rate,
    compute_critical_dependencies,
    compute_cycle_time,
    compute_late_rate,
    compute_lead_time,
    compute_pr_time_to_first_review,
    compute_pr_time_to_merge,
    compute_rework,
    compute_wip_per_person,
)
from app.metrics.windows import parse_window


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> dt.datetime:
    return dt.datetime(year, month, day, hour, minute, tzinfo=dt.timezone.utc)


def test_completion_rate_rule_r1_and_insufficient_data():
    win = parse_window("2026-03-01", "2026-03-15", timezone="UTC")

    # Menos de 5 tarefas planejadas -> insufficient_data
    facts_small = GraphFacts(
        project_id="proj_1",
        window=win,
        task_assignments=[
            TaskAssignmentFact(
                task_uid="t1",
                person_uids=["u1"],
                status_category="done",
                due_at=_utc(2026, 3, 5),
                done_at=_utc(2026, 3, 4),
            ),
            TaskAssignmentFact(
                task_uid="t2",
                person_uids=["u2"],
                status_category="doing",
                due_at=_utc(2026, 3, 6),
            ),
        ],
    )
    res_small = compute_completion_rate(facts_small, window=win)
    assert res_small.status == "insufficient_data"
    assert res_small.values is None
    assert res_small.inputs["planned_count"] == 2
    assert res_small.inputs["rule"] == "R1"

    # 5 tarefas com due_at na janela (R1)
    tasks = [
        TaskAssignmentFact("t1", ["alice"], "done", due_at=_utc(2026, 3, 5), done_at=_utc(2026, 3, 4)),
        TaskAssignmentFact("t2", ["alice"], "done", due_at=_utc(2026, 3, 6), done_at=_utc(2026, 3, 5)),
        TaskAssignmentFact("t3", ["bob"], "done", due_at=_utc(2026, 3, 7), done_at=_utc(2026, 3, 7)),
        TaskAssignmentFact("t4", ["bob"], "doing", due_at=_utc(2026, 3, 8)),
        TaskAssignmentFact("t5", ["carol"], "todo", due_at=_utc(2026, 3, 9)),
    ]
    facts_ok = GraphFacts(project_id="proj_1", window=win, task_assignments=tasks)
    res_ok = compute_completion_rate(facts_ok, window=win)
    assert res_ok.status == "ok"
    assert res_ok.values["planned_count"] == 5
    assert res_ok.values["done_count"] == 3
    assert res_ok.values["overall"] == 0.6  # 3/5
    assert res_ok.values["by_person"]["alice"] == 1.0  # 2/2
    assert res_ok.values["by_person"]["bob"] == 0.5  # 1/2
    assert res_ok.values["by_person"]["carol"] == 0.0  # 0/1


def test_completion_rate_rule_r2():
    win = parse_window("2026-03-01", "2026-03-15", timezone="UTC")

    # Nenhuma tarefa com due_at na janela -> usa Regra R2
    tasks = [
        TaskAssignmentFact("t1", ["u1"], "done", created_at=_utc(2026, 3, 1), done_at=_utc(2026, 3, 5)),
        TaskAssignmentFact("t2", ["u1"], "done", created_at=_utc(2026, 3, 2), done_at=_utc(2026, 3, 6)),
        TaskAssignmentFact("t3", ["u2"], "doing", created_at=_utc(2026, 3, 3)),
        TaskAssignmentFact("t4", ["u2"], "review", created_at=_utc(2026, 3, 4)),
        TaskAssignmentFact("t5", ["u3"], "doing", created_at=_utc(2026, 3, 5)),
    ]
    facts = GraphFacts(project_id="proj_1", window=win, task_assignments=tasks)
    res = compute_completion_rate(facts, window=win)

    assert res.status == "ok"
    assert res.inputs["rule"] == "R2"
    assert res.values["planned_count"] == 5
    assert res.values["done_count"] == 2
    assert res.values["overall"] == 0.4


def test_late_rate_and_insufficient_data():
    win = parse_window("2026-03-01", "2026-03-15", timezone="UTC")
    now = _utc(2026, 3, 15, 12, 0)

    # Menos de 5 concluídas com prazo
    small_tasks = [
        TaskAssignmentFact("t1", ["u1"], "done", due_at=_utc(2026, 3, 5), done_at=_utc(2026, 3, 4)),
        TaskAssignmentFact("t2", ["u1"], "done", due_at=_utc(2026, 3, 5), done_at=_utc(2026, 3, 6)),
    ]
    res_small = compute_late_rate(GraphFacts("proj_1", window=win, task_assignments=small_tasks), window=win, now=now)
    assert res_small.status == "insufficient_data"

    # 5 tarefas concluídas com prazo: 2 atrasadas, 3 no prazo
    # + 1 tarefa aberta vencida (due_at < now)
    tasks = [
        TaskAssignmentFact("t1", ["u1"], "done", due_at=_utc(2026, 3, 5), done_at=_utc(2026, 3, 4)),  # no prazo
        TaskAssignmentFact("t2", ["u1"], "done", due_at=_utc(2026, 3, 5), done_at=_utc(2026, 3, 5)),  # no prazo
        TaskAssignmentFact("t3", ["u1"], "done", due_at=_utc(2026, 3, 6), done_at=_utc(2026, 3, 5)),  # no prazo
        TaskAssignmentFact("t4", ["u2"], "done", due_at=_utc(2026, 3, 5), done_at=_utc(2026, 3, 6)),  # atrasada
        TaskAssignmentFact("t5", ["u2"], "done", due_at=_utc(2026, 3, 7), done_at=_utc(2026, 3, 8)),  # atrasada
        TaskAssignmentFact("t6", ["u3"], "doing", due_at=_utc(2026, 3, 10)),  # aberta e vencida (10 < 15)
        TaskAssignmentFact("t7", ["u3"], "doing", due_at=_utc(2026, 3, 20)),  # aberta no prazo (20 > 15)
    ]
    facts = GraphFacts("proj_1", window=win, task_assignments=tasks)
    res = compute_late_rate(facts, window=win, now=now)

    assert res.status == "ok"
    assert res.values["total_concluded_with_due"] == 5
    assert res.values["late_concluded_count"] == 2
    assert res.values["late_rate"] == 0.4  # 2/5
    assert res.values["overdue_open"] == 1


def test_lead_and_cycle_time_fabricated_chronology():
    win = parse_window("2026-03-01", "2026-03-15", timezone="UTC")

    # Tarefas com durações exatas:
    # Lead time (done - created): 1, 2, 3, 4, 10 dias
    # Cycle time (done - started): 0.5, 1.0, 1.5, 2.0, 5.0 dias
    tasks = [
        TaskAssignmentFact(
            "t1", ["u1"], "done",
            created_at=_utc(2026, 3, 1), started_at=_utc(2026, 3, 1, 12), done_at=_utc(2026, 3, 2),
        ),
        TaskAssignmentFact(
            "t2", ["u1"], "done",
            created_at=_utc(2026, 3, 1), started_at=_utc(2026, 3, 2), done_at=_utc(2026, 3, 3),
        ),
        TaskAssignmentFact(
            "t3", ["u2"], "done",
            created_at=_utc(2026, 3, 1), started_at=_utc(2026, 3, 2, 12), done_at=_utc(2026, 3, 4),
        ),
        TaskAssignmentFact(
            "t4", ["u2"], "done",
            created_at=_utc(2026, 3, 1), started_at=_utc(2026, 3, 3), done_at=_utc(2026, 3, 5),
        ),
        TaskAssignmentFact(
            "t5", ["u3"], "done",
            created_at=_utc(2026, 3, 1), started_at=_utc(2026, 3, 6), done_at=_utc(2026, 3, 11),
        ),
    ]
    facts = GraphFacts("proj_1", window=win, task_assignments=tasks)

    # Lead time
    res_lead = compute_lead_time(facts, window=win)
    assert res_lead.status == "ok"
    assert res_lead.values["n"] == 5
    # Amostra lead: [1.0, 2.0, 3.0, 4.0, 10.0] -> mediana = 3.0
    assert res_lead.values["median_days"] == 3.0
    assert res_lead.values["p85_days"] > 4.0

    # Cycle time
    res_cycle = compute_cycle_time(facts, window=win)
    assert res_cycle.status == "ok"
    assert res_cycle.values["n"] == 5
    # Amostra cycle: [0.5, 1.0, 1.5, 2.0, 5.0] -> mediana = 1.5
    assert res_cycle.values["median_days"] == 1.5


def test_lead_and_cycle_time_insufficient_data():
    win = parse_window("2026-03-01", "2026-03-15", timezone="UTC")
    tasks = [
        TaskAssignmentFact("t1", ["u1"], "done", created_at=_utc(2026, 3, 1), started_at=_utc(2026, 3, 2), done_at=_utc(2026, 3, 3)),
    ]
    facts = GraphFacts("proj_1", window=win, task_assignments=tasks)
    assert compute_lead_time(facts, window=win).status == "insufficient_data"
    assert compute_cycle_time(facts, window=win).status == "insufficient_data"


def test_rework_metric():
    win = parse_window("2026-03-01", "2026-03-15", timezone="UTC")
    tasks = [
        TaskAssignmentFact("t1", ["u1"], "done", done_at=_utc(2026, 3, 2), has_rework=True),
        TaskAssignmentFact("t2", ["u1"], "done", done_at=_utc(2026, 3, 3), has_rework=False),
        TaskAssignmentFact("t3", ["u2"], "done", done_at=_utc(2026, 3, 4), has_rework=True),
        TaskAssignmentFact("t4", ["u2"], "done", done_at=_utc(2026, 3, 5), has_rework=False),
        TaskAssignmentFact("t5", ["u3"], "done", done_at=_utc(2026, 3, 6), has_rework=False),
    ]
    prs = [
        PRFact("pr1", "u1", _utc(2026, 3, 1), changes_requested_count=2),
        PRFact("pr2", "u2", _utc(2026, 3, 2), changes_requested_count=1),
    ]
    facts = GraphFacts("proj_1", window=win, task_assignments=tasks, prs=prs)
    res = compute_rework(facts, window=win)

    assert res.status == "ok"
    assert res.values["tasks_done"] == 5
    assert res.values["tasks_with_rework"] == 2
    assert res.values["rework_rate"] == 0.4  # 2/5
    assert res.values["prs_with_multiple_changes_requested"] == 1


def test_pr_first_review_and_merge_time():
    win = parse_window("2026-03-01", "2026-03-15", timezone="UTC")

    # 5 PRs com durações controladas:
    # 2h, 4h, 8h, 24h, 48h para primeiro review
    # 4h, 8h, 16h, 48h, 96h para merge
    prs = [
        PRFact("pr1", "u1", _utc(2026, 3, 1, 10), first_review_at=_utc(2026, 3, 1, 12), merged_at=_utc(2026, 3, 1, 14)),
        PRFact("pr2", "u1", _utc(2026, 3, 2, 10), first_review_at=_utc(2026, 3, 2, 14), merged_at=_utc(2026, 3, 2, 18)),
        PRFact("pr3", "u2", _utc(2026, 3, 3, 10), first_review_at=_utc(2026, 3, 3, 18), merged_at=_utc(2026, 3, 4, 2)),
        PRFact("pr4", "u2", _utc(2026, 3, 4, 10), first_review_at=_utc(2026, 3, 5, 10), merged_at=_utc(2026, 3, 6, 10)),
        PRFact("pr5", "u3", _utc(2026, 3, 5, 10), first_review_at=_utc(2026, 3, 7, 10), merged_at=_utc(2026, 3, 9, 10)),
    ]
    facts = GraphFacts("proj_1", window=win, prs=prs)

    res_review = compute_pr_time_to_first_review(facts, window=win)
    assert res_review.status == "ok"
    assert res_review.values["n"] == 5
    # [2.0, 4.0, 8.0, 24.0, 48.0] -> mediana = 8.0
    assert res_review.values["median_h"] == 8.0

    res_merge = compute_pr_time_to_merge(facts, window=win)
    assert res_merge.status == "ok"
    assert res_merge.values["n"] == 5
    # [4.0, 8.0, 16.0, 48.0, 96.0] -> mediana = 16.0
    assert res_merge.values["median_h"] == 16.0


def test_wip_and_bottleneck_risk():
    people = [
        PersonFact("alice", "Alice"),
        PersonFact("bob", "Bob"),
        PersonFact("carol", "Carol"),
    ]

    # Alice tem 5 tarefas em doing/review (wip=5 > 4)
    # Alice deu 5 de 6 reviews (share = 5/6 = 83.3% >= 50%)
    # PRs revisados por Alice demoram 50h (p85 >= 48h)
    # Resultado esperado para Alice: 3 sinais ativos -> level='high'
    tasks = [
        TaskAssignmentFact("t1", ["alice"], "doing"),
        TaskAssignmentFact("t2", ["alice"], "review"),
        TaskAssignmentFact("t3", ["alice"], "doing"),
        TaskAssignmentFact("t4", ["alice"], "doing"),
        TaskAssignmentFact("t5", ["alice"], "doing"),
        TaskAssignmentFact("t6", ["bob"], "doing"),
        TaskAssignmentFact("t7", ["carol"], "done"),
    ]

    prs = [
        PRFact("pr1", "bob", created_at=_utc(2026, 3, 1, 0)),
        PRFact("pr2", "bob", created_at=_utc(2026, 3, 2, 0)),
        PRFact("pr3", "carol", created_at=_utc(2026, 3, 3, 0)),
        PRFact("pr4", "carol", created_at=_utc(2026, 3, 4, 0)),
        PRFact("pr5", "carol", created_at=_utc(2026, 3, 5, 0)),
        PRFact("pr6", "alice", created_at=_utc(2026, 3, 6, 0)),
    ]

    reviews = [
        ReviewFact("alice", "bob", "pr1", "APPROVED", _utc(2026, 3, 3, 2)),  # 50h espera
        ReviewFact("alice", "bob", "pr2", "APPROVED", _utc(2026, 3, 4, 2)),  # 50h espera
        ReviewFact("alice", "carol", "pr3", "APPROVED", _utc(2026, 3, 5, 2)),  # 50h espera
        ReviewFact("alice", "carol", "pr4", "APPROVED", _utc(2026, 3, 6, 2)),  # 50h espera
        ReviewFact("alice", "carol", "pr5", "APPROVED", _utc(2026, 3, 7, 2)),  # 50h espera
        ReviewFact("bob", "alice", "pr6", "APPROVED", _utc(2026, 3, 6, 4)),   # 4h espera
    ]

    facts = GraphFacts(
        project_id="proj_1",
        people=people,
        task_assignments=tasks,
        prs=prs,
        reviews=reviews,
    )

    # WIP
    wip_res = compute_wip_per_person(facts)
    assert wip_res.status == "ok"
    assert wip_res.values["alice"] == 5
    assert wip_res.values["bob"] == 1
    assert wip_res.values["carol"] == 0

    # Gargalo
    risk_res = compute_bottleneck_risk(facts, wip_limit=4)
    assert risk_res.status == "ok"
    alice_risk = risk_res.values["alice"]
    assert alice_risk["level"] == "high"
    assert set(alice_risk["active_signals"]) == {"review_share", "wip_high", "pr_wait_high"}
    assert alice_risk["wip"] == 5
    assert alice_risk["review_share"] == round(5 / 6.0, 4)

    bob_risk = risk_res.values["bob"]
    assert bob_risk["level"] == "low"
    assert len(bob_risk["active_signals"]) == 0


def test_critical_dependencies():
    # Tarefa t1 bloqueia t2, t3, t4 (bloqueia 3 tarefas >= 2)
    deps = [
        TaskDependencyFact(blocking_task_uid="t1", blocked_task_uid="t2"),
        TaskDependencyFact(blocking_task_uid="t1", blocked_task_uid="t3"),
        TaskDependencyFact(blocking_task_uid="t1", blocked_task_uid="t4"),
    ]
    tasks = [
        TaskAssignmentFact("t1", ["u1"], "doing", created_at=_utc(2026, 3, 1)),
        TaskAssignmentFact("t2", ["u2"], "doing", blocked=True, blocked_since=_utc(2026, 3, 5)),
        TaskAssignmentFact("t3", ["u2"], "doing", blocked=True, blocked_since=_utc(2026, 3, 8)),
        TaskAssignmentFact("t4", ["u3"], "doing", blocked=True, blocked_since=_utc(2026, 3, 10)),
    ]
    facts = GraphFacts(project_id="proj_1", task_assignments=tasks, task_dependencies=deps)

    now = _utc(2026, 3, 15)
    res = compute_critical_dependencies(facts, now=now)

    assert res.status == "ok"
    assert len(res.values["blocking_tasks"]) == 1
    assert res.values["blocking_tasks"][0]["task_uid"] == "t1"
    assert res.values["blocking_tasks"][0]["blocked_count"] == 3
    assert res.values["blocked_tasks_count"] == 3
    # A mais antiga é t2 bloqueada em 5 de março. now=15 de março -> 10 dias
    assert res.values["oldest_blocked_days"] == 10.0


def test_compute_all_flow_metrics():
    win = parse_window("2026-03-01", "2026-03-15", timezone="UTC")
    facts = GraphFacts(
        project_id="proj_1",
        window=win,
        people=[PersonFact("u1", "User 1")],
    )
    bundle = compute_all_flow_metrics(facts, window=win)

    expected_keys = {
        "flow.completion_rate",
        "flow.late_rate",
        "flow.lead_time",
        "flow.cycle_time",
        "flow.rework",
        "flow.pr_time_to_first_review",
        "flow.pr_time_to_merge",
        "flow.wip_per_person",
        "flow.bottleneck_risk",
        "flow.critical_dependencies",
    }
    assert set(bundle.keys()) == expected_keys
