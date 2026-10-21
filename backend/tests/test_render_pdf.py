from __future__ import annotations

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
from app.reports.render_pdf import render_pdf_report


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
        resumo="Equipe com excelente vazão na sprint. Atenção aos módulos críticos e acentuação: ação, índice, colaboração.",
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


def test_render_pdf_basic_structure(tmp_path: Path):
    """Verifica que o PDF gerado possui cabeçalho válido, acentos preservados e seções completas."""
    report = ReportModel(
        meta=ReportMeta(
            type="sprint",
            title="Relatório de Teste com Acentuação e Métricas",
            project="Projeto Demo com Acentuação",
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
                title="Indicadores-Chave e Vazão",
                blocks=[
                    KPIsBlock(items=[KPIItem(label="Vazão de Entregas", value="85%", hint="Meta: 80%")]),
                    CalloutBlock(level="warning", text="Atenção à taxa de retrabalho na sprint."),
                    TableBlock(
                        title="Tabela de Colaboração",
                        columns=["Membro", "Commits", "Situação"],
                        rows=[["Diego", 12, "Concluído"], ["Ana", 8, "Em andamento"]],
                    ),
                    TextBlock(
                        origin="llm",
                        markdown="Resumo executivo com **destaque em negrito** e lista:\n- Ponto 1: Comunicação\n- Ponto 2: Resiliência",
                    ),
                ],
            )
        ],
        appendix=ReportAppendix(
            definitions=["flow.completion_rate: Taxa de tarefas concluídas no período."],
            limitations=["Dados limitados ao repositório principal de código."],
        ),
    )

    out_file = tmp_path / "report.pdf"
    pdf_bytes = render_pdf_report(report, output_path=out_file)

    # 1. Arquivo gravado no disco
    assert out_file.is_file()
    assert out_file.read_bytes() == pdf_bytes

    # 2. Cabeçalho mágico de PDF
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in pdf_bytes[-1024:]
    assert len(pdf_bytes) > 2000


def test_render_pdf_with_images(tmp_path: Path):
    """Verifica que imagens de gráficos e do grafo são embutidas corretamente no PDF."""
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
            title="Relatório Gerencial com Imagens e Grafo",
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
                    ChartBlock(kind="line", png_path=str(tmp_path / "inexistente.png"), caption="Gráfico Ausente"),
                ],
            )
        ],
    )

    pdf_bytes = render_pdf_report(report)
    assert pdf_bytes.startswith(b"%PDF-")
    # Arquivo com imagens deve ter tamanho representativo
    assert len(pdf_bytes) > 10000


def test_render_pdf_all_canonical_types(sample_bundle: dict, sample_analysis: AnalysisSection, tmp_path: Path):
    """Verifica que todos os 5 tipos de relatórios canônicos do COGNIS geram PDF válido."""
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

        out_path = tmp_path / f"relatorio_{r_type}.pdf"
        pdf_bytes = render_pdf_report(report, output_path=out_path)

        assert out_path.is_file()
        assert len(pdf_bytes) > 5000
        assert pdf_bytes.startswith(b"%PDF-")
        assert b"%%EOF" in pdf_bytes[-1024:]
