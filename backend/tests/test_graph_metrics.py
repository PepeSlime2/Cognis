from __future__ import annotations

import networkx as nx
import pytest

from app.graph.collab_graph import CollabGraph
from app.metrics.graph_metrics import (
    compute_all_graph_metrics,
    compute_betweenness,
    compute_centralization,
    compute_closeness,
    compute_community,
    compute_components,
    compute_degree,
    compute_density,
    compute_modularity,
    compute_pagerank,
    compute_shortest_path,
    compute_weighted_degree,
)


def make_collab_helper(nodes: list[str], edges: list[tuple[str, str, float]], min_weight: float = 1.0) -> CollabGraph:
    """Cria uma instância de CollabGraph para teste com topologia exata e pesos controlados."""
    G_d = nx.DiGraph()
    G_u = nx.Graph()
    G_u_prime = nx.Graph()

    for n in sorted(nodes):
        G_d.add_node(n)
        G_u.add_node(n)
        G_u_prime.add_node(n)

    for u, v, w in edges:
        G_d.add_edge(u, v, weight=w)
        # Em grafo não dirigido, somamos se a aresta for informada
        dist = 1.0 / w if w > 0 else float("inf")
        G_u.add_edge(u, v, weight=w, distance=dist)
        if w >= min_weight:
            G_u_prime.add_edge(u, v, weight=w, distance=dist)

    return CollabGraph(
        G_d=G_d,
        G_u=G_u,
        G_u_prime=G_u_prime,
        active_nodes=sorted(nodes),
        edge_breakdown={},
        config={"min_edge_weight": min_weight},
    )


def test_star_graph_hand_calculated_metrics():
    """
    Grafo Estrela S_4: centro C e folhas L1, L2, L3.
    Arestas: (C, L1), (C, L2), (C, L3) todas com peso 1.0.
    n = 4, m = 3.

    Valores calculados à mão:
    - degree: C tem grau 3/(4-1) = 1.0; cada folha tem grau 1/3 = 0.3333.
    - weighted_degree: C tem 3.0; cada folha tem 1.0.
    - betweenness:
        Todos os 3 caminhos entre folhas (L1-L2, L1-L3, L2-L3) passam por C.
        Entre folhas = 0.
        Normalizado para n=4: multiplicador 2/((n-1)(n-2)) = 2/(3*2) = 1/3.
        Contagem bruta de C = 3. Normalizado = 3 * (1/3) = 1.0.
    - closeness:
        Distâncias de C a L1,L2,L3 = 1 cada -> soma = 3. Closeness = (4-1)/3 = 1.0.
        Distâncias de L1: a C é 1, a L2 é 2, a L3 é 2 -> soma = 5. Closeness = 3/5 = 0.6.
    - centralization (Freeman):
        Graus: C=3, L1=1, L2=1, L3=1. Max = 3.
        Soma das diferenças = (3-3) + (3-1) + (3-1) + (3-1) = 0 + 2 + 2 + 2 = 6.
        Denominador = (n-1)(n-2) = 3 * 2 = 6.
        Centralização = 6 / 6 = 1.0 (máxima teórica).
    - density:
        m / (n(n-1)/2) = 3 / 6 = 0.5.
    """
    collab = make_collab_helper(
        nodes=["C", "L1", "L2", "L3"],
        edges=[("C", "L1", 1.0), ("C", "L2", 1.0), ("C", "L3", 1.0)],
    )

    deg = compute_degree(collab)
    assert deg.status == "ok"
    assert deg.values["C"] == 1.0
    assert deg.values["L1"] == pytest.approx(0.3333, abs=1e-4)

    w_deg = compute_weighted_degree(collab)
    assert w_deg.values["C"] == 3.0
    assert w_deg.values["L1"] == 1.0

    bet = compute_betweenness(collab)
    assert bet.values["C"] == 1.0
    assert bet.values["L1"] == 0.0
    assert bet.values["L2"] == 0.0
    assert bet.values["L3"] == 0.0

    clo = compute_closeness(collab)
    assert clo.values["C"] == 1.0
    assert clo.values["L1"] == pytest.approx(0.6, abs=1e-4)

    cent = compute_centralization(collab)
    assert cent.status == "ok"
    assert cent.values == 1.0

    dens = compute_density(collab)
    assert dens.values == 0.5

    comp = compute_components(collab)
    assert comp.values["count"] == 1
    assert comp.values["members"] == [["C", "L1", "L2", "L3"]]


def test_line_graph_p3_hand_calculated():
    """
    Grafo Linha P_3: A - B - C.
    Arestas: (A, B, 1.0), (B, C, 1.0).
    n = 3, m = 2.

    Valores à mão:
    - degree: B=2/(3-1)=1.0; A=1/2=0.5; C=1/2=0.5.
    - betweenness:
        B está no único caminho entre A e C.
        Normalizado para n=3: 2/((2)(1)) = 1.0. Betweenness de B = 1.0; A, C = 0.0.
    - centralization:
        Graus: B=2, A=1, C=1. Max = 2.
        Soma das diferenças: (2-2) + (2-1) + (2-1) = 2.
        Denominador: (3-1)(3-2) = 2 * 1 = 2.
        Centralização: 2 / 2 = 1.0.
    """
    collab = make_collab_helper(
        nodes=["A", "B", "C"],
        edges=[("A", "B", 1.0), ("B", "C", 1.0)],
    )

    deg = compute_degree(collab)
    assert deg.values["B"] == 1.0
    assert deg.values["A"] == 0.5
    assert deg.values["C"] == 0.5

    bet = compute_betweenness(collab)
    assert bet.values["B"] == 1.0
    assert bet.values["A"] == 0.0
    assert bet.values["C"] == 0.0

    cent = compute_centralization(collab)
    assert cent.values == 1.0


def test_disconnected_silos_and_communities():
    """
    Grafo com 2 triângulos completamente desconexos (Silos):
    Triângulo 1: U1, U2, U3 (peso 2.0)
    Triângulo 2: V1, V2, V3 (peso 2.0)
    n = 6.
    """
    edges = [
        ("U1", "U2", 2.0), ("U2", "U3", 2.0), ("U3", "U1", 2.0),
        ("V1", "V2", 2.0), ("V2", "V3", 2.0), ("V3", "V1", 2.0),
    ]
    collab = make_collab_helper(nodes=["U1", "U2", "U3", "V1", "V2", "V3"], edges=edges)

    # Componentes: exatamente 2 componentes de 3 nós
    comps = compute_components(collab)
    assert comps.values["count"] == 2
    assert len(comps.values["members"]) == 2

    # Comunidades: exatamente 2 comunidades (C1 e C2)
    comm_res, comm_list = compute_community(collab)
    assert comm_res.status == "ok"
    assert len(comm_list) == 2
    # Nós de U devem estar na mesma comunidade
    assert comm_res.values["U1"] == comm_res.values["U2"] == comm_res.values["U3"]
    # Nós de V devem estar na mesma comunidade
    assert comm_res.values["V1"] == comm_res.values["V2"] == comm_res.values["V3"]
    assert comm_res.values["U1"] != comm_res.values["V1"]

    # Modularidade deve ser alta (> 0.4)
    mod = compute_modularity(collab, communities=comm_list)
    assert mod.status == "ok"
    assert mod.values > 0.4

    # Shortest path intra-cluster: U1 -> U2 (distância 1/2.0 = 0.5)
    sp_intra = compute_shortest_path(collab, "U1", "U2")
    assert sp_intra.status == "ok"
    assert sp_intra.values["path"] == ["U1", "U2"]
    assert sp_intra.values["distance"] == 0.5

    # Shortest path inter-cluster: U1 -> V1 (desconexo -> not_applicable)
    sp_inter = compute_shortest_path(collab, "U1", "V1")
    assert sp_inter.status == "not_applicable"
    assert "Não há caminho" in sp_inter.reason


def test_insufficient_sample_size():
    """Valida retorno obrigatório de status 'insufficient_data' quando n < 3."""
    collab = make_collab_helper(nodes=["A", "B"], edges=[("A", "B", 1.0)])

    deg = compute_degree(collab)
    assert deg.status == "insufficient_data"
    assert "n < 3" in deg.reason

    bet = compute_betweenness(collab)
    assert bet.status == "insufficient_data"

    dens = compute_density(collab)
    assert dens.status == "insufficient_data"

    comm, _ = compute_community(collab)
    assert comm.status == "insufficient_data"


def test_compute_all_graph_metrics_bundle():
    """Valida execução unificada das 10 métricas de grafos para um grafo válido."""
    collab = make_collab_helper(
        nodes=["A", "B", "C", "D"],
        edges=[("A", "B", 1.0), ("B", "C", 1.0), ("C", "D", 1.0), ("D", "A", 1.0)],
    )

    metrics = compute_all_graph_metrics(collab)

    expected_keys = {
        "graph.degree",
        "graph.weighted_degree",
        "graph.betweenness",
        "graph.closeness",
        "graph.pagerank",
        "graph.community",
        "graph.modularity",
        "graph.density",
        "graph.components",
        "graph.centralization",
    }
    assert set(metrics.keys()) == expected_keys
    for k, v in metrics.items():
        assert v.status == "ok", f"Métrica {k} falhou com status {v.status}: {v.reason}"
