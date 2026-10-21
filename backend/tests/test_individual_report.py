from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import docx
import pytest

from app.llm.schemas import AnalysisSection
from app.reports.builder import build_report
from app.reports.render_docx import render_docx_report
from app.reports.render_html import render_html_report
from app.reports.render_pdf import render_pdf_report


@pytest.fixture
def mock_rich_bundle():
    """Bundle de métricas contendo dados individuais de Diego e da equipe."""
    return {
        "project_id": "demo-proj",
        "data_version": "1.0",
        "window": {
            "from": "2026-09-01",
            "to": "2026-09-30",
            "label": "Sprint 1",
            "timezone": "America/Sao_Paulo",
        },
        "metrics": {
            "person.overall": {
                "id": "person.overall",
                "values": {"diego_uid": 82.5, "bruno_uid": 78.0, "alice_uid": 65.0},
                "inputs": {
                    "used_components": {
                        "diego_uid": ["participation", "collaboration", "delivery", "quality"],
                    }
                },
                "status": "ok",
            },
            "person.participation": {
                "id": "person.participation",
                "values": {"diego_uid": 88.0, "bruno_uid": 90.0, "alice_uid": 70.0},
                "status": "ok",
            },
            "person.collaboration": {
                "id": "person.collaboration",
                "values": {"diego_uid": 75.0, "bruno_uid": 85.0, "alice_uid": 60.0},
                "status": "ok",
            },
            "person.delivery": {
                "id": "person.delivery",
                "values": {"diego_uid": 92.0, "bruno_uid": 80.0, "alice_uid": 75.0},
                "status": "ok",
            },
            "person.quality": {
                "id": "person.quality",
                "values": {"diego_uid": 75.0, "bruno_uid": 70.0, "alice_uid": 55.0},
                "status": "ok",
            },
            "person.counters": {
                "id": "person.counters",
                "values": {
                    "diego_uid": {
                        "commits": 24,
                        "prs_opened": 6,
                        "prs_merged": 5,
                        "reviews_given": 12,
                        "reviews_received": 7,
                        "comments": 15,
                        "tasks_assigned": 8,
                        "tasks_done": 7,
                        "distinct_collaborators": 4,
                    }
                },
                "status": "ok",
            },
            "team.interaction_intensity": {
                "id": "team.interaction_intensity",
                "values": {
                    "mean_intensity": 18.5,
                    "pairs": {
                        "diego_uid<->bruno_uid": 14.5,
                        "diego_uid<->alice_uid": 8.0,
                        "bruno_uid<->alice_uid": 12.0,
                    },
                },
                "status": "ok",
            },
            "team.knowledge_concentration": {
                "id": "team.knowledge_concentration",
                "values": {
                    "by_module": {
                        "api/payments": {
                            "top1_author": "diego_uid",
                            "top1_share": 1.0,
                            "bus_factor": 1,
                        },
                        "frontend/ui": {
                            "top1_author": "alice_uid",
                            "top1_share": 0.8,
                            "bus_factor": 1,
                        },
                    }
                },
                "status": "ok",
            },
            "flow.wip_per_person": {
                "id": "flow.wip_per_person",
                "values": {"diego_uid": 2, "bruno_uid": 3, "alice_uid": 1},
                "status": "ok",
            },
        },
        "signals": [],
    }


def test_individual_report_builder_content(mock_rich_bundle):
    """Verifica que o construtor monta todas as seções e avisos do SPEC §10.1 e §13.4."""
    analysis = AnalysisSection(
        resumo="Diego teve forte atuação em pagamentos e colaborou intensamente com Bruno.",
        achados=[],
        recomendacoes=[],
        limitacoes=[],
    )

    report_model = build_report(
        project_id="proj-1",
        project_name="Demo COGNIS",
        bundle=mock_rich_bundle,
        report_type="individual",
        analysis_section=analysis,
        analysis_source="template",
        target_person_uid="diego_uid",
        target_person_name="Diego Ramos",
        anonymize=False,
    )

    assert report_model.meta.type == "individual"
    assert "Diego Ramos" in report_model.meta.title
    assert report_model.meta.person_name == "Diego Ramos"

    # 1. Verificar presença do aviso de Uso Responsável (§13.4)
    sec_ids = [s.id for s in report_model.sections]
    assert "ethical_notice" in sec_ids
    assert "indices" in sec_ids
    assert "counters" in sec_ids
    assert "network" in sec_ids
    assert "modules" in sec_ids
    assert "activity" in sec_ids

    # Verificar texto do aviso de Goodhart e Proxy
    notice_sec = next(s for s in report_model.sections if s.id == "ethical_notice")
    callout_texts = " ".join(b.text for b in notice_sec.blocks if hasattr(b, "text"))
    assert "Lei de Goodhart" in callout_texts
    assert "person.quality é um proxy" in callout_texts

    # 2. Verificar índices e contadores
    counters_sec = next(s for s in report_model.sections if s.id == "counters")
    assert any("Commits Realizados" in row[0] for row in counters_sec.blocks[0].rows)


def test_individual_report_notices_present_in_all_three_formats(mock_rich_bundle, tmp_path):
    """
    Critério de aceite central de F8.7:
    'aviso presente nos 3 formatos' (HTML, DOCX, PDF).
    """
    report_model = build_report(
        project_id="proj-1",
        project_name="Demo COGNIS",
        bundle=mock_rich_bundle,
        report_type="individual",
        target_person_uid="diego_uid",
        target_person_name="Diego Ramos",
        anonymize=False,
    )

    # 1. HTML
    html_out = tmp_path / "individual.html"
    html_content = render_html_report(report_model, output_path=html_out)
    assert html_out.is_file()
    assert "Lei de Goodhart" in html_content
    assert "person.quality é um proxy" in html_content
    assert "Nota de Uso Responsável" in html_content

    # 2. DOCX
    docx_out = tmp_path / "individual.docx"
    docx_bytes = render_docx_report(report_model, output_path=docx_out)
    assert docx_out.is_file()
    doc = docx.Document(io.BytesIO(docx_bytes))
    full_docx_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Lei de Goodhart" in full_docx_text
    assert "person.quality é um proxy" in full_docx_text
    assert "Nota de Uso Responsável" in full_docx_text

    # 3. PDF (Validação de renderização Platypus e integridade binária)
    pdf_out = tmp_path / "individual.pdf"
    pdf_bytes = render_pdf_report(report_model, output_path=pdf_out)
    assert pdf_out.is_file()
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in pdf_bytes[-1024:]
    assert len(pdf_bytes) > 3000
    # Valida que o modelo fornecido ao renderizador continha os avisos requeridos por §13.4
    assert "Lei de Goodhart" in report_model.appendix.ethical_note
    ethical_sec = next(s for s in report_model.sections if s.id == "ethical_notice")
    assert any("Lei de Goodhart" in b.text for b in ethical_sec.blocks if hasattr(b, "text"))
    assert any("person.quality é um proxy" in b.text for b in ethical_sec.blocks if hasattr(b, "text"))


def test_individual_report_anonymization(mock_rich_bundle, tmp_path):
    """Verifica que quando anonymize=True, nomes reais são substituídos por pseudônimos nos 3 formatos."""
    report_model = build_report(
        project_id="proj-1",
        project_name="Demo COGNIS",
        bundle=mock_rich_bundle,
        report_type="individual",
        target_person_uid="diego_uid",
        target_person_name="Diego Ramos",
        anonymize=True,
    )

    assert report_model.meta.anonymized is True
    # O nome real NÃO deve estar no título nem nos metadados
    assert "Diego Ramos" not in report_model.meta.title
    assert "Pessoa" in report_model.meta.title
    pseudo_name = report_model.meta.person_name
    assert pseudo_name and pseudo_name.startswith("Pessoa")

    # 1. HTML: 'Diego Ramos' nunca aparece e o pseudônimo aparece
    html_content = render_html_report(report_model)
    assert "Diego Ramos" not in html_content
    assert pseudo_name in html_content

    # 2. DOCX: 'Diego Ramos' nunca aparece e o pseudônimo aparece
    docx_bytes = render_docx_report(report_model)
    doc = docx.Document(io.BytesIO(docx_bytes))
    full_docx_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Diego Ramos" not in full_docx_text
    assert pseudo_name in full_docx_text

    # 3. PDF: renderiza sem erros com pseudônimo e integridade binária
    pdf_bytes = render_pdf_report(report_model)
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in pdf_bytes[-1024:]
    assert len(pdf_bytes) > 3000
