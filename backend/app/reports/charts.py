from __future__ import annotations

import base64
import io
import math
from pathlib import Path
from typing import Any

# Garantir backend Agg antes de importar pyplot (SPEC §10.3)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx

from ..llm.facts_builder import Anonymizer

# Paleta harmônica e acessível de 10 cores (SPEC §10.3, §12.5)
COMMUNITY_COLORS = [
    "#4f46e5",  # Índigo
    "#059669",  # Esmeralda
    "#d97706",  # Âmbar
    "#dc2626",  # Rubi
    "#7c3aed",  # Violeta
    "#0891b2",  # Ciano
    "#db2777",  # Rosa
    "#ca8a04",  # Ouro
    "#2563eb",  # Azul Royal
    "#65a30d",  # Lima
]


def image_bytes_to_base64(png_bytes: bytes) -> str:
    """Converte bytes PNG para data URI base64 utilizável em HTML offline."""
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def render_graph_image(
    graph: nx.Graph,
    node_labels: dict[str, str] | None = None,
    communities: dict[str, Any] | None = None,
    node_metrics: dict[str, float] | None = None,
    output_path: str | Path | None = None,
    anonymize: bool = False,
    figsize: tuple[float, float] = (10.0, 7.0),
    dpi: int = 200,
    dark_mode: bool = False,
) -> bytes:
    """
    Renderiza a imagem do grafo de colaboração em PNG determinístico (SPEC §10.3).
    - Layout: spring_layout(seed=42)
    - Cores dos nós por comunidade (paleta de 10 cores)
    - Tamanho dos nós proporcional à métrica / grau
    - Arestas com largura proporcional ao peso
    """
    anonymizer = Anonymizer(enabled=anonymize)
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    try:
        # Configurar cores de fundo e eixos
        bg_color = "#0b081e" if dark_mode else "#ffffff"
        text_color = "#f8fafc" if dark_mode else "#1e293b"
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)

        nodes = list(graph.nodes())
        n = len(nodes)

        if n == 0:
            ax.text(
                0.5,
                0.5,
                "Grafo sem nós na janela temporal",
                ha="center",
                va="center",
                color=text_color,
                fontsize=12,
            )
            ax.axis("off")
        else:
            # Layout determinístico com seed=42
            k_val = 1.2 / max(1, math.sqrt(n))
            pos = nx.spring_layout(graph, seed=42, k=k_val)

            # Mapeamento de comunidades para cores
            unique_comms = sorted(
                list(
                    {
                        str(communities.get(node))
                        for node in nodes
                        if communities and node in communities and communities.get(node)
                    }
                )
            )
            comm_to_color: dict[str, str] = {}
            for idx, comm in enumerate(unique_comms):
                comm_to_color[comm] = COMMUNITY_COLORS[idx % len(COMMUNITY_COLORS)]

            node_color_list = []
            for node in nodes:
                c_val = str(communities.get(node)) if communities and node in communities else None
                node_color_list.append(comm_to_color.get(c_val, "#4f46e5"))

            # Tamanhos dos nós
            node_size_list = []
            for node in nodes:
                if node_metrics and node in node_metrics:
                    val = float(node_metrics[node])
                    # Escala entre 700 e 2200
                    size = 700 + min(1500, max(0, val * 1500))
                else:
                    deg = graph.degree(node)
                    size = 700 + min(1500, deg * 120)
                node_size_list.append(size)

            # Larguras das arestas
            edges = list(graph.edges(data=True))
            edge_widths = []
            for _, _, data in edges:
                w = float(data.get("weight", 1.0))
                edge_widths.append(min(6.0, max(1.0, w * 0.8)))

            edge_color = "rgba(255,255,255,0.2)" if dark_mode else "#94a3b8"

            # 1. Desenhar arestas
            nx.draw_networkx_edges(
                graph,
                pos,
                ax=ax,
                width=edge_widths,
                edge_color=edge_color,
                alpha=0.55,
            )

            # 2. Desenhar nós com borda elegante
            nx.draw_networkx_nodes(
                graph,
                pos,
                ax=ax,
                nodelist=nodes,
                node_color=node_color_list,
                node_size=node_size_list,
                edgecolors="#ffffff" if dark_mode else "#334155",
                linewidths=1.5,
                alpha=0.95,
            )

            # 3. Desenhar rótulos legíveis
            labels = {}
            for node in nodes:
                orig_label = (node_labels.get(node) if node_labels else str(node))
                display_label = anonymizer.get_name(orig_label)
                # Quebrar em no máximo 14 chars para não sobrepor
                if len(display_label) > 14:
                    display_label = display_label[:12] + "…"
                labels[node] = display_label

            nx.draw_networkx_labels(
                graph,
                pos,
                ax=ax,
                labels=labels,
                font_size=9,
                font_family="sans-serif",
                font_weight="bold",
                font_color="#ffffff" if dark_mode else "#0f172a",
            )

            # 4. Adicionar legenda de comunidades se houver agrupamentos
            if unique_comms and len(unique_comms) > 1:
                legend_handles = [
                    plt.Line2D(
                        [0],
                        [0],
                        marker="o",
                        color="w",
                        label=f"Comunidade {comm}",
                        markerfacecolor=comm_to_color[comm],
                        markersize=10,
                    )
                    for comm in unique_comms
                ]
                legend = ax.legend(
                    handles=legend_handles,
                    loc="upper left",
                    bbox_to_anchor=(0.02, 0.98),
                    frameon=True,
                    facecolor=bg_color,
                    edgecolor="#64748b",
                    fontsize=8,
                )
                plt.setp(legend.get_texts(), color=text_color)

            ax.axis("off")

        plt.tight_layout()

        # Salvar em BytesIO
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=dpi, facecolor=fig.get_facecolor(), bbox_inches="tight")
        buf.seek(0)
        img_bytes = buf.getvalue()

        # Salvar em arquivo se requisitado
        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(img_bytes)

        return img_bytes
    finally:
        plt.close(fig)


def render_bar_chart(
    categories: list[str],
    values: list[float | int],
    title: str,
    xlabel: str = "",
    ylabel: str = "",
    color: str = "#4f46e5",
    figsize: tuple[float, float] = (8.0, 4.5),
    dpi: int = 150,
    output_path: str | Path | None = None,
    dark_mode: bool = False,
) -> bytes:
    """
    Renderiza um gráfico de barras legível e elegante em PNG (SPEC §10.3).
    """
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    try:
        bg_color = "#0b081e" if dark_mode else "#ffffff"
        text_color = "#f8fafc" if dark_mode else "#1e293b"
        grid_color = "#334155" if dark_mode else "#e2e8f0"

        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)

        bars = ax.bar(categories, values, color=color, width=0.55, edgecolor="#ffffff", linewidth=0.5)

        # Rótulos de valor no topo das barras
        for bar in bars:
            height = bar.get_height()
            label_val = f"{height:.1f}" if isinstance(height, float) and not height.is_integer() else f"{int(height)}"
            ax.annotate(
                label_val,
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8.5,
                fontweight="bold",
                color=text_color,
            )

        ax.set_title(title, fontsize=12, fontweight="bold", pad=12, color=text_color)
        if xlabel:
            ax.set_xlabel(xlabel, fontsize=9.5, fontweight="bold", color=text_color)
        if ylabel:
            ax.set_ylabel(ylabel, fontsize=9.5, fontweight="bold", color=text_color)

        ax.tick_params(colors=text_color, labelsize=8.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(grid_color)
        ax.spines["bottom"].set_color(grid_color)
        ax.yaxis.grid(True, linestyle="--", alpha=0.5, color=grid_color)

        plt.xticks(rotation=15, ha="right")
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=dpi, facecolor=fig.get_facecolor(), bbox_inches="tight")
        buf.seek(0)
        img_bytes = buf.getvalue()

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(img_bytes)

        return img_bytes
    finally:
        plt.close(fig)
