from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from .facts import GraphFacts

DEFAULT_EDGE_WEIGHTS = {
    "review": 1.0,           # máx 3 por (u, PR)
    "comment": 0.5,          # máx 5 por (u, alvo)
    "shared_task": 1.0,      # bidirecional
    "pr_closes_task": 0.5,   # u fecha task de v (v != u)
    "shared_module": 0.25,   # cada um com >= 2 commits no módulo, bidirecional
}
DEFAULT_MIN_EDGE_WEIGHT = 1.0
ALLOWED_REVIEW_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "COMMENTED"})


@dataclass
class CollabGraph:
    """
    Representação do grafo de colaboração de uma equipe (SPEC §7.3).
    - G_d: Grafo dirigido ponderado (weight)
    - G_u: Grafo não dirigido ponderado (weight, distance = 1/weight)
    - G_u_prime: Grafo não dirigido filtrado por min_edge_weight
    - active_nodes: Lista de uids das Person ativas
    - edge_breakdown: Detalhes das interações por par dirigido (u, v)
    """

    G_d: nx.DiGraph
    G_u: nx.Graph
    G_u_prime: nx.Graph
    active_nodes: list[str]
    edge_breakdown: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


def build_collab_graph(
    facts: GraphFacts,
    config: dict[str, Any] | None = None,
    include_bots: bool = False,
) -> CollabGraph:
    """
    Constrói o grafo de colaboração a partir dos fatos em memória, de forma pura e determinística.
    Conforme SPEC §7.3.
    """
    cfg = config or {}
    weights = {**DEFAULT_EDGE_WEIGHTS, **cfg.get("edge_weights", {})}
    min_edge_weight = float(cfg.get("min_edge_weight", DEFAULT_MIN_EDGE_WEIGHT))

    # 1. Identificar pessoas elegíveis (excluindo bots e excluded se include_bots=False)
    eligible_persons: dict[str, str] = {}
    for p in facts.people:
        if not include_bots and (p.is_bot or p.excluded):
            continue
        eligible_persons[p.uid] = p.display_name

    # 2. Identificar nós ativos (>= 1 evento ou com tarefa aberta atribuída)
    active_uids: set[str] = set()

    # Reviews
    for r in facts.reviews:
        if r.reviewer_person_uid in eligible_persons:
            active_uids.add(r.reviewer_person_uid)
        if r.pr_author_person_uid in eligible_persons:
            active_uids.add(r.pr_author_person_uid)

    # Comentários
    for c in facts.comments:
        if c.commenter_person_uid in eligible_persons:
            active_uids.add(c.commenter_person_uid)
        if c.target_author_person_uid in eligible_persons:
            active_uids.add(c.target_author_person_uid)

    # Tarefas
    for t in facts.task_assignments:
        for u in t.person_uids:
            if u in eligible_persons:
                active_uids.add(u)

    # PR closes tasks
    for pr_close in facts.pr_closes_tasks:
        if pr_close.pr_author_person_uid in eligible_persons:
            active_uids.add(pr_close.pr_author_person_uid)
        if pr_close.task_assignee_person_uid in eligible_persons:
            active_uids.add(pr_close.task_assignee_person_uid)

    # Commits
    for mc in facts.module_commits:
        if mc.person_uid in eligible_persons:
            active_uids.add(mc.person_uid)

    for c in facts.commits:
        if c.author_person_uid in eligible_persons:
            active_uids.add(c.author_person_uid)

    for pr in facts.prs:
        if pr.author_person_uid in eligible_persons:
            active_uids.add(pr.author_person_uid)

    # Se não houver eventos, mas existirem pessoas elegíveis, manter as cadastradas como isoladas
    if not active_uids and eligible_persons:
        active_uids = set(eligible_persons.keys())

    # Estruturas para acumular peso dirigido u -> v
    directed_weights: dict[tuple[str, str], float] = defaultdict(float)
    breakdown: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: defaultdict(float))

    def add_interaction(u: str, v: str, kind: str, weight: float, count: int = 1) -> None:
        if u == v:  # Auto-interações são descartadas
            return
        if u not in active_uids or v not in active_uids:
            return
        directed_weights[(u, v)] += weight
        breakdown[(u, v)][kind] += weight
        breakdown[(u, v)][f"{kind}_count"] += count

    # 3. Calcular interações dirigidas conforme tabela §7.3

    # (a) Reviews: u enviou review em PR de v (máx 3 por (u, PR))
    # Agrupar reviews por (reviewer, author, pr_uid)
    reviews_by_pair_pr: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in facts.reviews:
        if r.state.upper() not in ALLOWED_REVIEW_STATES:
            continue
        reviews_by_pair_pr[(r.reviewer_person_uid, r.pr_author_person_uid, r.pr_uid)] += 1

    for (u, v, _pr_id), raw_count in reviews_by_pair_pr.items():
        capped_count = min(raw_count, 3)
        add_interaction(u, v, "review", capped_count * weights["review"], count=capped_count)

    # (b) Comentários: u comentou item de v (máx 5 por (u, alvo))
    comments_by_pair_target: dict[tuple[str, str, str], int] = defaultdict(int)
    for c in facts.comments:
        comments_by_pair_target[(c.commenter_person_uid, c.target_author_person_uid, c.target_uid)] += 1

    for (u, v, _target_id), raw_count in comments_by_pair_target.items():
        capped_count = min(raw_count, 5)
        add_interaction(u, v, "comment", capped_count * weights["comment"], count=capped_count)

    # (c) Mesma Task: u e v são ambos responsáveis pela mesma Task (bidirecional)
    for t in facts.task_assignments:
        assignees = [uid for uid in t.person_uids if uid in active_uids]
        for i in range(len(assignees)):
            for j in range(i + 1, len(assignees)):
                u, v = assignees[i], assignees[j]
                add_interaction(u, v, "shared_task", weights["shared_task"])
                add_interaction(v, u, "shared_task", weights["shared_task"])

    # (d) PR de u fecha Task cujo responsável é v (v != u, via FECHA)
    for pr_close in facts.pr_closes_tasks:
        u = pr_close.pr_author_person_uid
        v = pr_close.task_assignee_person_uid
        add_interaction(u, v, "pr_closes_task", weights["pr_closes_task"])

    # (e) Módulos em comum: u e v alteraram o mesmo Module na janela, cada um com >= 2 commits (bidirecional)
    # Contar commits por (person_uid, module_path)
    module_commits_count: dict[tuple[str, str], int] = defaultdict(int)
    for mc in facts.module_commits:
        module_commits_count[(mc.person_uid, mc.module_path)] += 1

    # Identificar autores com >= 2 commits por módulo
    authors_by_module: dict[str, list[str]] = defaultdict(list)
    for (person_uid, module_path), count in module_commits_count.items():
        if count >= 2 and person_uid in active_uids:
            authors_by_module[module_path].append(person_uid)

    for _mod_path, authors in authors_by_module.items():
        if len(authors) < 2:
            continue
        for i in range(len(authors)):
            for j in range(i + 1, len(authors)):
                u, v = authors[i], authors[j]
                add_interaction(u, v, "shared_module", weights["shared_module"])
                add_interaction(v, u, "shared_module", weights["shared_module"])

    # 4. Construir Grafos NetworkX

    # G_d: Grafo dirigido
    G_d = nx.DiGraph()
    for uid in sorted(active_uids):
        display = eligible_persons.get(uid, uid)
        G_d.add_node(uid, display_name=display)

    for (u, v), w in directed_weights.items():
        if w > 0:
            G_d.add_edge(u, v, weight=w)

    # G_u: Grafo não dirigido (weight(u,v) = w(u->v) + w(v->u), distance = 1/weight)
    G_u = nx.Graph()
    for uid in sorted(active_uids):
        display = eligible_persons.get(uid, uid)
        G_u.add_node(uid, display_name=display)

    undirected_pairs: set[frozenset[str]] = {
        frozenset([u, v]) for (u, v), w in directed_weights.items() if w > 0
    }

    for pair in undirected_pairs:
        nodes = list(pair)
        if len(nodes) == 2:
            u, v = nodes[0], nodes[1]
            total_w = directed_weights.get((u, v), 0.0) + directed_weights.get((v, u), 0.0)
            if total_w > 0:
                dist = 1.0 / total_w
                G_u.add_edge(u, v, weight=total_w, distance=dist)

    # G_u_prime: Arestas com weight >= min_edge_weight (para densidade, componentes, centralização)
    G_u_prime = nx.Graph()
    for uid in sorted(active_uids):
        display = eligible_persons.get(uid, uid)
        G_u_prime.add_node(uid, display_name=display)

    for u, v, data in G_u.edges(data=True):
        if data["weight"] >= min_edge_weight:
            G_u_prime.add_edge(u, v, **data)

    return CollabGraph(
        G_d=G_d,
        G_u=G_u,
        G_u_prime=G_u_prime,
        active_nodes=sorted(active_uids),
        edge_breakdown=dict(breakdown),
        config={"edge_weights": weights, "min_edge_weight": min_edge_weight},
    )
