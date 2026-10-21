from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.llm.schemas import AnalysisSection
from app.llm.templates import generate_template_analysis
from app.llm.validator import validate_analysis_section
from tests.llm_eval.run_eval import load_fixtures, run_eval_suite

FIXTURES_DIR = Path(__file__).resolve().parent / "llm_eval" / "fixtures"


def test_llm_eval_five_fixtures_exist() -> None:
    """Verifica que as 5 fixtures exigidas por SPEC §9.9 existem."""
    expected_fixtures = {
        "equipe_saudavel",
        "gargalo_review",
        "silos",
        "bus_factor",
        "dados_insuficientes",
    }
    fixtures = load_fixtures()
    assert set(fixtures.keys()) == expected_fixtures


def test_llm_eval_fixtures_structure() -> None:
    """Valida a estrutura JSON de cada fixture contra o contrato de FATOS (SPEC §9.4)."""
    fixtures = load_fixtures()
    for name, facts in fixtures.items():
        assert "window" in facts, f"Fixture {name} deve conter 'window'"
        assert "from" in facts["window"]
        assert "to" in facts["window"]

        assert "team" in facts, f"Fixture {name} deve conter 'team'"
        assert isinstance(facts["team"], dict)
        assert "active_members" in facts["team"]

        assert "signals" in facts, f"Fixture {name} deve conter 'signals'"
        assert isinstance(facts["signals"], list)

        assert "metrics" in facts, f"Fixture {name} deve conter 'metrics'"
        assert isinstance(facts["metrics"], list)

        assert "limits" in facts, f"Fixture {name} deve conter 'limits'"
        assert isinstance(facts["limits"], list)


def test_llm_eval_template_analysis_passes_validator() -> None:
    """Verifica que para as 5 fixtures, a análise determinística por template passa com 100% de sucesso no validador."""
    fixtures = load_fixtures()
    for name, facts in fixtures.items():
        sec = generate_template_analysis(facts, scope="team")
        assert isinstance(sec, AnalysisSection)
        assert len(sec.resumo) > 0

        val = validate_analysis_section(sec, facts)
        assert val.passed is True, f"Validador reprovou template para {name}: {val.violations}"
        assert len(val.violations) == 0


def test_llm_eval_run_eval_suite_generates_csv_and_md(tmp_path: Path) -> None:
    """Verifica que run_eval_suite executa de ponta a ponta e exporta planilha CSV e relatório MD."""
    csv_out = tmp_path / "test_resultados.csv"
    md_out = tmp_path / "test_relatorio.md"

    results = run_eval_suite(
        rounds=1,
        force_template=True,
        output_csv=csv_out,
        output_md=md_out,
    )

    assert len(results) == 5  # 5 cenários x 1 rodada
    assert csv_out.exists()
    assert md_out.exists()

    # Verificar conteúdo do CSV
    content = csv_out.read_text(encoding="utf-8")
    assert "cenario,rodada,json_valido" in content
    assert "equipe_saudavel" in content
    assert "gargalo_review" in content
    assert "silos" in content
    assert "bus_factor" in content
    assert "dados_insuficientes" in content

    # Verificar conteúdo do MD
    md_content = md_out.read_text(encoding="utf-8")
    assert "# Relatório de Avaliação do LLM — COGNIS" in md_content
    assert "100.0%" in md_content
