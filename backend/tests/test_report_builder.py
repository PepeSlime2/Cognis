from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.llm.schemas import AnalysisSection, Finding, Recommendation
from app.reports.builder import build_report
from app.reports.models import ReportModel


@pytest.fixture
def sample_bundle() -> dict:
    """Fixture de MetricsBundle sintetizado similar ao produzido para o demo seed."""
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
            "flow.pr_time_to_first_review": {"id": "flow.pr_time_to_first_review", "values": 14.5, "unit": "hours", "status": "ok"},
            "flow.pr_time_to_merge": {"id": "flow.pr_time_to_merge", "values": 28.0, "unit": "hours", "status": "ok"},
            "flow.rework": {"id": "flow.rework", "values": 0.15, "unit": "0-1", "status": "ok"},
            "flow.wip_per_person": {"id": "flow.wip_per_person", "values": {"Bruno": 4, "Diego": 2, "Ana": 1}, "unit": "count", "status": "ok"},
            "graph.density": {"id": "graph.density", "values": 0.48, "unit": "0-1", "status": "ok"},
            "graph.modularity": {"id": "graph.modularity", "values": 0.32, "unit": "0-1", "status": "ok"},
            "team.interaction_intensity": {"id": "team.interaction_intensity", "values": 45, "unit": "count", "status": "ok"},
            "team.activity_distribution": {"id": "team.activity_distribution", "values": {"gini": 0.28}, "unit": "gini", "status": "ok"},
            "team.cross_community_share": {"id": "team.cross_community_share", "values": 0.18, "unit": "0-1", "status": "ok"},
            "team.knowledge_concentration": {
                "id": "team.knowledge_concentration",
                "values": {
                    "by_module": {
                        "api/payments": {"bus_factor": 1, "top1_author": "Diego", "top1_share": 1.0},
                        "frontend/auth": {"bus_factor": 2, "top1_author": "Ana", "top1_share": 0.6},
                    }
                },
                "status": "ok",
            },
            "team.isolation": {
                "id": "team.isolation",
                "values": {"isolated_members": ["Felipe"]},
                "status": "ok",
            },
            "team.bridges": {
                "id": "team.bridges",
                "values": {"bridge_members": ["Bruno"]},
                "status": "ok",
            },
            "person.overall": {"id": "person.overall", "values": {"Diego": 0.78, "Bruno": 0.85}, "unit": "0-1", "status": "ok"},
            "person.participation": {"id": "person.participation", "values": {"Diego": 0.35, "Bruno": 0.40}, "unit": "0-1", "status": "ok"},
            "person.collaboration": {"id": "person.collaboration", "values": {"Diego": 0.65, "Bruno": 0.88}, "unit": "0-1", "status": "ok"},
            "person.delivery": {"id": "person.delivery", "values": {"Diego": 0.90, "Bruno": 0.80}, "unit": "0-1", "status": "ok"},
            "person.quality": {"id": "person.quality", "values": {"Diego": 0.82, "Bruno": 0.75}, "unit": "0-1", "status": "ok"},
        },
        "signals": [
            {
                "id": "S1",
                "code": "BUS_FACTOR_1",
                "severity": "high",
                "subject": "Diego",
                "target": "api/payments",
                "title": "Fator Ônibus Crítico em api/payments",
            },
            {
                "id": "S2",
                "code": "REVIEW_CONCENTRATION",
                "severity": "medium",
                "subject": "Bruno",
                "title": "Concentração de Revisões",
            },
        ],
    }


@pytest.fixture
def sample_analysis() -> AnalysisSection:
    return AnalysisSection(
        resumo="A equipe demonstrou boa vazão de entregas, com taxa de conclusão de 82%. Há risco de concentração em revisões.",
        achados=[
            Finding(
                titulo="Concentração de reviews",
                descricao="Bruno concentra parte significativa dos reviews da sprint.",
                severidade="media",
                evidencias=[],
            )
        ],
        recomendacoes=[
            Recommendation(
                acao="Distribuir revisões de PRs",
                justificativa="Reduz o tempo de espera e evita sobrecarga.",
                evidencias=[],
            )
        ],
        limitacoes=["Análise baseada em dados dos últimos 14 dias."],
    )


def test_build_report_sprint(sample_bundle: dict, sample_analysis: AnalysisSection):
    """Testa geração válida do relatório tipo sprint."""
    report = build_report(
        project_id="proj-1",
        project_name="Demo COGNIS",
        bundle=sample_bundle,
        report_type="sprint",
        analysis_section=sample_analysis,
        analysis_source="ollama",
    )
    assert report.meta.type == "sprint"
    assert "Sprint" in report.meta.title
    assert len(report.sections) >= 3

    # Serialização JSON completa e validação de schema
    raw_json = report.model_dump_json()
    parsed = ReportModel.model_validate_json(raw_json)
    assert parsed.meta.type == "sprint"
    assert len(parsed.appendix.definitions) > 0


def test_build_report_gerencial(sample_bundle: dict, sample_analysis: AnalysisSection):
    """Testa geração válida do relatório tipo gerencial com imagem de grafo."""
    report = build_report(
        project_id="proj-1",
        project_name="Demo COGNIS",
        bundle=sample_bundle,
        report_type="gerencial",
        analysis_section=sample_analysis,
        analysis_source="template",
        graph_png_path="/storage/graphs/proj-1.png",
    )
    assert report.meta.type == "gerencial"
    assert "Gerencial" in report.meta.title

    raw_json = report.model_dump_json()
    parsed = ReportModel.model_validate_json(raw_json)
    assert parsed.meta.type == "gerencial"

    # Verificar presença do bloco graph_image
    has_graph = any(b.type == "graph_image" for s in parsed.sections for b in s.blocks)
    assert has_graph is True


def test_build_report_individual(sample_bundle: dict, sample_analysis: AnalysisSection):
    """Testa geração válida do relatório individual com aviso ético e anonimização."""
    report = build_report(
        project_id="proj-1",
        project_name="Demo COGNIS",
        bundle=sample_bundle,
        report_type="individual",
        target_person_name="Diego",
        anonymize=True,
    )
    assert report.meta.type == "individual"
    assert report.meta.anonymized is True
    assert "Pessoa" in (report.meta.person_name or "")

    # Validação do aviso ético (§13.4)
    has_ethical_notice = any(
        b.type == "callout" and "Goodhart" in b.text
        for s in report.sections
        for b in s.blocks
    )
    assert has_ethical_notice is True

    raw_json = report.model_dump_json()
    parsed = ReportModel.model_validate_json(raw_json)
    assert parsed.meta.type == "individual"


def test_build_report_gargalos(sample_bundle: dict, sample_analysis: AnalysisSection):
    """Testa geração válida do relatório tipo gargalos."""
    report = build_report(
        project_id="proj-1",
        project_name="Demo COGNIS",
        bundle=sample_bundle,
        report_type="gargalos",
        analysis_section=sample_analysis,
    )
    assert report.meta.type == "gargalos"

    raw_json = report.model_dump_json()
    parsed = ReportModel.model_validate_json(raw_json)
    assert parsed.meta.type == "gargalos"
    assert len(parsed.sections) >= 3


def test_build_report_colaboracao(sample_bundle: dict, sample_analysis: AnalysisSection):
    """Testa geração válida do relatório tipo colaboração."""
    report = build_report(
        project_id="proj-1",
        project_name="Demo COGNIS",
        bundle=sample_bundle,
        report_type="colaboracao",
        analysis_section=sample_analysis,
        graph_png_path="/storage/graphs/collab.png",
    )
    assert report.meta.type == "colaboracao"

    raw_json = report.model_dump_json()
    parsed = ReportModel.model_validate_json(raw_json)
    assert parsed.meta.type == "colaboracao"


def test_all_five_types_are_valid_json(sample_bundle: dict, sample_analysis: AnalysisSection):
    """Critério de aceite F8.1: JSON válido para cada um dos 5 tipos com o seed."""
    types = ["sprint", "gerencial", "individual", "gargalos", "colaboracao"]
    for r_type in types:
        report = build_report(
            project_id="demo-seed-proj",
            project_name="Demo COGNIS",
            bundle=sample_bundle,
            report_type=r_type,
            analysis_section=sample_analysis,
            target_person_name="Diego",
        )
        json_output = report.model_dump_json()
        assert len(json_output) > 100

        # Carregar como JSON nativo e como ReportModel
        dict_data = json.loads(json_output)
        assert dict_data["meta"]["type"] == r_type
        assert len(dict_data["sections"]) > 0
        assert "definitions" in dict_data["appendix"]
        assert "ethical_note" in dict_data["appendix"]

        validated_model = ReportModel.model_validate(dict_data)
        assert validated_model.meta.type == r_type
