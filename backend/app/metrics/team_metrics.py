from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from ..graph.collab_graph import CollabGraph
from ..graph.facts import GraphFacts
from .graph_metrics import MetricResult, compute_community, compute_modularity


def gini_coefficient(values: list[float | int]) -> float:
    """
    Fórmula de Gini conforme SPEC §7.4 C:
    (2 · Σ i·xᵢ) / (n · Σx) − (n+1)/n
    com x ordenado crescente (1-indexed).
    Validado:
    [1, 1, 1, 1] -> 0.0
    [0, 0, 0, 10] -> 0.75
    """
    n = len(values)
    if n == 0:
        return 0.0
    total = float(sum(values))
    if total == 0:
        return 0.0

    sorted_x = sorted(float(v) for v in values)
    # i varia de 1 a n
    weighted_sum = sum((idx + 1) * val for idx, val in enumerate(sorted_x))
    gini = (2.0 * weighted_sum) / (n * total) - (float(n + 1) / float(n))
    return round(min(1.0, max(0.0, gini)), 4)


def compute_interaction_intensity(collab: CollabGraph) -> MetricResult:
    """
    team.interaction_intensity:
    Soma dos pesos das arestas de G_u total ÷ pessoas ativas (SPEC §7.4 C).
    Nulo quando n < 2.
    """
    n = len(collab.active_nodes)
    if n < 2:
        return MetricResult(
            id="team.interaction_intensity",
            scope="team",
            status="insufficient_data",
            unit="score",
            values=None,
            reason="Tamanho da amostra insuficiente (n < 2)",
            inputs={"n_nodes": n},
        )

    G = collab.G_u
    total_edge_weight = sum(data.get("weight", 0.0) for _, _, data in G.edges(data=True))
    mean_intensity = total_edge_weight / float(n)

    # Detalhe por par de colaboradores
    pair_weights = {
        f"{u}<->{v}": round(data.get("weight", 0.0), 2)
        for u, v, data in sorted(G.edges(data=True), key=lambda e: (e[0], e[1]))
    }

    return MetricResult(
        id="team.interaction_intensity",
        scope="team",
        status="ok",
        unit="score",
        values={
            "mean_intensity": round(mean_intensity, 2),
            "total_weight": round(total_edge_weight, 2),
            "pairs": pair_weights,
        },
        inputs={"n_nodes": n, "n_edges": G.number_of_edges()},
    )


def compute_knowledge_concentration(
    facts: GraphFacts,
    min_changes_module: int = 5,
) -> MetricResult:
    """
    team.knowledge_concentration:
    Por módulo na janela: changes[autor] = Σ(additions + deletions).
    top1_share = max/Σ.
    bus_factor = menor k de autores cujo acumulado das maiores alterações >= 0.5 do total.
    Resumo de equipe: % de módulos com bus_factor = 1 (considerando módulos com >= min_changes_module commits).
    """
    # Agrupar alterações por módulo e autor
    module_author_changes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    module_commits_count: dict[str, int] = defaultdict(int)

    for mc in facts.module_commits:
        ch = int(mc.additions + mc.deletions)
        # Se commit não tiver additions/deletions explícitas, conta pelo menos 1 unidade de alteração
        ch = max(1, ch)
        module_author_changes[mc.module_path][mc.person_uid] += ch
        module_commits_count[mc.module_path] += 1

    modules_detail = {}
    eligible_modules = []
    bus_factor_1_count = 0

    for mod_path, authors_dict in module_author_changes.items():
        total_changes = sum(authors_dict.values())
        n_commits = module_commits_count[mod_path]
        n_authors = len(authors_dict)

        # Ordenar alterações decrescentes
        sorted_changes = sorted(authors_dict.values(), reverse=True)
        top1 = sorted_changes[0] if sorted_changes else 0
        top1_share = top1 / float(total_changes) if total_changes > 0 else 1.0

        # Calcular bus_factor: menor k cujo acumulado >= 0.5 do total
        k = 0
        accum = 0
        half_total = total_changes * 0.5
        for ch_val in sorted_changes:
            accum += ch_val
            k += 1
            if accum >= half_total:
                break
        bus_factor = max(1, k)

        is_eligible = n_commits >= min_changes_module
        if is_eligible:
            eligible_modules.append(mod_path)
            if bus_factor == 1:
                bus_factor_1_count += 1

        modules_detail[mod_path] = {
            "bus_factor": bus_factor,
            "top1_share": round(top1_share, 4),
            "n_authors": n_authors,
            "n_commits": n_commits,
            "total_changes": total_changes,
            "is_eligible": is_eligible,
        }

    pct_bus_factor_1 = (
        round(bus_factor_1_count / float(len(eligible_modules)), 4)
        if eligible_modules
        else 0.0
    )

    return MetricResult(
        id="team.knowledge_concentration",
        scope="module",
        status="ok",
        unit="0-1",
        values={
            "pct_modules_bus_factor_1": pct_bus_factor_1,
            "bus_factor_1_count": bus_factor_1_count,
            "eligible_modules_count": len(eligible_modules),
            "modules": modules_detail,
        },
        inputs={"min_changes_module": min_changes_module},
    )


def compute_activity_distribution(
    facts: GraphFacts,
    collab: CollabGraph,
) -> MetricResult:
    """
    team.activity_distribution:
    Gini de tasks_assigned entre pessoas ativas e Gini de reviews_given;
    Entropia normalizada H/ln(n).
    Nulo quando n < 3 ou soma de atividades = 0.
    """
    n = len(collab.active_nodes)
    if n < 3:
        return MetricResult(
            id="team.activity_distribution",
            scope="team",
            status="insufficient_data",
            unit="0-1",
            values=None,
            reason="Tamanho da amostra insuficiente (n < 3)",
            inputs={"n_nodes": n},
        )

    tasks_by_person: dict[str, int] = defaultdict(int)
    for t in facts.task_assignments:
        for uid in t.person_uids:
            if uid in collab.active_nodes:
                tasks_by_person[uid] += 1

    reviews_by_person: dict[str, int] = defaultdict(int)
    for r in facts.reviews:
        if r.reviewer_person_uid in collab.active_nodes:
            reviews_by_person[r.reviewer_person_uid] += 1

    tasks_list = [tasks_by_person[uid] for uid in collab.active_nodes]
    reviews_list = [reviews_by_person[uid] for uid in collab.active_nodes]

    total_tasks = sum(tasks_list)
    total_reviews = sum(reviews_list)

    if total_tasks == 0 and total_reviews == 0:
        return MetricResult(
            id="team.activity_distribution",
            scope="team",
            status="insufficient_data",
            unit="0-1",
            values=None,
            reason="Nenhuma atividade registrada na equipe para cálculo de distribuição",
            inputs={"n_nodes": n},
        )

    gini_tasks = gini_coefficient(tasks_list) if total_tasks > 0 else 0.0
    gini_reviews = gini_coefficient(reviews_list) if total_reviews > 0 else 0.0

    # Entropia normalizada H / ln(n)
    total_combined = [t + r for t, r in zip(tasks_list, reviews_list)]
    sum_combined = sum(total_combined)
    if sum_combined > 0 and n > 1:
        entropy = 0.0
        for val in total_combined:
            if val > 0:
                p = val / float(sum_combined)
                entropy -= p * math.log(p)
        normalized_entropy = round(min(1.0, max(0.0, entropy / math.log(n))), 4)
    else:
        normalized_entropy = 0.0

    return MetricResult(
        id="team.activity_distribution",
        scope="team",
        status="ok",
        unit="0-1",
        values={
            "gini_tasks": gini_tasks,
            "gini_reviews": gini_reviews,
            "normalized_entropy": normalized_entropy,
        },
        inputs={
            "n_nodes": n,
            "total_tasks": total_tasks,
            "total_reviews": total_reviews,
        },
    )


def compute_isolation(
    facts: GraphFacts,
    collab: CollabGraph,
    min_activity: int = 5,
) -> MetricResult:
    """
    team.isolation:
    isolation_index = 1 − dc/(n−1).
    flag=true se dc <= 1 e pessoa tem >= min_activity eventos na janela (padrão 5).
    Pessoa com 0 eventos -> status='inactive' (não é 'isolada').
    Nulo quando n < 3.
    """
    n = len(collab.active_nodes)
    if n < 3:
        return MetricResult(
            id="team.isolation",
            scope="person",
            status="insufficient_data",
            unit="0-1",
            values=None,
            reason="Tamanho da amostra insuficiente (n < 3)",
            inputs={"n_nodes": n},
        )

    # Contar total de eventos por pessoa na janela
    events_count: dict[str, int] = defaultdict(int)

    for c in facts.commits:
        if c.author_person_uid in collab.active_nodes:
            events_count[c.author_person_uid] += 1

    for mc in facts.module_commits:
        if mc.person_uid in collab.active_nodes:
            events_count[mc.person_uid] += 1

    for pr in facts.prs:
        if pr.author_person_uid in collab.active_nodes:
            events_count[pr.author_person_uid] += 1

    for r in facts.reviews:
        if r.reviewer_person_uid in collab.active_nodes:
            events_count[r.reviewer_person_uid] += 1
        if r.pr_author_person_uid in collab.active_nodes:
            events_count[r.pr_author_person_uid] += 1

    for cm in facts.comments:
        if cm.commenter_person_uid in collab.active_nodes:
            events_count[cm.commenter_person_uid] += 1

    for t in facts.task_assignments:
        for uid in t.person_uids:
            if uid in collab.active_nodes:
                events_count[uid] += 1

    denom = float(n - 1)
    values = {}
    isolated_members = []

    for uid in collab.active_nodes:
        dc = len(collab.G_u[uid]) if uid in collab.G_u else 0
        ev_total = events_count[uid]

        idx = round(1.0 - (dc / denom), 4) if denom > 0 else 0.0

        if ev_total == 0:
            person_status = "inactive"
            is_isolated = False
        else:
            person_status = "active"
            is_isolated = (dc <= 1) and (ev_total >= min_activity)

        if is_isolated:
            isolated_members.append(uid)

        values[uid] = {
            "isolation_index": idx,
            "is_isolated": is_isolated,
            "distinct_collaborators": dc,
            "events_count": ev_total,
            "status": person_status,
        }

    return MetricResult(
        id="team.isolation",
        scope="person",
        status="ok",
        unit="0-1",
        values=values,
        inputs={
            "n_nodes": n,
            "min_activity": min_activity,
            "isolated_count": len(isolated_members),
            "isolated_members": isolated_members,
        },
    )


def compute_bridges(
    collab: CollabGraph,
    communities: list[set[str]] | None = None,
) -> MetricResult:
    """
    team.bridges:
    Coeficiente de participação P = 1 − Σ_c (k_ic / k_i)².
    onde k_ic = peso das arestas da pessoa i para a comunidade c, e k_i = peso total de arestas de i.
    Nulo/not_applicable quando menos de 2 comunidades.
    """
    n = len(collab.active_nodes)
    if communities is None or len(communities) < 2:
        comm_res, comm_list = compute_community(collab)
        if comm_res.status != "ok" or len(comm_list) < 2:
            return MetricResult(
                id="team.bridges",
                scope="person",
                status="not_applicable",
                unit="0-1",
                values=None,
                reason="Menos de 2 comunidades identificadas na equipe",
                inputs={"n_nodes": n},
            )
        communities = comm_list

    # Mapear cada nó para o índice de sua comunidade
    node_to_comm: dict[str, int] = {}
    for c_idx, comm in enumerate(communities):
        for node in comm:
            node_to_comm[node] = c_idx

    G = collab.G_u
    values = {}

    for uid in collab.active_nodes:
        if uid not in G:
            values[uid] = 0.0
            continue

        neighbors = G[uid]
        k_i = sum(data.get("weight", 0.0) for data in neighbors.values())

        if k_i <= 0:
            values[uid] = 0.0
            continue

        comm_weights: dict[int, float] = defaultdict(float)
        for neighbor_uid, data in neighbors.items():
            c_idx = node_to_comm.get(neighbor_uid, -1)
            comm_weights[c_idx] += data.get("weight", 0.0)

        sum_sq = sum((w / k_i) ** 2 for w in comm_weights.values())
        p_coef = max(0.0, 1.0 - sum_sq)
        values[uid] = round(p_coef, 4)

    return MetricResult(
        id="team.bridges",
        scope="person",
        status="ok",
        unit="0-1",
        values=values,
        inputs={"n_nodes": n, "n_communities": len(communities)},
    )


def compute_cross_community_share(
    collab: CollabGraph,
    communities: list[set[str]] | None = None,
) -> MetricResult:
    """
    team.cross_community_share:
    Σ pesos entre comunidades / Σ pesos totais.
    Nulo/not_applicable quando menos de 2 comunidades.
    """
    if communities is None or len(communities) < 2:
        comm_res, comm_list = compute_community(collab)
        if comm_res.status != "ok" or len(comm_list) < 2:
            return MetricResult(
                id="team.cross_community_share",
                scope="team",
                status="not_applicable",
                unit="0-1",
                values=None,
                reason="Menos de 2 comunidades identificadas na equipe",
            )
        communities = comm_list

    node_to_comm: dict[str, int] = {}
    for c_idx, comm in enumerate(communities):
        for node in comm:
            node_to_comm[node] = c_idx

    G = collab.G_u
    total_weight = 0.0
    cross_weight = 0.0

    for u, v, data in G.edges(data=True):
        w = data.get("weight", 0.0)
        total_weight += w
        c_u = node_to_comm.get(u, -1)
        c_v = node_to_comm.get(v, -2)
        if c_u != c_v:
            cross_weight += w

    share = round(cross_weight / total_weight, 4) if total_weight > 0 else 0.0

    return MetricResult(
        id="team.cross_community_share",
        scope="team",
        status="ok",
        unit="0-1",
        values=share,
        inputs={
            "total_weight": round(total_weight, 2),
            "cross_weight": round(cross_weight, 2),
            "n_communities": len(communities),
        },
    )


def compute_review_coverage(facts: GraphFacts) -> MetricResult:
    """
    team.review_coverage:
    PRs mesclados com >= 1 review de não-autor ÷ PRs mesclados.
    Nulo quando < 5 PRs mesclados.
    """
    # Identificar PRs mesclados
    merged_prs = [
        pr for pr in facts.prs
        if pr.merged_at is not None or pr.state.lower() == "merged"
    ]
    n_merged = len(merged_prs)

    if n_merged < 5:
        return MetricResult(
            id="team.review_coverage",
            scope="team",
            status="insufficient_data",
            unit="0-1",
            values=None,
            reason="Tamanho da amostra insuficiente (< 5 PRs mesclados)",
            inputs={"merged_prs_count": n_merged},
        )

    # Identificar autores dos PRs
    pr_authors = {pr.pr_uid: pr.author_person_uid for pr in merged_prs}

    # Verificar se receberam review de outra pessoa
    reviewed_prs = set()
    for r in facts.reviews:
        if r.pr_uid in pr_authors:
            if r.reviewer_person_uid != pr_authors[r.pr_uid]:
                reviewed_prs.add(r.pr_uid)

    coverage = len(reviewed_prs) / float(n_merged)
    return MetricResult(
        id="team.review_coverage",
        scope="team",
        status="ok",
        unit="0-1",
        values=round(coverage, 4),
        inputs={"merged_prs": n_merged, "reviewed_merged_prs": len(reviewed_prs)},
    )


def compute_all_team_metrics(
    facts: GraphFacts,
    collab: CollabGraph,
    min_changes_module: int = 5,
    min_activity: int = 5,
) -> dict[str, MetricResult]:
    """Calcula todas as métricas de estrutura e colaboração da equipe (SPEC §7.4 C)."""
    comm_res, comm_list = compute_community(collab)

    return {
        "team.interaction_intensity": compute_interaction_intensity(collab),
        "team.knowledge_concentration": compute_knowledge_concentration(
            facts, min_changes_module=min_changes_module
        ),
        "team.activity_distribution": compute_activity_distribution(facts, collab),
        "team.isolation": compute_isolation(facts, collab, min_activity=min_activity),
        "team.bridges": compute_bridges(collab, communities=comm_list),
        "team.cross_community_share": compute_cross_community_share(collab, communities=comm_list),
        "team.review_coverage": compute_review_coverage(facts),
    }
