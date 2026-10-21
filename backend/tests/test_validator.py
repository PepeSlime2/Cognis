from __future__ import annotations

import json
import pytest

from app.llm.validator import (
    format_retry_feedback,
    validate_analysis_section,
)


@pytest.fixture
def mock_facts() -> dict:
    return {
        "scope": "team",
        "window": {"from": "2026-09-01", "to": "2026-09-14", "label": "Sprint 3"},
        "team": {
            "active_members": 6,
            "density": 0.47,
            "modularity": 0.31,
            "completion_rate": 0.72,
            "late_rate": 0.28,
            "bus_factor": 1,
        },
        "signals": [
            {
                "id": "S1",
                "code": "BUS_FACTOR_1",
                "severity": "high",
                "subject": "Diego",
                "evidence": [
                    {"metric_id": "team.knowledge_concentration", "value": "1.0 em api/payments"}
                ],
            },
            {
                "id": "S2",
                "code": "REVIEW_CONCENTRATION",
                "severity": "medium",
                "subject": "Alice",
                "evidence": [
                    {"metric_id": "flow.bottleneck_risk", "value": "13 de 21 PRs (62%)"}
                ],
            },
        ],
        "metrics": [
            {
                "id": "M1",
                "metric_id": "flow.lead_time",
                "value": 4.5,
                "desc": "Lead time mediano em dias",
            },
            {
                "id": "M2",
                "metric_id": "graph.centralization",
                "value": 0.58,
                "desc": "Centralização Freeman",
            },
        ],
        "people": [
            {"id": "P1", "name": "Alice", "participation": 0.88},
            {"id": "P2", "name": "Diego", "participation": 0.45},
            {"id": "P3", "name": "Bob", "participation": 0.60},
        ],
        "limits": [
            "Qualidade e retrabalho são proxies e dependem dos dados registrados."
        ],
    }


# ==============================================================================
# 1. Caso Válido
# ==============================================================================

def test_validate_analysis_section_fully_valid(mock_facts):
    valid_payload = {
        "resumo": "A Sprint 3 teve 6 membros ativos com taxa de conclusão de 72% e lead time de 4,5 dias.",
        "achados": [
            {
                "titulo": "Concentração de reviews em Alice",
                "descricao": "Alice realizou 13 de 21 revisões, totalizando 62% das revisões do período.",
                "severidade": "media",
                "evidencias": [{"ref": "S2"}],
            },
            {
                "titulo": "Risco de conhecimento exclusivo com Diego",
                "descricao": "Diego é o único mantenedor com concentração de 1.0 no módulo.",
                "severidade": "alta",
                "evidencias": [{"ref": "S1"}],
            },
        ],
        "recomendacoes": [
            {
                "acao": "Realizar pareamento com Bob nas revisões.",
                "justificativa": "Alivia a sobrecarga de Alice identificada em S2.",
                "evidencias": [{"ref": "S2"}],
            }
        ],
        "limitacoes": [
            "Dados de qualidade dependem dos registros do repositório."
        ],
    }

    result = validate_analysis_section(valid_payload, mock_facts)
    assert result.passed is True
    assert len(result.violations) == 0
    assert result.parsed_section is not None
    assert result.parsed_section.achados[0].severidade == "media"


def test_validate_string_json_with_codeblock_markdown(mock_facts):
    valid_payload = {
        "resumo": "Resumo sintético para 6 desenvolvedores.",
        "achados": [
            {
                "titulo": "Padrão de centralização",
                "descricao": "A centralização medida foi de 0.58 no grafo.",
                "severidade": "baixa",
                "evidencias": [{"ref": "M2"}],
            }
        ],
        "recomendacoes": [
            {
                "acao": "Acompanhar métricas de fluxo.",
                "justificativa": "Baseado na evidência M2.",
                "evidencias": [{"ref": "M2"}],
            }
        ],
        "limitacoes": [],
    }
    raw_markdown = f"```json\n{json.dumps(valid_payload)}\n```"

    result = validate_analysis_section(raw_markdown, mock_facts)
    assert result.passed is True
    assert result.parsed_section is not None


# ==============================================================================
# 2. Casos Maliciosos: Falha Estrutural e JSON Inválido
# ==============================================================================

def test_malicious_invalid_json_fails(mock_facts):
    broken_json = "{ resumo: 'incompleto sem fechar chaves' "
    result = validate_analysis_section(broken_json, mock_facts)
    assert result.passed is False
    assert any("JSON inválido" in v for v in result.violations)


def test_malicious_missing_required_schema_fields(mock_facts):
    incomplete_payload = {
        # 'resumo' é obrigatório no schema AnalysisSection e está ausente
        "achados": [],
        "recomendacoes": [],
    }
    result = validate_analysis_section(incomplete_payload, mock_facts)
    assert result.passed is False
    assert any("incompatível com o schema" in v for v in result.violations)


# ==============================================================================
# 3. Casos Maliciosos: Referências (Refs) Inexistentes
# ==============================================================================

def test_malicious_hallucinated_ref_fails(mock_facts):
    payload = {
        "resumo": "Equipe com 6 membros.",
        "achados": [
            {
                "titulo": "Achado inventado",
                "descricao": "Cita uma evidência inexistente na base.",
                "severidade": "alta",
                "evidencias": [{"ref": "S99"}],  # S99 não existe!
            }
        ],
        "recomendacoes": [
            {
                "acao": "Recomendação qualquer.",
                "justificativa": "Justificativa.",
                "evidencias": [{"ref": "M42"}],  # M42 não existe!
            }
        ],
        "limitacoes": [],
    }

    result = validate_analysis_section(payload, mock_facts)
    assert result.passed is False
    assert any("S99" in v for v in result.violations)
    assert any("M42" in v for v in result.violations)


# ==============================================================================
# 4. Casos Maliciosos: Números Alucinados / Inventados
# ==============================================================================

def test_malicious_hallucinated_numbers_fails(mock_facts):
    payload = {
        "resumo": "A equipe concluiu 93 tarefas e teve um ganho de 37% na produtividade.",  # 93 e 37% não existem!
        "achados": [
            {
                "titulo": "Atraso massivo de 85 dias",  # 85 não existe!
                "descricao": "Foram abertos 140 chamados com 12 incidentes graves.",  # 140 e 12 não existem!
                "severidade": "alta",
                "evidencias": [{"ref": "S1"}],
            }
        ],
        "recomendacoes": [],
        "limitacoes": [],
    }

    result = validate_analysis_section(payload, mock_facts)
    assert result.passed is False
    assert any("93" in v for v in result.violations)
    assert any("37%" in v or "37" in v for v in result.violations)
    assert any("85" in v for v in result.violations)
    assert any("140" in v for v in result.violations)


# ==============================================================================
# 5. Casos Maliciosos: Pessoas Inventadas
# ==============================================================================

def test_malicious_hallucinated_person_fails(mock_facts):
    payload = {
        "resumo": "Análise da equipe com 6 pessoas.",
        "achados": [
            {
                "titulo": "Desempenho de colaborador externo",
                "descricao": "Roberto Silva assumiu as demandas críticas sem auxílio.",  # Roberto Silva não existe!
                "severidade": "media",
                "evidencias": [{"ref": "S1"}],
            }
        ],
        "recomendacoes": [],
        "limitacoes": [],
    }

    result = validate_analysis_section(payload, mock_facts)
    assert result.passed is False
    assert any("Roberto Silva" in v for v in result.violations)


def test_malicious_hallucinated_pseudonym_fails(mock_facts):
    anonymized_facts = dict(mock_facts)
    anonymized_facts["people"] = [
        {"id": "P1", "name": "Pessoa A"},
        {"id": "P2", "name": "Pessoa B"},
    ]
    payload = {
        "resumo": "Análise com pseudônimos.",
        "achados": [
            {
                "titulo": "Sobrecarga de Pessoa Z",
                "descricao": "Pessoa Z acumulou tarefas atrasadas.",  # Pessoa Z não existe!
                "severidade": "media",
                "evidencias": [{"ref": "S1"}],
            }
        ],
        "recomendacoes": [],
        "limitacoes": [],
    }

    result = validate_analysis_section(payload, anonymized_facts)
    assert result.passed is False
    assert any("Pessoa Z" in v for v in result.violations)


# ==============================================================================
# 6. Tolerância e Metalinguagem
# ==============================================================================

def test_meta_counting_numbers_are_ignored(mock_facts):
    payload = {
        "resumo": "Avaliamos os dados e apresentamos 2 achados e 1 recomendações para o fluxo.",
        "achados": [
            {
                "titulo": "Centralização em Alice",
                "descricao": "Identificada taxa de 0.58 no índice.",
                "severidade": "baixa",
                "evidencias": [{"ref": "M2"}],
            }
        ],
        "recomendacoes": [
            {
                "acao": "Seguir monitoramento.",
                "justificativa": "Baseado em M2.",
                "evidencias": [{"ref": "M2"}],
            }
        ],
        "limitacoes": [],
    }

    result = validate_analysis_section(payload, mock_facts)
    # Os números 2 e 1 de metalinguagem ("2 achados", "1 recomendações") não devem reprovar
    assert result.passed is True


# ==============================================================================
# 7. Formatação de Feedback para Retry
# ==============================================================================

def test_format_retry_feedback():
    violations = [
        "A evidência 'S99' não existe em FATOS.",
        "O número '37%' não existe nos números permitidos de FATOS.",
    ]
    feedback = format_retry_feedback(violations)
    assert "S99" in feedback
    assert "37%" in feedback
    assert "Regras estritas de correção" in feedback
