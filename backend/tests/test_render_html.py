from __future__ import annotations

import tempfile
from pathlib import Path

import networkx as nx
import pytest

from app.llm.schemas import AnalysisSection, Finding, Recommendation
from app.reports.builder import build_report
from app.reports.charts import render_bar_chart, render_graph_image
from app.reports.models import (
    CalloutBlock,
    ChartBlock,
    GraphImageBlock,
    KPIItem,
    KPIsBlock,
    ReportAppendix,
    ReportMeta,
    ReportModel,
    ReportSection,
    TableBlock,
    TextBlock,
)
from app.reports.render_html import render_html_report


@pytest.fixture
def sample_bundle() -> dict:
    return {
        "project_id": "proj-seed-demo",
        "data_version": "1.0",
        "window": {
            "from": "2026-09-01",
            "to": "2026-09-14",
            "label": "Sprint 3",
            "timezone": "America/Sao_Paulo",
        },
        "metrics": {
            "flow.completion_rate": {"id": "flow.completion_rate", "values": 0.82, "unit": "0-1", "status": "ok"},
            "flow.late_rate": {"id": "flow.late_rate", "values": 0.12, "unit": "0-1", "status": "ok"},
            "flow.lead_time": {"id": "flow.lead_time", "values": {"median": 4.5, "p85": 7.8}, "unit": "days", "status": "ok"},
            "flow.cycle_time": {"id": "flow.cycle_time", "values": {"median": 2.8, "p85": 5.0}, "unit": "days", "status": "ok"},
            "team.interaction_intensity": {"id": "team.interaction_intensity", "values": 45, "unit": "count", "status": "ok"},
            "person.overall": {"id": "person.overall", "values": {"Diego": 0.78, "Bruno": 0.85}, "unit": "0-1", "status": "ok"},
            "person.participation": {"id": "person.participation", "values": {"Diego": 0.35, "Bruno": 0.40}, "unit": "0-1", "status": "ok"},
            "person.collaboration": {"id": "person.collaboration", "values": {"Diego": 0.65, "Bruno": 0.88}, "unit": "0-1", "status": "ok"},
            "person.delivery": {"id": "person.delivery", "values": {"Diego": 0.90, "Bruno": 0.80}, "unit": "0-1", "status": "ok"},
            "person.quality": {"id": "person.quality", "values": {"Diego": 0.82, "Bruno": 0.75}, "unit": "0-1", "status": "ok"},
            "team.knowledge_concentration": {
                "id": "team.knowledge_concentration",
                "values": {
                    "by_module": {
                        "api/payments": {"bus_factor": 1, "top1_author": "Diego", "top1_share": 1.0},
                    }
                },
                "status": "ok",
            },
        },
        "signals": [
            {
                "id": "S1",
                "code": "BUS_FACTOR_1",
                "severity": "high",
                "subject": "Diego",
                "target": "api/payments",
                "title": "Fator Ônibus Crítico em api/payments",
            }
        ],
    }


@pytest.fixture
def sample_analysis() -> AnalysisSection:
    return AnalysisSection(
        resumo="Equipe com excelente vazão na sprint. Atenção aos módulos críticos.",
        achados=[
            Finding(
                titulo="Concentração de conhecimento",
                descricao="Diego é o único autor em api/payments.",
                severidade="alta",
                evidencias=[],
            )
        ],
        recomendacoes=[
            Recommendation(
                acao="Parear com outro dev",
                justificativa="Aumentar resiliência técnica.",
            )
        ],
    )


def test_render_html_basic_structure(tmp_path: Path):
    """Verifica que o HTML gerado é completo, autocontido e offline."""
    report = ReportModel(
        meta=ReportMeta(
            type="sprint",
            title="Relatório de Teste Sprint 1",
            project="Projeto Demo",
            project_id="proj-1",
            window={"from": "2026-09-01", "to": "2026-09-14", "label": "Sprint 1"},
            generated_at="2026-10-21T18:00:00Z",
            model="llama3.1:8b",
            data_version="1.0",
            anonymized=False,
        ),
        sections=[
            ReportSection(
                id="kpis",
                title="Indicadores-Chave",
                blocks=[
                    KPIsBlock(items=[KPIItem(label="Vazão", value="85%", hint="Meta: 80%")]),
                    CalloutBlock(level="warning", text="Atenção à taxa de retrabalho."),
                    TableBlock(
                        title="Tabela de Colaboradores",
                        columns=["Membro", "Commits"],
                        rows=[["Diego", 12], ["Ana", 8]],
                    ),
                    TextBlock(
                        origin="llm",
                        markdown="Resumo executivo com **destaque** e lista:\n- Ponto 1\n- Ponto 2",
                    ),
                ],
            )
        ],
        appendix=ReportAppendix(
            definitions=["flow.completion_rate: Taxa de tarefas concluídas."],
            limitations=["Dados limitados ao repositório principal."],
        ),
    )

    out_file = tmp_path / "report.html"
    html_content = render_html_report(report, output_path=out_file)

    # 1. Arquivo gravado no disco
    assert out_file.is_file()
    assert out_file.read_text(encoding="utf-8") == html_content

    # 2. Estrutura HTML completa
    assert "<!DOCTYPE html>" in html_content
    assert "<html lang=\"pt-BR\">" in html_content
    assert "Relatório de Teste Sprint 1" in html_content
    assert "Projeto Demo" in html_content
    assert "Sprint 1" in html_content

    # 3. CSS inline e sem chamadas externas a CDNs
    assert "<style>" in html_content
    assert "http://" not in html_content
    assert "https://" not in html_content
    assert "<link rel=\"stylesheet\"" not in html_content

    # 4. Elementos renderizados
    assert "Vazão" in html_content
    assert "85%" in html_content
    assert "Meta: 80%" in html_content
    assert "Atenção à taxa de retrabalho." in html_content
    assert "Tabela de Colaboradores" in html_content
    assert "Diego" in html_content
    assert "<strong>destaque</strong>" in html_content
    assert "<li>Ponto 1</li>" in html_content
    assert "Selo IA Local" in html_content or "Análise IA Local" in html_content

    # 5. Apêndice e nota ética
    assert "Definições das Métricas" in html_content
    assert "flow.completion_rate" in html_content
    assert "Limitações dos Dados" in html_content
    assert "Lei de Goodhart" in html_content


def test_render_html_with_embedded_images(tmp_path: Path):
    """Verifica que gráficos PNG gerados são convertidos para data URI base64 offline."""
    # Gerar imagem de grafo e gráfico de barras
    G = nx.complete_graph(3)
    graph_png = tmp_path / "graph.png"
    render_graph_image(G, node_labels={0: "A", 1: "B", 2: "C"}, output_path=graph_png)

    bar_png = tmp_path / "bar.png"
    render_bar_chart(
        categories=["Diego", "Bruno", "Ana"],
        values=[15, 8, 4],
        output_path=bar_png,
        title="Reviews por Pessoa",
    )

    report = ReportModel(
        meta=ReportMeta(
            type="gerencial",
            title="Relatório Gerencial com Imagens",
            project="Projeto Demo",
            project_id="proj-1",
            window={"from": "2026-09-01", "to": "2026-09-30"},
            generated_at="2026-10-21T18:00:00Z",
            model="llama3.1:8b",
            anonymized=True,
        ),
        sections=[
            ReportSection(
                id="charts",
                title="Visualizações do Grafo e Métricas",
                blocks=[
                    GraphImageBlock(png_path=str(graph_png), caption="Grafo de Colaboração da Equipe"),
                    ChartBlock(kind="bar", png_path=str(bar_png), caption="Distribuição de Reviews"),
                    ChartBlock(kind="line", png_path=str(tmp_path / "inexistente.png"), caption="Gráfico Faltante"),
                ],
            )
        ],
    )

    html_content = render_html_report(report)

    # Verifica data URI base64
    assert "data:image/png;base64," in html_content
    assert 'alt="Grafo de Colaboração da Equipe"' in html_content
    assert 'alt="Distribuição de Reviews"' in html_content
    assert "Grafo de Colaboração da Equipe" in html_content

    # Para imagem inexistente, placeholder seguro sem exceção
    assert "Imagem não disponível" in html_content

    # Badge de anonimização
    assert "Anonimizado" in html_content


def test_render_all_canonical_report_types(sample_bundle: dict, sample_analysis: AnalysisSection, tmp_path: Path):
    """Verifica que todos os 5 tipos de relatórios canônicos do COGNIS geram HTML válido."""
    report_types = ["sprint", "gerencial", "individual", "gargalos", "colaboracao"]

    for r_type in report_types:
        report = build_report(
            report_type=r_type,
            bundle=sample_bundle,
            project_name="COGNIS Demo",
            project_id="proj-seed-demo",
            analysis_section=sample_analysis,
            analysis_source="ollama",
            target_person_uid="Diego" if r_type == "individual" else None,
            target_person_name="Diego" if r_type == "individual" else None,
            anonymize=(r_type == "individual"),
        )

        out_path = tmp_path / f"relatorio_{r_type}.html"
        html_out = render_html_report(report, output_path=out_path)

        assert out_path.is_file()
        assert len(html_out) > 500
        assert "<!DOCTYPE html>" in html_out
        assert "COGNIS" in html_out
        assert "Lei de Goodhart" in html_out

        if r_type == "individual":
            assert "Colaborador" in html_out
            assert "Pessoa" in html_out or "Diego" in html_out
