from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any

import numpy as np

from ..graph.facts import GraphFacts, TaskAssignmentFact
from ..metrics.windows import TimeWindow
from .graph_metrics import MetricResult


def _is_task_concluded_in_window(task: TaskAssignmentFact, window: TimeWindow | None) -> bool:
    if task.status_category != "done":
        return False
    if window is None or task.done_at is None:
        return True
    return window.start_utc <= task.done_at < window.end_utc


def compute_completion_rate(
    facts: GraphFacts,
    window: TimeWindow | None = None,
) -> MetricResult:
    """
    flow.completion_rate:
    |planned ∩ done| / |planned| (geral e por pessoa).
    Regra R1: tarefa com due_at ∈ S.
    Regra R2: se o projeto não tem nenhum due_at na janela, tarefas com created_at <= S.end
    que estiveram em doing/review/done.
    insufficient_data se planned < 5.
    """
    win = window or facts.window

    # Verifica se há alguma tarefa com due_at dentro da janela (Regra R1)
    has_due_in_window = False
    if win is not None:
        has_due_in_window = any(
            t.due_at is not None and (win.start_utc <= t.due_at < win.end_utc)
            for t in facts.task_assignments
        )
    else:
        has_due_in_window = any(t.due_at is not None for t in facts.task_assignments)

    rule = "R1" if has_due_in_window else "R2"

    planned_tasks: list[TaskAssignmentFact] = []
    for t in facts.task_assignments:
        if t.is_planned is not None:
            if t.is_planned:
                planned_tasks.append(t)
            continue

        if rule == "R1":
            if t.due_at is not None:
                if win is None or (win.start_utc <= t.due_at < win.end_utc):
                    planned_tasks.append(t)
        else:  # R2
            if win is None:
                if t.status_category in ("doing", "review", "done"):
                    planned_tasks.append(t)
            else:
                if t.created_at is None or t.created_at < win.end_utc:
                    if t.status_category in ("doing", "review", "done"):
                        planned_tasks.append(t)

    n_planned = len(planned_tasks)
    if n_planned < 5:
        return MetricResult(
            id="flow.completion_rate",
            scope="team",
            status="insufficient_data",
            unit="0-1",
            values=None,
            reason="Tamanho da amostra insuficiente (planned < 5)",
            inputs={"rule": rule, "planned_count": n_planned},
        )

    # Identificar quais das tarefas planejadas foram concluídas
    planned_and_done: list[TaskAssignmentFact] = [
        t for t in planned_tasks if _is_task_concluded_in_window(t, win)
    ]

    overall_rate = round(len(planned_and_done) / float(n_planned), 4)

    # Cálculo por pessoa
    person_planned: dict[str, int] = defaultdict(int)
    person_done: dict[str, int] = defaultdict(int)

    for t in planned_tasks:
        for p in t.person_uids:
            person_planned[p] += 1

    for t in planned_and_done:
        for p in t.person_uids:
            person_done[p] += 1

    by_person: dict[str, float] = {}
    for p, count in person_planned.items():
        if count > 0:
            by_person[p] = round(person_done[p] / float(count), 4)

    return MetricResult(
        id="flow.completion_rate",
        scope="team",
        status="ok",
        unit="0-1",
        values={
            "overall": overall_rate,
            "by_person": by_person,
            "planned_count": n_planned,
            "done_count": len(planned_and_done),
        },
        inputs={"rule": rule, "planned_count": n_planned},
    )


def compute_late_rate(
    facts: GraphFacts,
    window: TimeWindow | None = None,
    now: dt.datetime | None = None,
) -> MetricResult:
    """
    flow.late_rate:
    Entre tarefas concluídas com due_at na janela: done_at > due_at ÷ total.
    Mais overdue_open = tarefas abertas com due_at < agora.
    insufficient_data se < 5 concluídas com prazo.
    """
    win = window or facts.window
    current_time = now or (win.end_utc if win is not None else dt.datetime.now(dt.timezone.utc))

    concluded_with_due = [
        t
        for t in facts.task_assignments
        if _is_task_concluded_in_window(t, win) and t.due_at is not None and t.done_at is not None
    ]

    # Contagem de abertas vencidas
    overdue_open_count = sum(
        1
        for t in facts.task_assignments
        if t.status_category != "done"
        and t.due_at is not None
        and t.due_at < current_time
    )

    n_concluded = len(concluded_with_due)
    if n_concluded < 5:
        return MetricResult(
            id="flow.late_rate",
            scope="team",
            status="insufficient_data",
            unit="0-1",
            values=None,
            reason="Tamanho da amostra insuficiente (< 5 tarefas concluídas com prazo)",
            inputs={
                "concluded_with_due_count": n_concluded,
                "overdue_open_count": overdue_open_count,
            },
        )

    late_count = sum(1 for t in concluded_with_due if t.done_at > t.due_at)
    rate = round(late_count / float(n_concluded), 4)

    return MetricResult(
        id="flow.late_rate",
        scope="team",
        status="ok",
        unit="0-1",
        values={
            "late_rate": rate,
            "overdue_open": overdue_open_count,
            "total_concluded_with_due": n_concluded,
            "late_concluded_count": late_count,
        },
        inputs={
            "total_concluded_with_due": n_concluded,
            "overdue_open": overdue_open_count,
        },
    )


def compute_lead_time(
    facts: GraphFacts,
    window: TimeWindow | None = None,
) -> MetricResult:
    """
    flow.lead_time:
    done_at - created_at em dias para tarefas concluídas.
    Retorna median_days, p85_days, n.
    insufficient_data se n < 5.
    """
    win = window or facts.window
    concluded = [
        t
        for t in facts.task_assignments
        if _is_task_concluded_in_window(t, win) and t.created_at is not None and t.done_at is not None
    ]

    durations_days = [
        max(0.0, (t.done_at - t.created_at).total_seconds() / 86400.0)
        for t in concluded
    ]

    n = len(durations_days)
    if n < 5:
        return MetricResult(
            id="flow.lead_time",
            scope="team",
            status="insufficient_data",
            unit="days",
            values=None,
            reason="Tamanho da amostra insuficiente (n < 5)",
            inputs={"n": n},
        )

    median_val = round(float(np.percentile(durations_days, 50)), 2)
    p85_val = round(float(np.percentile(durations_days, 85)), 2)

    return MetricResult(
        id="flow.lead_time",
        scope="team",
        status="ok",
        unit="days",
        values={"median_days": median_val, "p85_days": p85_val, "n": n},
        inputs={"n": n},
    )


def compute_cycle_time(
    facts: GraphFacts,
    window: TimeWindow | None = None,
) -> MetricResult:
    """
    flow.cycle_time:
    done_at - started_at em dias para tarefas concluídas.
    Retorna median_days, p85_days, n.
    insufficient_data se n < 5.
    """
    win = window or facts.window
    concluded = [
        t
        for t in facts.task_assignments
        if _is_task_concluded_in_window(t, win) and t.started_at is not None and t.done_at is not None
    ]

    durations_days = [
        max(0.0, (t.done_at - t.started_at).total_seconds() / 86400.0)
        for t in concluded
    ]

    n = len(durations_days)
    if n < 5:
        return MetricResult(
            id="flow.cycle_time",
            scope="team",
            status="insufficient_data",
            unit="days",
            values=None,
            reason="Tamanho da amostra insuficiente (n < 5)",
            inputs={"n": n},
        )

    median_val = round(float(np.percentile(durations_days, 50)), 2)
    p85_val = round(float(np.percentile(durations_days, 85)), 2)

    return MetricResult(
        id="flow.cycle_time",
        scope="team",
        status="ok",
        unit="days",
        values={"median_days": median_val, "p85_days": p85_val, "n": n},
        inputs={"n": n},
    )


def compute_rework(
    facts: GraphFacts,
    window: TimeWindow | None = None,
) -> MetricResult:
    """
    flow.rework:
    Proporção de tarefas concluídas com retrabalho (has_rework=True),
    mais contagem de PRs com >= 2 rodadas de CHANGES_REQUESTED.
    insufficient_data se tarefas concluídas < 5.
    """
    win = window or facts.window
    done_tasks = [t for t in facts.task_assignments if _is_task_concluded_in_window(t, win)]
    n_done = len(done_tasks)

    if n_done < 5:
        return MetricResult(
            id="flow.rework",
            scope="team",
            status="insufficient_data",
            unit="0-1",
            values=None,
            reason="Tamanho da amostra insuficiente (tarefas concluídas < 5)",
            inputs={"tasks_done": n_done},
        )

    rework_tasks = [t for t in done_tasks if t.has_rework]
    rework_rate = round(len(rework_tasks) / float(n_done), 4)

    prs_with_mult_cr = [p for p in facts.prs if p.changes_requested_count >= 2]

    return MetricResult(
        id="flow.rework",
        scope="team",
        status="ok",
        unit="0-1",
        values={
            "rework_rate": rework_rate,
            "tasks_with_rework": len(rework_tasks),
            "tasks_done": n_done,
            "prs_with_multiple_changes_requested": len(prs_with_mult_cr),
            "prs_analyzed": len(facts.prs),
        },
        inputs={"tasks_done": n_done, "prs_count": len(facts.prs)},
    )


def compute_pr_time_to_first_review(
    facts: GraphFacts,
    window: TimeWindow | None = None,
) -> MetricResult:
    """
    flow.pr_time_to_first_review:
    first_review_at - created_at em horas.
    Retorna median_h, p85_h, n.
    insufficient_data se n < 5.
    """
    win = window or facts.window
    durations_h: list[float] = []

    for p in facts.prs:
        if p.first_review_at is None or p.created_at is None:
            continue
        if win is not None and not (win.start_utc <= p.first_review_at < win.end_utc or win.start_utc <= p.created_at < win.end_utc):
            continue
        durations_h.append(max(0.0, (p.first_review_at - p.created_at).total_seconds() / 3600.0))

    n = len(durations_h)
    if n < 5:
        return MetricResult(
            id="flow.pr_time_to_first_review",
            scope="team",
            status="insufficient_data",
            unit="hours",
            values=None,
            reason="Tamanho da amostra insuficiente (n < 5)",
            inputs={"n": n},
        )

    median_val = round(float(np.percentile(durations_h, 50)), 2)
    p85_val = round(float(np.percentile(durations_h, 85)), 2)

    return MetricResult(
        id="flow.pr_time_to_first_review",
        scope="team",
        status="ok",
        unit="hours",
        values={"median_h": median_val, "p85_h": p85_val, "n": n},
        inputs={"n": n},
    )


def compute_pr_time_to_merge(
    facts: GraphFacts,
    window: TimeWindow | None = None,
) -> MetricResult:
    """
    flow.pr_time_to_merge:
    merged_at - created_at em horas para PRs mesclados.
    Retorna median_h, p85_h, n.
    insufficient_data se n < 5.
    """
    win = window or facts.window
    durations_h: list[float] = []

    for p in facts.prs:
        if p.merged_at is None or p.created_at is None:
            continue
        if win is not None and not (win.start_utc <= p.merged_at < win.end_utc):
            continue
        durations_h.append(max(0.0, (p.merged_at - p.created_at).total_seconds() / 3600.0))

    n = len(durations_h)
    if n < 5:
        return MetricResult(
            id="flow.pr_time_to_merge",
            scope="team",
            status="insufficient_data",
            unit="hours",
            values=None,
            reason="Tamanho da amostra insuficiente (n < 5)",
            inputs={"n": n},
        )

    median_val = round(float(np.percentile(durations_h, 50)), 2)
    p85_val = round(float(np.percentile(durations_h, 85)), 2)

    return MetricResult(
        id="flow.pr_time_to_merge",
        scope="team",
        status="ok",
        unit="hours",
        values={"median_h": median_val, "p85_h": p85_val, "n": n},
        inputs={"n": n},
    )


def compute_wip_per_person(facts: GraphFacts) -> MetricResult:
    """
    flow.wip_per_person:
    Tarefas abertas em 'doing' ou 'review' por responsável.
    """
    wip_counts: dict[str, int] = defaultdict(int)

    # Inicializar todas as pessoas conhecidas com 0
    for person in facts.people:
        if not person.excluded and not person.is_bot:
            wip_counts[person.uid] = 0

    for task in facts.task_assignments:
        if task.status_category in ("doing", "review"):
            for p in task.person_uids:
                wip_counts[p] += 1

    return MetricResult(
        id="flow.wip_per_person",
        scope="person",
        status="ok",
        unit="count",
        values=dict(sorted(wip_counts.items())),
        inputs={"tasks_in_wip": sum(wip_counts.values())},
    )


def compute_bottleneck_risk(
    facts: GraphFacts,
    wip_limit: int = 4,
) -> MetricResult:
    """
    flow.bottleneck_risk:
    Por pessoa, 3 sinais:
    (1) review_share = reviews_given / total_reviews >= 0.5 (e total_reviews >= 6);
    (2) wip > wip_limit (padrão 4);
    (3) p85 de espera de PRs onde a pessoa é revisora >= 48 h.
    Nível: 0 sinais 'low', 1 'medium', >= 2 'high'.
    """
    total_reviews = len(facts.reviews)
    reviews_by_person: dict[str, int] = defaultdict(int)
    for r in facts.reviews:
        reviews_by_person[r.reviewer_person_uid] += 1

    # WIP por pessoa
    wip_res = compute_wip_per_person(facts)
    wip_dict: dict[str, int] = wip_res.values or {}

    # Espera de PRs por revisor
    # Mapear PRs para tempo de espera
    pr_by_uid = {p.pr_uid: p for p in facts.prs}
    reviewer_waits: dict[str, list[float]] = defaultdict(list)

    for r in facts.reviews:
        pr = pr_by_uid.get(r.pr_uid)
        if pr is not None and pr.created_at is not None and r.submitted_at is not None:
            wait_h = max(0.0, (r.submitted_at - pr.created_at).total_seconds() / 3600.0)
            reviewer_waits[r.reviewer_person_uid].append(wait_h)

    # Avaliar pessoas ativas
    results: dict[str, Any] = {}
    candidate_people = [p for p in facts.people if not p.excluded and not p.is_bot]
    if not candidate_people:
        # Pega uids observados em reviews ou wip
        all_uids = set(reviews_by_person.keys()) | set(wip_dict.keys())
    else:
        all_uids = {p.uid for p in candidate_people}

    for uid in sorted(all_uids):
        active_signals: list[str] = []

        # Sinal 1: review_share >= 0.5 (total >= 6)
        rev_count = reviews_by_person.get(uid, 0)
        review_share = round(rev_count / float(total_reviews), 4) if total_reviews > 0 else 0.0
        if total_reviews >= 6 and review_share >= 0.5:
            active_signals.append("review_share")

        # Sinal 2: wip > wip_limit
        person_wip = wip_dict.get(uid, 0)
        if person_wip > wip_limit:
            active_signals.append("wip_high")

        # Sinal 3: p85 espera >= 48h
        waits = reviewer_waits.get(uid, [])
        p85_wait = round(float(np.percentile(waits, 85)), 2) if waits else None
        if p85_wait is not None and p85_wait >= 48.0:
            active_signals.append("pr_wait_high")

        # Nível
        n_signals = len(active_signals)
        level = "high" if n_signals >= 2 else ("medium" if n_signals == 1 else "low")

        results[uid] = {
            "level": level,
            "active_signals": active_signals,
            "review_share": review_share,
            "wip": person_wip,
            "p85_review_wait_h": p85_wait,
        }

    return MetricResult(
        id="flow.bottleneck_risk",
        scope="person",
        status="ok",
        unit="level",
        values=results,
        inputs={"total_reviews": total_reviews, "wip_limit": wip_limit},
    )


def compute_critical_dependencies(
    facts: GraphFacts,
    now: dt.datetime | None = None,
) -> MetricResult:
    """
    flow.critical_dependencies:
    Tarefas que bloqueiam >= 2 outras (BLOQUEADA_POR),
    mais contagem de tarefas blocked=True e idade da mais antiga em dias.
    """
    current_time = now or dt.datetime.now(dt.timezone.utc)

    # Mapear bloqueios
    blocked_by: dict[str, list[str]] = defaultdict(list)
    for dep in facts.task_dependencies:
        blocked_by[dep.blocking_task_uid].append(dep.blocked_task_uid)

    blocking_tasks = []
    for blocking_uid, blocked_list in sorted(blocked_by.items()):
        if len(blocked_list) >= 2:
            blocking_tasks.append({
                "task_uid": blocking_uid,
                "blocked_count": len(blocked_list),
                "blocked_task_uids": sorted(blocked_list),
            })

    # Contar tarefas bloqueadas e verificar a mais antiga
    blocked_tasks_set = {dep.blocked_task_uid for dep in facts.task_dependencies}
    for t in facts.task_assignments:
        if t.blocked and t.status_category != "done":
            blocked_tasks_set.add(t.task_uid)

    blocked_tasks_count = len(blocked_tasks_set)

    # Idade da mais antiga tarefa bloqueada
    oldest_blocked_days: float | None = None
    oldest_dt: dt.datetime | None = None

    for t in facts.task_assignments:
        if t.task_uid in blocked_tasks_set:
            ref_dt = t.blocked_since or t.created_at
            if ref_dt is not None:
                if oldest_dt is None or ref_dt < oldest_dt:
                    oldest_dt = ref_dt

    if oldest_dt is not None:
        oldest_blocked_days = round(max(0.0, (current_time - oldest_dt).total_seconds() / 86400.0), 2)

    return MetricResult(
        id="flow.critical_dependencies",
        scope="team",
        status="ok",
        unit="count/days",
        values={
            "blocking_tasks": blocking_tasks,
            "blocked_tasks_count": blocked_tasks_count,
            "oldest_blocked_days": oldest_blocked_days,
        },
        inputs={
            "dependency_edges_count": len(facts.task_dependencies),
            "blocked_tasks_count": blocked_tasks_count,
        },
    )


def compute_all_flow_metrics(
    facts: GraphFacts,
    window: TimeWindow | None = None,
    wip_limit: int = 4,
    now: dt.datetime | None = None,
) -> dict[str, MetricResult]:
    """
    Executa e agrega todas as métricas do Catálogo D (Fluxo e risco do projeto).
    """
    win = window or facts.window

    return {
        "flow.completion_rate": compute_completion_rate(facts, window=win),
        "flow.late_rate": compute_late_rate(facts, window=win, now=now),
        "flow.lead_time": compute_lead_time(facts, window=win),
        "flow.cycle_time": compute_cycle_time(facts, window=win),
        "flow.rework": compute_rework(facts, window=win),
        "flow.pr_time_to_first_review": compute_pr_time_to_first_review(facts, window=win),
        "flow.pr_time_to_merge": compute_pr_time_to_merge(facts, window=win),
        "flow.wip_per_person": compute_wip_per_person(facts),
        "flow.bottleneck_risk": compute_bottleneck_risk(facts, wip_limit=wip_limit),
        "flow.critical_dependencies": compute_critical_dependencies(facts, now=now),
    }
