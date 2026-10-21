from __future__ import annotations

import io
from pathlib import Path

import networkx as nx
import pytest

from app.reports.charts import (
    COMMUNITY_COLORS,
    image_bytes_to_base64,
    render_bar_chart,
    render_graph_image,
)

PNG_MAGIC_HEADER = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def sample_graph() -> nx.Graph:
    """Cria um grafo não-dirigido simulando uma equipe com 2 comunidades."""
    G = nx.Graph()
    # Comunidade 1 (backend)
    G.add_edge("dev1", "dev2", weight=3.5)
    G.add_edge("dev2", "dev3", weight=2.0)
    G.add_edge("dev1", "dev3", weight=1.5)

    # Comunidade 2 (frontend)
    G.add_edge("dev4", "dev5", weight=4.0)

    # Elo ponte entre comunidades
    G.add_edge("dev2", "dev4", weight=1.0)
    return G


def test_render_graph_image_generates_valid_png(sample_graph: nx.Graph, tmp_path: Path):
    """Critério de aceite F8.2: PNG legível com cores por comunidade."""
    out_file = tmp_path / "grafo_teste.png"
    labels = {
        "dev1": "Diego",
        "dev2": "Bruno",
        "dev3": "Felipe",
        "dev4": "Ana",
        "dev5": "Carla",
    }
    comms = {
        "dev1": "C1",
        "dev2": "C1",
        "dev3": "C1",
        "dev4": "C2",
        "dev5": "C2",
    }
    metrics = {
        "dev1": 0.4,
        "dev2": 0.8,
        "dev3": 0.2,
        "dev4": 0.6,
        "dev5": 0.3,
    }

    png_bytes = render_graph_image(
        graph=sample_graph,
        node_labels=labels,
        communities=comms,
        node_metrics=metrics,
        output_path=out_file,
    )

    # Validação do cabeçalho binário PNG
    assert png_bytes.startswith(PNG_MAGIC_HEADER)
    assert len(png_bytes) > 5000  # Imagem renderizada em alta resolução

    # Validação do arquivo persistido em disco
    assert out_file.exists()
    assert out_file.stat().st_size == len(png_bytes)


def test_render_graph_image_anonymized(sample_graph: nx.Graph):
    """Testa renderização com anonimização ativada."""
    labels = {"dev1": "Diego", "dev2": "Bruno"}
    png_bytes = render_graph_image(
        graph=sample_graph,
        node_labels=labels,
        anonymize=True,
    )
    assert png_bytes.startswith(PNG_MAGIC_HEADER)
    assert len(png_bytes) > 2000


def test_render_graph_image_empty():
    """Testa tratamento gracioso de grafo vazio."""
    empty_g = nx.Graph()
    png_bytes = render_graph_image(empty_g)
    assert png_bytes.startswith(PNG_MAGIC_HEADER)


def test_render_bar_chart(tmp_path: Path):
    """Testa renderização de gráfico de barras com rótulos e valores."""
    out_file = tmp_path / "bar_chart.png"
    categories = ["Bruno", "Diego", "Ana", "Carla", "Felipe"]
    values = [14, 8, 7, 5, 1]

    png_bytes = render_bar_chart(
        categories=categories,
        values=values,
        title="Revisões de Código por Integrante",
        xlabel="Desenvolvedor",
        ylabel="Total de Reviews",
        output_path=out_file,
    )

    assert png_bytes.startswith(PNG_MAGIC_HEADER)
    assert out_file.exists()
    assert out_file.stat().st_size == len(png_bytes)


def test_image_bytes_to_base64():
    """Testa conversão de bytes para data URI base64."""
    fake_png = PNG_MAGIC_HEADER + b"data12345"
    uri = image_bytes_to_base64(fake_png)
    assert uri.startswith("data:image/png;base64,")
    assert len(uri) > 30
