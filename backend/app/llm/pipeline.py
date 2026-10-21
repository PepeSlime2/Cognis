from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..db.models import Analysis, Project
from ..metrics.service import get_metrics_bundle
from ..metrics.windows import TimeWindow
from .client import (
    LLMError,
    OllamaAPIError,
    OllamaConnectionError,
    OllamaTimeoutError,
    chat,
    check_ollama_health,
)
from .facts_builder import build_facts
from .schemas import AnalysisSection
from .templates import generate_template_analysis
from .validator import format_retry_feedback, validate_analysis_section

logger = logging.getLogger(__name__)

# Carregar prompt do sistema do arquivo oficial
PROMPTS_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system_ptbr.md"

try:
    SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
except Exception:
    SYSTEM_PROMPT = (
        "Você é um analista de dinâmica de equipes de software. Escreva em português do Brasil, "
        "tom profissional e direto. Use SOMENTE os dados do bloco FATOS. Não invente números, nomes, datas ou causas. "
        "Todo achado e recomendação deve citar pelo menos uma evidência (ref) existente em FATOS. "
        "Copie números exatamente como aparecem em FATOS. Responda apenas com JSON no schema fornecido."
    )


def de_anonymize_text(text: str, reverse_map: dict[str, str]) -> str:
    """Substitui pseudônimos 'Pessoa X' pelos nomes reais correspondentes."""
    result = text
    for pseudo, real in reverse_map.items():
        result = result.replace(pseudo, real)
    return result


def de_anonymize_section(section: AnalysisSection, reverse_map: dict[str, str]) -> AnalysisSection:
    """Restaura nomes reais na seção antes de persistir para exibição (SPEC §9.4)."""
    if not reverse_map:
        return section

    data = section.model_dump()
    data["resumo"] = de_anonymize_text(data["resumo"], reverse_map)

    for finding in data.get("achados", []):
        finding["titulo"] = de_anonymize_text(finding["titulo"], reverse_map)
        finding["descricao"] = de_anonymize_text(finding["descricao"], reverse_map)

    for rec in data.get("recomendacoes", []):
        rec["acao"] = de_anonymize_text(rec["acao"], reverse_map)
        rec["justificativa"] = de_anonymize_text(rec["justificativa"], reverse_map)

    data["limitacoes"] = [de_anonymize_text(lim, reverse_map) for lim in data.get("limitacoes", [])]
    return AnalysisSection.model_validate(data)


def run_analysis_pipeline(
    db: Session,
    neo4j_driver: Any,
    project: Project,
    window: TimeWindow,
    scope: str = "team",
    person_uid: str | None = None,
    target_person_name: str | None = None,
    anonymize: bool = False,
    force_template: bool = False,
    existing_analysis_id: str | None = None,
    raw_facts: Any | None = None,
) -> Analysis:
    """
    Executa o pipeline completo de análise (SPEC §9.3 e §9.7):
    bundle -> signals -> facts_builder -> [LLM com retry ≤ 2] -> validator -> fallback template -> persistência.
    """
    # 1. Recuperar ou criar registro de Analysis no SQLite
    analysis: Analysis | None = None
    if existing_analysis_id:
        analysis = db.get(Analysis, existing_analysis_id)

    if analysis is None:
        analysis = Analysis(
            project_id=project.id,
            scope=scope,
            window_from=window.start_utc,
            window_to=window.end_utc,
            person_uid=person_uid,
            status="running",
            facts_json={},
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
    else:
        analysis.status = "running"
        db.commit()

    # 2. Obter bundle de métricas determinístico
    bundle = get_metrics_bundle(
        db=db,
        neo4j_driver=neo4j_driver,
        project=project,
        window=window,
        raw_facts=raw_facts,
    )

    # Resolver nome da pessoa caso escopo seja person e target_person_name não foi passado
    if scope == "person" and not target_person_name:
        people_metrics = bundle.get("metrics", {}).get("person.counters", {}).get("by_person", {})
        if people_metrics:
            target_person_name = next(iter(people_metrics.keys()))

    # 3. Construir bloco compacto FATOS
    facts_res = build_facts(
        bundle=bundle,
        scope=scope,
        anonymize=anonymize,
        target_person_name=target_person_name,
    )
    facts = facts_res.facts
    reverse_map = facts_res.reverse_map

    analysis.facts_json = facts

    # 4. Avaliar disponibilidade do Ollama
    health = check_ollama_health()
    use_llm = not force_template and health.get("available", False)

    final_section: AnalysisSection | None = None
    final_source: str = "template"
    retries_count = 0
    all_violations: list[str] = []

    if use_llm:
        logger.info("Executando pipeline de análise com LLM local (modelo=%s)", health.get("model"))
        user_prompt = (
            f"FATOS DO PROJETO:\n```json\n{json.dumps(facts, ensure_ascii=False, indent=2)}\n```\n\n"
            f"Com base exclusivamente nos fatos acima, produza a análise estruturada para o escopo '{scope}'.\n"
            "Responda apenas com o JSON conforme o schema AnalysisSection."
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # Loop de chamada com retry (máx. 2 retries = até 3 tentativas no total)
        for attempt in range(3):
            try:
                raw_response = chat(messages=messages, format=AnalysisSection)
            except (OllamaTimeoutError, OllamaConnectionError, OllamaAPIError, LLMError) as exc:
                logger.warning("Falha na chamada ao Ollama na tentativa %s: %s", attempt + 1, exc)
                all_violations.append(f"Falha de comunicação com o LLM: {exc}")
                break

            val_res = validate_analysis_section(raw_response, facts)
            if val_res.passed and val_res.parsed_section is not None:
                final_section = val_res.parsed_section
                final_source = "llm"
                break
            else:
                retries_count += 1
                all_violations.extend(val_res.violations)
                logger.info("Tentativa %s reprovada no validador com %s violações.", attempt + 1, len(val_res.violations))
                if attempt < 2:
                    # Adicionar resposta reprovada e feedback de correção nas mensagens
                    messages.append({"role": "assistant", "content": raw_response})
                    feedback_msg = format_retry_feedback(val_res.violations)
                    messages.append({"role": "user", "content": feedback_msg})

    # 5. Se o LLM não foi usado ou se falhou em todas as tentativas -> Fallback Template
    if final_section is None:
        logger.info("Aplicando fallback determinístico de template para a análise (scope=%s)", scope)
        final_section = generate_template_analysis(facts, scope=scope)
        final_source = "template"

    # Se a análise foi anonimizada para o LLM, desanonimizar para persistência
    if anonymize and reverse_map:
        final_section = de_anonymize_section(final_section, reverse_map)

    # 6. Persistir resultado final
    analysis.status = "completed"
    analysis.model = "llama3.1:8b" if final_source == "llm" else "template"
    analysis.source = final_source
    analysis.result_json = final_section.model_dump()
    analysis.validation_json = {
        "passed": final_source == "llm",
        "retries": retries_count,
        "violations": all_violations,
        "source": final_source,
    }

    db.commit()
    db.refresh(analysis)
    return analysis
