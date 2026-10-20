from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import networkx as nx

from .collab_graph import CollabGraph


@dataclass
class MetricResult:
    """
    Contrato padronizado de resultado de métrica (SPEC §7.2).
    """

    id: str
    scope: str  # "person" | "team" | "module" | "task" | "pair"
    status: str  # "ok" | "insufficient_data" | "not_applicable"
    unit: str
    values: Any
    reason: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    formula_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope,
            "status": self.status,
            "unit": self.unit,
            "values": self.values,
            "reason": self.reason,
            "inputs": self.inputs,
            "formula_version": self.formula_version,
        }


def _check_min_sample_person(collab: CollabGraph, metric_id: str, unit: str) -> MetricResult | None:
    n = len(collab.active_nodes)
    if n < 3:
        return MetricResult(
            id=metric_id,
            scope="person",
            status="insufficient_data",
            unit=unit,
            values=None,
            reason="Tamanho da amostra insuficiente (n < 3)",
            inputs={"n_nodes": n, "n_edges": collab.G_u.number_of_edges()},
        )
    return None


def compute_degree(collab: CollabGraph) -> MetricResult:
    """graph.degree: grau normalizado de vizinhos distintos (len(G_u[u]) / (n-1))."""
    failed = _check_min_sample_person(collab, "graph.degree", "0-1")
    if failed:
        return failed

    G = collab.G_u
    n = len(collab.active_nodes)
    denom = n - 1
    values = {node: round(len(G[node]) / denom, 4) for node in collab.active_nodes}
    raw_counts = {node: len(G[node]) for node in collab.active_nodes}

    return MetricResult(
        id="graph.degree",
        scope="person",
        status="ok",
        unit="0-1",
        values=values,
        inputs={"n_nodes": n, "n_edges": G.number_of_edges(), "raw_degrees": raw_counts},
    )


def compute_weighted_degree(collab: CollabGraph) -> MetricResult:
    """graph.weighted_degree: soma dos pesos das arestas incidentes em G_u."""
    failed = _check_min_sample_person(collab, "graph.weighted_degree", "score")
    if failed:
        return failed

    G = collab.G_u
    values = {
        node: round(float(G.degree(node, weight="weight")), 4)
        for node in collab.active_nodes
    }

    return MetricResult(
        id="graph.weighted_degree",
        scope="person",
        status="ok",
        unit="score",
        values=values,
        inputs={"n_nodes": len(collab.active_nodes), "n_edges": G.number_of_edges()},
    )


def compute_betweenness(collab: CollabGraph) -> MetricResult:
    """graph.betweenness: intermediação normalizada ponderada pela distância (1/weight)."""
    failed = _check_min_sample_person(collab, "graph.betweenness", "0-1")
    if failed:
        return failed

    G = collab.G_u
    # nx.betweenness_centrality normaliza por 2 / ((n-1)(n-2)) para grafos não dirigidos
    raw = nx.betweenness_centrality(G, weight="distance", normalized=True)
    values = {node: round(float(raw.get(node, 0.0)), 4) for node in collab.active_nodes}

    return MetricResult(
        id="graph.betweenness",
        scope="person",
        status="ok",
        unit="0-1",
        values=values,
        inputs={"n_nodes": len(collab.active_nodes), "n_edges": G.number_of_edges()},
    )


def compute_closeness(collab: CollabGraph) -> MetricResult:
    """graph.closeness: proximidade ponderada pela distância (wf_improved=True trata grafos desconexos)."""
    failed = _check_min_sample_person(collab, "graph.closeness", "0-1")
    if failed:
        return failed

    G = collab.G_u
    raw = nx.closeness_centrality(G, distance="distance", wf_improved=True)
    values = {node: round(float(raw.get(node, 0.0)), 4) for node in collab.active_nodes}

    return MetricResult(
        id="graph.closeness",
        scope="person",
        status="ok",
        unit="0-1",
        values=values,
        inputs={"n_nodes": len(collab.active_nodes), "n_edges": G.number_of_edges()},
    )


def _safe_pagerank(G: nx.DiGraph, alpha: float = 0.85, weight: str = "weight") -> dict[Any, float]:
    try:
        return nx.pagerank(G, alpha=alpha, weight=weight)
    except (ModuleNotFoundError, ImportError):
        from networkx.algorithms.link_analysis.pagerank_alg import _pagerank_python
        return _pagerank_python(G, alpha=alpha, weight=weight)


def compute_pagerank(collab: CollabGraph) -> MetricResult:
    """graph.pagerank: PageRank estrutural dirigido em G_d ponderado pelo peso."""
    failed = _check_min_sample_person(collab, "graph.pagerank", "0-1")
    if failed:
        return failed

    G_d = collab.G_d
    n = len(collab.active_nodes)
    if G_d.number_of_edges() == 0:
        values = {node: round(1.0 / n, 4) for node in collab.active_nodes}
    else:
        raw = _safe_pagerank(G_d, alpha=0.85, weight="weight")
        values = {node: round(float(raw.get(node, 0.0)), 4) for node in collab.active_nodes}

    return MetricResult(
        id="graph.pagerank",
        scope="person",
        status="ok",
        unit="0-1",
        values=values,
        inputs={"n_nodes": n, "n_edges": G_d.number_of_edges()},
    )


def compute_community(collab: CollabGraph) -> tuple[MetricResult, list[set[str]]]:
    """
    graph.community: detecção de comunidades Louvain (seed=42).
    Rótulos C1, C2... ordenados por tamanho decrescente (empate -> menor uid).
    min_sample: n >= 4 e >= 1 aresta.
    """
    n = len(collab.active_nodes)
    m = collab.G_u.number_of_edges()

    if n < 4 or m == 0:
        return (
            MetricResult(
                id="graph.community",
                scope="person",
                status="insufficient_data",
                unit="label",
                values=None,
                reason="Tamanho da amostra insuficiente (n < 4 ou sem arestas)",
                inputs={"n_nodes": n, "n_edges": m},
            ),
            [],
        )

    communities = nx.community.louvain_communities(
        collab.G_u, weight="weight", resolution=1.0, seed=42
    )

    # Ordenar comunidades: decrescente por tamanho; em caso de empate, menor uid lexicográfico
    sorted_comm = sorted(
        communities,
        key=lambda comm: (-len(comm), sorted(list(comm))[0] if comm else ""),
    )

    values = {}
    for idx, comm in enumerate(sorted_comm, start=1):
        label = f"C{idx}"
        for member in comm:
            values[member] = label

    # Garantir que todos os active_nodes têm atribuição
    for node in collab.active_nodes:
        if node not in values:
            values[node] = "C0"

    result = MetricResult(
        id="graph.community",
        scope="person",
        status="ok",
        unit="label",
        values=values,
        inputs={"n_nodes": n, "n_edges": m, "n_communities": len(sorted_comm)},
    )
    return result, sorted_comm


def compute_modularity(
    collab: CollabGraph,
    communities: list[set[str]] | None = None,
) -> MetricResult:
    """graph.modularity: modularidade da partição de comunidades em G_u."""
    n = len(collab.active_nodes)
    m = collab.G_u.number_of_edges()

    if n < 4 or m == 0:
        return MetricResult(
            id="graph.modularity",
            scope="team",
            status="insufficient_data",
            unit="score",
            values=None,
            reason="Tamanho da amostra insuficiente (n < 4 ou sem arestas)",
            inputs={"n_nodes": n, "n_edges": m},
        )

    if communities is None or len(communities) == 0:
        comm_res, comm_list = compute_community(collab)
        if comm_res.status != "ok":
            return MetricResult(
                id="graph.modularity",
                scope="team",
                status="insufficient_data",
                unit="score",
                values=None,
                reason=comm_res.reason,
                inputs={"n_nodes": n, "n_edges": m},
            )
        communities = comm_list

    try:
        mod = nx.community.modularity(collab.G_u, communities, weight="weight")
        val = round(float(mod), 4)
        status = "ok"
        reason = None
    except Exception as err:
        val = None
        status = "insufficient_data"
        reason = f"Erro no cálculo de modularidade: {err}"

    return MetricResult(
        id="graph.modularity",
        scope="team",
        status=status,
        unit="score",
        values=val,
        reason=reason,
        inputs={"n_nodes": n, "n_edges": m, "n_communities": len(communities)},
    )


def compute_density(collab: CollabGraph) -> MetricResult:
    """graph.density: densidade de G_u' (apenas arestas com peso >= min_edge_weight)."""
    n = len(collab.active_nodes)
    if n < 3:
        return MetricResult(
            id="graph.density",
            scope="team",
            status="insufficient_data",
            unit="0-1",
            values=None,
            reason="Tamanho da amostra insuficiente (n < 3)",
            inputs={"n_nodes": n},
        )

    val = round(float(nx.density(collab.G_u_prime)), 4)
    return MetricResult(
        id="graph.density",
        scope="team",
        status="ok",
        unit="0-1",
        values=val,
        inputs={
            "n_nodes": n,
            "n_edges_filtered": collab.G_u_prime.number_of_edges(),
            "min_edge_weight": collab.config.get("min_edge_weight", 1.0),
        },
    )


def compute_components(collab: CollabGraph) -> MetricResult:
    """graph.components: componentes conectados em G_u'."""
    n = len(collab.active_nodes)
    if n == 0:
        return MetricResult(
            id="graph.components",
            scope="team",
            status="insufficient_data",
            unit="count",
            values=None,
            reason="Nenhum colaborador ativo no grafo",
            inputs={"n_nodes": 0},
        )

    raw_components = list(nx.connected_components(collab.G_u_prime))
    # Ordenar componentes por tamanho decrescente, e nós internamente em ordem alfabética
    sorted_components = [
        sorted(list(c))
        for c in sorted(raw_components, key=lambda c: (-len(c), sorted(list(c))[0] if c else ""))
    ]

    return MetricResult(
        id="graph.components",
        scope="team",
        status="ok",
        unit="count",
        values={
            "count": len(sorted_components),
            "members": sorted_components,
        },
        inputs={
            "n_nodes": n,
            "n_edges_filtered": collab.G_u_prime.number_of_edges(),
        },
    )


def compute_centralization(collab: CollabGraph) -> MetricResult:
    """
    graph.centralization: Centralização de grau de Freeman sobre G_u'.
    Fórmula: Σ(max_deg - deg_i) / ((n-1)(n-2))
    min_sample: n >= 3.
    """
    n = len(collab.active_nodes)
    if n < 3:
        return MetricResult(
            id="graph.centralization",
            scope="team",
            status="insufficient_data",
            unit="0-1",
            values=None,
            reason="Tamanho da amostra insuficiente (n < 3)",
            inputs={"n_nodes": n},
        )

    G = collab.G_u_prime
    degrees = [G.degree(node) for node in collab.active_nodes]
    max_deg = max(degrees) if degrees else 0

    denom = (n - 1) * (n - 2)
    if denom == 0:
        val = 0.0
    else:
        diff_sum = sum(max_deg - d for d in degrees)
        val = round(float(diff_sum / denom), 4)

    return MetricResult(
        id="graph.centralization",
        scope="team",
        status="ok",
        unit="0-1",
        values=val,
        inputs={
            "n_nodes": n,
            "max_deg": max_deg,
            "denominator": denom,
        },
    )


def compute_shortest_path(collab: CollabGraph, from_uid: str, to_uid: str) -> MetricResult:
    """
    graph.shortest_path: caminho mais curto ponderado pela distância (1/weight) em G_u.
    Sem caminho -> status 'not_applicable'.
    """
    G = collab.G_u
    if from_uid not in G or to_uid not in G:
        return MetricResult(
            id="graph.shortest_path",
            scope="pair",
            status="not_applicable",
            unit="distance",
            values=None,
            reason="Um ou ambos os nós não existem no grafo",
            inputs={"from_uid": from_uid, "to_uid": to_uid},
        )

    if from_uid == to_uid:
        return MetricResult(
            id="graph.shortest_path",
            scope="pair",
            status="ok",
            unit="distance",
            values={"path": [from_uid], "distance": 0.0},
            inputs={"from_uid": from_uid, "to_uid": to_uid},
        )

    try:
        path = nx.shortest_path(G, source=from_uid, target=to_uid, weight="distance")
        dist = nx.shortest_path_length(G, source=from_uid, target=to_uid, weight="distance")
        return MetricResult(
            id="graph.shortest_path",
            scope="pair",
            status="ok",
            unit="distance",
            values={"path": path, "distance": round(float(dist), 4)},
            inputs={"from_uid": from_uid, "to_uid": to_uid},
        )
    except nx.NetworkXNoPath:
        return MetricResult(
            id="graph.shortest_path",
            scope="pair",
            status="not_applicable",
            unit="distance",
            values=None,
            reason="Não há caminho entre os nós informados",
            inputs={"from_uid": from_uid, "to_uid": to_uid},
        )


def compute_all_graph_metrics(collab: CollabGraph) -> dict[str, MetricResult]:
    """Calcula todas as 10 métricas padrão de análise de grafos (SPEC §7.4 A)."""
    comm_res, comm_list = compute_community(collab)

    results = {
        "graph.degree": compute_degree(collab),
        "graph.weighted_degree": compute_weighted_degree(collab),
        "graph.betweenness": compute_betweenness(collab),
        "graph.closeness": compute_closeness(collab),
        "graph.pagerank": compute_pagerank(collab),
        "graph.community": comm_res,
        "graph.modularity": compute_modularity(collab, communities=comm_list),
        "graph.density": compute_density(collab),
        "graph.components": compute_components(collab),
        "graph.centralization": compute_centralization(collab),
    }
    return results
