from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ..graph.collab_graph import ALLOWED_REVIEW_STATES, CollabGraph
from ..graph.facts import GraphFacts
from .graph_metrics import MetricResult

DEFAULT_SCORE_WEIGHTS = {
    "participation": 0.25,
    "collaboration": 0.30,
    "delivery": 0.30,
    "quality": 0.15,
}


@dataclass
class PersonCounters:
    commits: int = 0
    prs_opened: int = 0
    prs_merged: int = 0
    reviews_given: int = 0
    reviews_received: int = 0
    comments: int = 0
    tasks_assigned: int = 0
    tasks_done: int = 0
    distinct_collaborators: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "commits": self.commits,
            "prs_opened": self.prs_opened,
            "prs_merged": self.prs_merged,
            "reviews_given": self.reviews_given,
            "reviews_received": self.reviews_received,
            "comments": self.comments,
            "tasks_assigned": self.tasks_assigned,
            "tasks_done": self.tasks_done,
            "distinct_collaborators": self.distinct_collaborators,
        }


def log_norm(count: float | int, max_count: float | int) -> float:
    """x(c) = log1p(c) / log1p(max_equipe(c)) (0 se max=0). SPEC §7.4."""
    if max_count <= 0 or count <= 0:
        return 0.0
    return math.log1p(float(count)) / math.log1p(float(max_count))


def extract_person_counters(
    facts: GraphFacts,
    collab: CollabGraph,
) -> dict[str, PersonCounters]:
    """Calcula os contadores brutos de atividade na janela por Person ativa (SPEC §7.4 B)."""
    counters: dict[str, PersonCounters] = {
        uid: PersonCounters() for uid in collab.active_nodes
    }

    # Commits
    for c in facts.commits:
        if not c.is_merge and c.author_person_uid in counters:
            counters[c.author_person_uid].commits += 1

    # PRs
    for pr in facts.prs:
        if pr.author_person_uid in counters:
            counters[pr.author_person_uid].prs_opened += 1
            if pr.merged_at is not None or pr.state.lower() == "merged":
                counters[pr.author_person_uid].prs_merged += 1

    # Reviews (dados e recebidos)
    for r in facts.reviews:
        if r.state.upper() in ALLOWED_REVIEW_STATES:
            if r.reviewer_person_uid in counters:
                counters[r.reviewer_person_uid].reviews_given += 1
            if r.pr_author_person_uid in counters:
                counters[r.pr_author_person_uid].reviews_received += 1

    # Comentários
    for c in facts.comments:
        if c.commenter_person_uid in counters:
            counters[c.commenter_person_uid].comments += 1

    # Tarefas atribuídas e concluídas
    for t in facts.task_assignments:
        is_done = t.status_category.lower() == "done"
        for uid in t.person_uids:
            if uid in counters:
                counters[uid].tasks_assigned += 1
                if is_done:
                    counters[uid].tasks_done += 1

    # Colaboradores distintos (grau em G_u)
    for uid in collab.active_nodes:
        if uid in collab.G_u:
            counters[uid].distinct_collaborators = len(collab.G_u[uid])

    return counters


def compute_person_counters(
    facts: GraphFacts,
    collab: CollabGraph,
) -> tuple[MetricResult, dict[str, PersonCounters]]:
    """Métrica person.counters com resumo dos contadores brutos."""
    counters = extract_person_counters(facts, collab)
    values = {uid: cnt.to_dict() for uid, cnt in counters.items()}

    res = MetricResult(
        id="person.counters",
        scope="person",
        status="ok",
        unit="count",
        values=values,
        inputs={"n_nodes": len(collab.active_nodes)},
    )
    return res, counters


def compute_participation(
    collab: CollabGraph,
    counters: dict[str, PersonCounters],
) -> MetricResult:
    """
    person.participation:
    100 · (0.15·x(commits) + 0.25·x(prs_opened) + 0.25·x(reviews_given) + 0.25·x(tasks_done) + 0.10·x(comments))
    Nulo quando equipe com atividade total = 0.
    """
    n = len(collab.active_nodes)
    if n == 0:
        return MetricResult(
            id="person.participation",
            scope="person",
            status="insufficient_data",
            unit="0-100",
            values=None,
            reason="Nenhuma pessoa ativa na equipe",
        )

    # Obter máximos da equipe para normalização logarítmica
    max_commits = max((c.commits for c in counters.values()), default=0)
    max_prs = max((c.prs_opened for c in counters.values()), default=0)
    max_revs = max((c.reviews_given for c in counters.values()), default=0)
    max_tasks = max((c.tasks_done for c in counters.values()), default=0)
    max_comments = max((c.comments for c in counters.values()), default=0)

    total_activity = max_commits + max_prs + max_revs + max_tasks + max_comments
    if total_activity == 0:
        return MetricResult(
            id="person.participation",
            scope="person",
            status="insufficient_data",
            unit="0-100",
            values=None,
            reason="Equipe sem atividade total no período",
            inputs={"n_nodes": n},
        )

    values = {}
    for uid in collab.active_nodes:
        cnt = counters.get(uid, PersonCounters())
        val = 100.0 * (
            0.15 * log_norm(cnt.commits, max_commits)
            + 0.25 * log_norm(cnt.prs_opened, max_prs)
            + 0.25 * log_norm(cnt.reviews_given, max_revs)
            + 0.25 * log_norm(cnt.tasks_done, max_tasks)
            + 0.10 * log_norm(cnt.comments, max_comments)
        )
        values[uid] = round(min(100.0, max(0.0, val)), 2)

    return MetricResult(
        id="person.participation",
        scope="person",
        status="ok",
        unit="0-100",
        values=values,
        inputs={"n_nodes": n, "total_activity": total_activity},
    )


def compute_collaboration(
    collab: CollabGraph,
    counters: dict[str, PersonCounters],
) -> MetricResult:
    """
    person.collaboration:
    100 · (0.40·x(reviews_given) + 0.20·x(reviews_received) + 0.20·x(comments) + 0.20·dc/(n−1))
    Nulo quando n < 3.
    """
    n = len(collab.active_nodes)
    if n < 3:
        return MetricResult(
            id="person.collaboration",
            scope="person",
            status="insufficient_data",
            unit="0-100",
            values=None,
            reason="Tamanho da amostra insuficiente (n < 3)",
            inputs={"n_nodes": n},
        )

    max_revs_given = max((c.reviews_given for c in counters.values()), default=0)
    max_revs_rcvd = max((c.reviews_received for c in counters.values()), default=0)
    max_comments = max((c.comments for c in counters.values()), default=0)

    denom = float(n - 1)
    values = {}
    for uid in collab.active_nodes:
        cnt = counters.get(uid, PersonCounters())
        dc_ratio = cnt.distinct_collaborators / denom if denom > 0 else 0.0
        val = 100.0 * (
            0.40 * log_norm(cnt.reviews_given, max_revs_given)
            + 0.20 * log_norm(cnt.reviews_received, max_revs_rcvd)
            + 0.20 * log_norm(cnt.comments, max_comments)
            + 0.20 * min(1.0, dc_ratio)
        )
        values[uid] = round(min(100.0, max(0.0, val)), 2)

    return MetricResult(
        id="person.collaboration",
        scope="person",
        status="ok",
        unit="0-100",
        values=values,
        inputs={"n_nodes": n},
    )


def compute_delivery(
    facts: GraphFacts,
    collab: CollabGraph,
) -> MetricResult:
    """
    person.delivery:
    100 · min(1, done_planned / planned).
    Caso de borda: se planned == 0 para a pessoa, valor é None (null).
    """
    n = len(collab.active_nodes)
    if n == 0:
        return MetricResult(
            id="person.delivery",
            scope="person",
            status="insufficient_data",
            unit="0-100",
            values=None,
            reason="Nenhuma pessoa ativa na equipe",
        )

    # Determinar regra de planned: R1 se houver due_at na janela ou is_planned explícito; R2 caso contrário
    has_due = any(t.due_at is not None or t.is_planned is not None for t in facts.task_assignments)
    rule_used = "R1" if has_due else "R2"

    planned_by_person: dict[str, int] = defaultdict(int)
    done_planned_by_person: dict[str, int] = defaultdict(int)

    for t in facts.task_assignments:
        is_planned = False
        if rule_used == "R1":
            if t.is_planned is not None:
                is_planned = t.is_planned
            elif t.due_at is not None and facts.window is not None:
                is_planned = facts.window.contains(t.due_at)
            elif t.due_at is not None:
                is_planned = True
        else:
            # R2: tarefa ativa no período
            is_planned = t.status_category.lower() in ("doing", "review", "done")

        if is_planned:
            is_done = t.status_category.lower() == "done"
            for uid in t.person_uids:
                if uid in collab.active_nodes:
                    planned_by_person[uid] += 1
                    if is_done:
                        done_planned_by_person[uid] += 1

    values = {}
    for uid in collab.active_nodes:
        pl = planned_by_person.get(uid, 0)
        if pl == 0:
            values[uid] = None  # planned = 0 -> null
        else:
            dp = done_planned_by_person.get(uid, 0)
            ratio = min(1.0, dp / float(pl))
            values[uid] = round(100.0 * ratio, 2)

    return MetricResult(
        id="person.delivery",
        scope="person",
        status="ok",
        unit="0-100",
        values=values,
        inputs={
            "n_nodes": n,
            "rule": rule_used,
            "planned": dict(planned_by_person),
            "done_planned": dict(done_planned_by_person),
        },
    )


def compute_quality(
    facts: GraphFacts,
    collab: CollabGraph,
) -> MetricResult:
    """
    person.quality:
    100 · (1 − média(componentes não nulos))
    Componentes:
    - pr_changes_requested_ratio (só se >= 3 PRs da pessoa)
    - rework_rate (tarefas voltaram de done/review para doing/todo ÷ concluídas; só se >= 3 concluídas)
    Nulo quando ambos componentes são nulos.
    """
    n = len(collab.active_nodes)
    if n == 0:
        return MetricResult(
            id="person.quality",
            scope="person",
            status="insufficient_data",
            unit="0-100",
            values=None,
            reason="Nenhuma pessoa ativa na equipe",
        )

    # Contagem de PRs e PRs com CHANGES_REQUESTED
    prs_total: dict[str, int] = defaultdict(int)
    prs_changes: dict[str, int] = defaultdict(int)

    for pr in facts.prs:
        if pr.author_person_uid in collab.active_nodes:
            prs_total[pr.author_person_uid] += 1
            if pr.has_changes_requested:
                prs_changes[pr.author_person_uid] += 1

    # Tarefas concluídas e tarefas com rework
    tasks_done_total: dict[str, int] = defaultdict(int)
    tasks_rework_total: dict[str, int] = defaultdict(int)

    for t in facts.task_assignments:
        if t.status_category.lower() == "done":
            for uid in t.person_uids:
                if uid in collab.active_nodes:
                    tasks_done_total[uid] += 1
                    if t.has_rework:
                        tasks_rework_total[uid] += 1

    values = {}
    details = {}
    for uid in collab.active_nodes:
        comps = []
        comp_names = []

        # 1. CHANGES_REQUESTED ratio (>= 3 PRs)
        n_prs = prs_total.get(uid, 0)
        if n_prs >= 3:
            ratio_cr = prs_changes.get(uid, 0) / float(n_prs)
            comps.append(ratio_cr)
            comp_names.append("pr_changes_requested_ratio")

        # 2. Rework rate (>= 3 tarefas concluídas)
        n_done = tasks_done_total.get(uid, 0)
        if n_done >= 3:
            ratio_rework = tasks_rework_total.get(uid, 0) / float(n_done)
            comps.append(ratio_rework)
            comp_names.append("rework_rate")

        if not comps:
            values[uid] = None  # Ambos componentes nulos -> null
            details[uid] = {"used_components": []}
        else:
            mean_penalty = sum(comps) / float(len(comps))
            q_val = 100.0 * (1.0 - mean_penalty)
            values[uid] = round(min(100.0, max(0.0, q_val)), 2)
            details[uid] = {"used_components": comp_names}

    return MetricResult(
        id="person.quality",
        scope="person",
        status="ok",
        unit="0-100",
        values=values,
        inputs={"n_nodes": n, "details": details},
    )


def compute_overall(
    collab: CollabGraph,
    part_res: MetricResult,
    collab_res: MetricResult,
    deliv_res: MetricResult,
    qual_res: MetricResult,
    score_weights: dict[str, float] | None = None,
) -> MetricResult:
    """
    person.overall:
    Σ wᵢ·índiceᵢ / Σ wᵢ apenas sobre índices NÃO NULOS (pesos renormalizados).
    Nulo quando todos os índices são nulos.
    Retorna também used_components por pessoa.
    """
    n = len(collab.active_nodes)
    weights = {**DEFAULT_SCORE_WEIGHTS, **(score_weights or {})}

    values = {}
    used_components = {}

    part_vals = part_res.values if part_res.status == "ok" and isinstance(part_res.values, dict) else {}
    collab_vals = collab_res.values if collab_res.status == "ok" and isinstance(collab_res.values, dict) else {}
    deliv_vals = deliv_res.values if deliv_res.status == "ok" and isinstance(deliv_res.values, dict) else {}
    qual_vals = qual_res.values if qual_res.status == "ok" and isinstance(qual_res.values, dict) else {}

    for uid in collab.active_nodes:
        candidates = [
            ("participation", weights["participation"], part_vals.get(uid)),
            ("collaboration", weights["collaboration"], collab_vals.get(uid)),
            ("delivery", weights["delivery"], deliv_vals.get(uid)),
            ("quality", weights["quality"], qual_vals.get(uid)),
        ]

        active_terms = [
            (name, w, val)
            for name, w, val in candidates
            if val is not None
        ]

        if not active_terms:
            values[uid] = None
            used_components[uid] = []
        else:
            sum_w = sum(w for _, w, _ in active_terms)
            if sum_w <= 0:
                values[uid] = None
                used_components[uid] = []
            else:
                weighted_sum = sum(w * val for _, w, val in active_terms)
                final_score = weighted_sum / sum_w
                values[uid] = round(min(100.0, max(0.0, final_score)), 2)
                used_components[uid] = [name for name, _, _ in active_terms]

    return MetricResult(
        id="person.overall",
        scope="person",
        status="ok",
        unit="0-100",
        values=values,
        inputs={
            "n_nodes": n,
            "weights": weights,
            "used_components": used_components,
        },
    )


def compute_all_person_metrics(
    facts: GraphFacts,
    collab: CollabGraph,
    score_weights: dict[str, float] | None = None,
) -> dict[str, MetricResult]:
    """Calcula todas as métricas individuais por Person (SPEC §7.4 B)."""
    counters_res, counters_map = compute_person_counters(facts, collab)
    part_res = compute_participation(collab, counters_map)
    collab_res = compute_collaboration(collab, counters_map)
    deliv_res = compute_delivery(facts, collab)
    qual_res = compute_quality(facts, collab)
    overall_res = compute_overall(
        collab, part_res, collab_res, deliv_res, qual_res, score_weights=score_weights
    )

    return {
        "person.counters": counters_res,
        "person.participation": part_res,
        "person.collaboration": collab_res,
        "person.delivery": deliv_res,
        "person.quality": qual_res,
        "person.overall": overall_res,
    }
