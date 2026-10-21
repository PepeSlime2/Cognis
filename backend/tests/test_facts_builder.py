from __future__ import annotations

import json
import pytest
from pydantic import ValidationError

from app.llm.facts_builder import Anonymizer, build_facts, sanitize_text
from app.llm.schemas import (
    AnalysisSection,
    Evidence,
    Finding,
    Recommendation,
)


# ==============================================================================
# Fixtures de Bundle Simulado
# ==============================================================================

@pytest.fixture
def sample_bundle() -> dict:
    return {
        "project_id": "proj-123",
        "window": {
            "from": "2026-09-01",
            "to": "2026-09-14",
            "label": "Sprint 3 - Pagamentos",
        },
        "metrics": {
            "graph.components": {"value": {"total_nodes": 6, "connected_components": 1}},
            "graph.density": {"value": 0.472},
            "graph.modularity": {"value": 0.314},
            "graph.centralization": {"value": 0.589},
            "flow.completion_rate": {"value": 0.72},
            "flow.late_rate": {"value": 0.285},
            "flow.lead_time": {"value": {"median": 4.5, "p85": 9.2}},
            "flow.cycle_time": {"value": {"median": 3.1, "p85": 6.8}},
            "flow.rework": {"value": 0.15},
            "flow.bottleneck_risk": {"value": "medium"},
            "team.knowledge_concentration": {"value": {"bus_factor": 1, "top1_share": 1.0}},
            "team.bridges": {
                "value": {"Alice": 0.65, "Bob": 0.42, "Charlie": 0.11}
            },
            "person.participation": {
                "by_person": {
                    "Alice": 0.88,
                    "Bob": 0.75,
                    "Charlie": 0.62,
                    "Diego": 0.45,
                    "Eduarda": 0.30,
                    "Felipe": 0.15,
                }
            },
            "person.delivery": {
                "by_person": {
                    "Alice": 0.95,
                    "Bob": 0.80,
                    "Charlie": 0.70,
                    "Diego": 0.50,
                    "Eduarda": 0.40,
                    "Felipe": 0.20,
                }
            },
            "person.counters": {
                "by_person": {
                    "Alice": {"commits": 24, "prs_created": 6, "reviews_given": 18, "tasks_completed": 8}
                }
            },
            "person.overall": {
                "by_person": {"Alice": 0.89}
            },
        },
        "signals": [
            {
                "id": "SIG-1",
                "code": "BUS_FACTOR_1",
                "severity": "high",
                "subject": "Diego",
                "title": "Fator de ônibus crítico",
                "message": "Diego é o único autor do módulo api/payments",
                "evidence": [
                    {"metric_id": "team.knowledge_concentration", "value": "top1_share: 1.0 em api/payments"}
                ],
            },
            {
                "id": "SIG-2",
                "code": "REVIEW_CONCENTRATION",
                "severity": "medium",
                "subject": "Alice",
                "title": "Sobrecarga de revisão",
                "message": "Alice realizou 62% das revisões",
                "evidence": [
                    {"metric_id": "flow.bottleneck_risk", "value": "Alice revisou 13 de 21 PRs"}
                ],
            },
            {
                "id": "SIG-3",
                "code": "ISOLATED_MEMBER",
                "severity": "medium",
                "subject": "Felipe",
                "title": "Membro isolado",
                "message": "Felipe colabora com no máximo 1 colega",
                "evidence": [
                    {"metric_id": "team.isolation", "value": "1 colaborador distinto"}
                ],
            },
        ],
    }


# ==============================================================================
# Testes dos Schemas Pydantic
# ==============================================================================

def test_analysis_section_valid():
    section = AnalysisSection(
        resumo="Visão equilibrada com pontos de atenção no fluxo de revisão.",
        achados=[
            Finding(
                titulo="Concentração de revisões",
                descricao="Uma única pessoa concentrou mais de 60% dos reviews.",
                severidade="alta",
                evidencias=[Evidence(ref="S2"), Evidence(ref="M1")],
            )
        ],
        recomendacoes=[
            Recommendation(
                acao="Distribuir revisões entre os pares.",
                justificativa="Reduz o tempo de bloqueio e mitiga gargalo.",
                evidencias=[Evidence(ref="S2")],
            )
        ],
        limitacoes=["Dados de retrabalho baseados em histórico recente."],
    )
    data = section.model_dump()
    assert data["resumo"].startswith("Visão equilibrada")
    assert len(data["achados"]) == 1
    assert data["achados"][0]["evidencias"][0]["ref"] == "S2"
    assert len(data["recomendacoes"]) == 1
    assert data["recomendacoes"][0]["acao"].startswith("Distribuir")


def test_analysis_section_resumo_max_length():
    with pytest.raises(ValidationError):
        AnalysisSection(
            resumo="X" * 601,
            achados=[],
            recomendacoes=[],
            limitacoes=[],
        )


def test_finding_severidade_enum():
    with pytest.raises(ValidationError):
        Finding(
            titulo="Teste",
            descricao="Desc",
            severidade="invalida",  # Deve ser 'baixa', 'media' ou 'alta'
            evidencias=[],
        )


# ==============================================================================
# Testes do Anonymizer
# ==============================================================================

def test_anonymizer_mapping_and_reversibility():
    anon = Anonymizer(enabled=True)
    assert anon.get_name("Alice") == "Pessoa A"
    assert anon.get_name("Bob") == "Pessoa B"
    assert anon.get_name("Alice") == "Pessoa A"  # Idempotente
    assert anon.get_name("Charlie") == "Pessoa C"

    rev = anon.reverse_map
    assert rev["Pessoa A"] == "Alice"
    assert rev["Pessoa B"] == "Bob"
    assert rev["Pessoa C"] == "Charlie"


def test_anonymizer_disabled():
    anon = Anonymizer(enabled=False)
    assert anon.get_name("Alice") == "Alice"
    assert anon.get_name("Bob") == "Bob"
    assert anon.reverse_map == {}


# ==============================================================================
# Testes de Sanitização de Texto
# ==============================================================================

def test_sanitize_text():
    raw = "Tarefa com   múltiplos    espaços\ne quebra de linha\r\ne muito longa " + ("A" * 100)
    cleaned = sanitize_text(raw, max_len=50)
    assert "\n" not in cleaned
    assert "\r" not in cleaned
    assert "  " not in cleaned
    assert len(cleaned) <= 50
    assert cleaned.endswith("…")


# ==============================================================================
# Testes do Facts Builder
# ==============================================================================

def test_build_facts_team_scope(sample_bundle):
    result = build_facts(sample_bundle, scope="team", anonymize=False)
    facts = result.facts

    assert facts["scope"] == "team"
    assert facts["window"]["from"] == "2026-09-01"
    assert facts["window"]["to"] == "2026-09-14"
    assert facts["team"]["active_members"] == 6
    assert facts["team"]["density"] == 0.47
    assert facts["team"]["completion_rate"] == 0.72
    assert facts["team"]["bus_factor"] == 1

    # Signals com IDs curtos
    assert len(facts["signals"]) == 3
    assert facts["signals"][0]["id"] == "S1"
    assert facts["signals"][0]["code"] == "BUS_FACTOR_1"
    assert facts["signals"][0]["subject"] == "Diego"
    codes = [s["code"] for s in facts["signals"]]
    assert "REVIEW_CONCENTRATION" in codes
    assert "ISOLATED_MEMBER" in codes

    # Métricas com IDs curtos
    assert len(facts["metrics"]) > 0
    assert facts["metrics"][0]["id"] == "M1"

    # Pessoas rankeadas
    assert len(facts["people"]) <= 12
    assert facts["people"][0]["name"] == "Alice"
    assert facts["people"][0]["participation"] == 0.88

    # Estimativa de tokens
    assert result.tokens_estimate < 3000
    assert len(json.dumps(facts)) < 12000
    assert len(facts["limits"]) >= 2


def test_build_facts_anonymized(sample_bundle):
    result = build_facts(sample_bundle, scope="team", anonymize=True)
    facts = result.facts
    reverse_map = result.reverse_map

    # Nenhum nome real deve aparecer em signals ou people
    assert "Alice" not in json.dumps(facts)
    assert "Diego" not in json.dumps(facts)
    assert "Felipe" not in json.dumps(facts)

    # Verificação do mapa reverso
    assert len(reverse_map) >= 3
    for pseudo, real in reverse_map.items():
        assert pseudo.startswith("Pessoa ")
        assert real in ["Alice", "Bob", "Charlie", "Diego", "Eduarda", "Felipe"]

    # Menções de evidência textual também devem ter nomes mascarados
    for sig in facts["signals"]:
        for ev in sig.get("evidence", []):
            assert "Alice" not in str(ev.get("value"))


def test_build_facts_person_scope(sample_bundle):
    result = build_facts(
        sample_bundle,
        scope="person",
        anonymize=False,
        target_person_name="Alice",
    )
    facts = result.facts

    assert facts["scope"] == "person"
    # Somente signals que envolvam a Alice
    for sig in facts["signals"]:
        assert sig.get("subject") == "Alice" or sig.get("target") == "Alice"

    # Pessoas contém apenas a Alice marcada como target
    assert len(facts["people"]) == 1
    assert facts["people"][0]["name"] == "Alice"
    assert facts["people"][0]["is_target"] is True

    # Métricas individuais da Alice
    metric_ids = [m["metric_id"] for m in facts["metrics"]]
    assert "person.counters" in metric_ids
    assert "person.overall" in metric_ids


def test_build_facts_max_limits(sample_bundle):
    # Gerar 25 signals simulados para testar o teto
    large_bundle = dict(sample_bundle)
    large_bundle["signals"] = [
        {
            "id": f"SIG-{i}",
            "code": f"SIGNAL_{i}",
            "severity": "medium",
            "subject": f"Dev {i}",
            "evidence": [],
        }
        for i in range(25)
    ]

    result = build_facts(large_bundle, scope="team", max_signals=10)
    assert len(result.facts["signals"]) == 10
    assert result.facts["signals"][0]["id"] == "S1"
    assert result.facts["signals"][9]["id"] == "S10"
