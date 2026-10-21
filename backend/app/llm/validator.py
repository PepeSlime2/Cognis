from __future__ import annotations

import json
import math
import re
from typing import Any
from pydantic import BaseModel, Field, ValidationError

from .schemas import AnalysisSection


# Regex para extração de números conforme SPEC §9.7: \d+(?:[.,]\d+)?%?
NUMBER_PATTERN = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")

# Regex para detectar contagem de itens de metalinguagem (ex: "3 achados", "2 recomendações")
META_COUNT_PATTERN = re.compile(
    r"\b([1-9]|10)\s+(?:recomendações|recomendacoes|achados|itens|ações|acoes)\b",
    re.IGNORECASE,
)


class ValidationResult(BaseModel):
    """
    Resultado da validação estrita anti-alucinação de uma seção de análise (SPEC §9.7).
    """
    passed: bool
    violations: list[str] = Field(default_factory=list)
    parsed_section: AnalysisSection | None = None


def normalize_number(num_str: str) -> tuple[float, bool]:
    """
    Converte string numérica ('42', '4,5', '72%', '0.15') em float e flag de percentual.
    """
    is_percent = "%" in num_str
    clean = num_str.replace("%", "").replace(",", ".").strip()
    try:
        val = float(clean)
        return val, is_percent
    except ValueError:
        return float("nan"), is_percent


def extract_allowed_numbers(facts: dict[str, Any]) -> set[float]:
    """
    Extrai recursivamente todos os números presentes no bloco FATOS e gera seus
    valores numéricos (incluindo versões percentuais e decimais equivalentes).
    """
    allowed: set[float] = set()

    def visit(val: Any) -> None:
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            v = float(val)
            allowed.add(v)
            # Se for decimal entre 0 e 1, permitir a forma percentual (ex: 0.72 -> 72)
            if 0.0 <= v <= 1.0:
                allowed.add(round(v * 100, 2))
                allowed.add(round(v * 100, 0))
            # Se for percentual entre 0 e 100, permitir a forma decimal (ex: 72 -> 0.72)
            if 0.0 <= v <= 100.0:
                allowed.add(round(v / 100, 4))
                allowed.add(round(v / 100, 2))
        elif isinstance(val, str):
            # Tentar extrair números de strings de evidências (ex: "13 de 21", "2026-09-01")
            for match in NUMBER_PATTERN.findall(val):
                n_val, is_pct = normalize_number(match)
                if not math.isnan(n_val):
                    allowed.add(n_val)
                    if is_pct:
                        allowed.add(round(n_val / 100, 4))
                    elif 0.0 <= n_val <= 1.0:
                        allowed.add(round(n_val * 100, 2))
                        allowed.add(round(n_val * 100, 0))
        elif isinstance(val, list):
            for item in val:
                visit(item)
        elif isinstance(val, dict):
            for item in val.values():
                visit(item)

    visit(facts)
    return allowed


def is_number_allowed(num_str: str, allowed_numbers: set[float]) -> bool:
    """
    Verifica se o número extraído do texto corresponde a algum número em fatos,
    com tolerância de arredondamento de até 0.5.
    """
    val, is_pct = normalize_number(num_str)
    if math.isnan(val):
        return True

    candidates = [val]
    if is_pct:
        candidates.append(val / 100)
    else:
        candidates.append(val * 100)

    for target in allowed_numbers:
        for cand in candidates:
            # Tolerância absoluta de 0.5 na última casa ou correspondência exata
            if abs(target - cand) <= 0.501:
                return True
            # Se o número for relativamente próximo (ex: 72.1 vs 72)
            if target != 0 and abs(target - cand) / max(abs(target), abs(cand)) <= 0.01:
                return True

    return False


def extract_allowed_refs(facts: dict[str, Any]) -> set[str]:
    """
    Coleta todos os IDs curtos válidos presentes em FATOS (ex.: 'S1', 'M2', 'P3').
    """
    refs: set[str] = set()

    # Signals
    for s in facts.get("signals", []):
        if s.get("id"):
            refs.add(str(s["id"]))

    # Metrics
    for m in facts.get("metrics", []):
        if m.get("id"):
            refs.add(str(m["id"]))

    # People
    for p in facts.get("people", []):
        if p.get("id"):
            refs.add(str(p["id"]))

    return refs


def extract_allowed_people(facts: dict[str, Any]) -> set[str]:
    """
    Coleta todos os nomes de pessoas permitidos (reais ou pseudônimos 'Pessoa X').
    """
    people: set[str] = set()

    for p in facts.get("people", []):
        if p.get("name"):
            people.add(str(p["name"]).lower())

    for s in facts.get("signals", []):
        if s.get("subject"):
            people.add(str(s["subject"]).lower())
        if s.get("target"):
            people.add(str(s["target"]).lower())

    for m in facts.get("metrics", []):
        if m.get("subject"):
            people.add(str(m["subject"]).lower())

    return people


def validate_analysis_section(
    raw_output: str | dict[str, Any],
    facts: dict[str, Any],
) -> ValidationResult:
    """
    Executa a bateria completa de validações anti-alucinação (SPEC §9.7):
    1. Conformidade com o schema Pydantic AnalysisSection
    2. Existência de todas as referências (evidencias[].ref) no facts
    3. Conformidade estrita de todos os números citados no texto com facts
    4. Conformidade de nomes de pessoas citados no texto
    """
    violations: list[str] = []

    # 1. Parse do schema Pydantic
    parsed_section: AnalysisSection | None = None
    if isinstance(raw_output, str):
        try:
            # Se veio cercado de ```json ... ```, limpar
            clean_str = raw_output.strip()
            if clean_str.startswith("```"):
                lines = clean_str.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                clean_str = "\n".join(lines).strip()

            parsed_dict = json.loads(clean_str)
            parsed_section = AnalysisSection.model_validate(parsed_dict)
        except json.JSONDecodeError as exc:
            return ValidationResult(
                passed=False,
                violations=[f"JSON inválido retornado pelo modelo: {exc}"],
            )
        except ValidationError as exc:
            err_details = "; ".join(f"{err['loc']}: {err['msg']}" for err in exc.errors())
            return ValidationResult(
                passed=False,
                violations=[f"Estrutura incompatível com o schema AnalysisSection: {err_details}"],
            )
    elif isinstance(raw_output, dict):
        try:
            parsed_section = AnalysisSection.model_validate(raw_output)
        except ValidationError as exc:
            err_details = "; ".join(f"{err['loc']}: {err['msg']}" for err in exc.errors())
            return ValidationResult(
                passed=False,
                violations=[f"Estrutura incompatível com o schema AnalysisSection: {err_details}"],
            )
    else:
        return ValidationResult(
            passed=False,
            violations=["Tipo de saída inválido para validação (deve ser str JSON ou dict)"],
        )

    # 2. Validar referências (refs de evidências)
    allowed_refs = extract_allowed_refs(facts)
    cited_refs: set[str] = set()

    for finding in parsed_section.achados:
        for ev in finding.evidencias:
            cited_refs.add(ev.ref)
            if ev.ref not in allowed_refs:
                violations.append(
                    f"A evidência '{ev.ref}' citada no achado '{finding.titulo}' não existe em FATOS."
                )

    for rec in parsed_section.recomendacoes:
        for ev in rec.evidencias:
            cited_refs.add(ev.ref)
            if ev.ref not in allowed_refs:
                violations.append(
                    f"A evidência '{ev.ref}' citada na recomendação '{rec.acao[:40]}' não existe em FATOS."
                )

    # 3. Validar números citados no texto
    allowed_numbers = extract_allowed_numbers(facts)

    # Coletar todos os blocos de texto
    text_blocks: list[str] = [parsed_section.resumo]
    for f in parsed_section.achados:
        text_blocks.append(f.titulo)
        text_blocks.append(f.descricao)
    for r in parsed_section.recomendacoes:
        text_blocks.append(r.acao)
        text_blocks.append(r.justificativa)
    text_blocks.extend(parsed_section.limitacoes)

    full_text = " ".join(text_blocks)

    # Encontrar números usados em metalinguagem (ex: "3 achados", "2 recomendações") para ignorar
    meta_ignored_numbers: set[str] = set()
    for meta_match in META_COUNT_PATTERN.finditer(full_text):
        meta_num = meta_match.group(1)
        meta_ignored_numbers.add(meta_num)

    extracted_numbers = NUMBER_PATTERN.findall(full_text)
    for raw_num in extracted_numbers:
        # Se for número de metalinguagem <= 10 (ex: "3 recomendações"), pular
        if raw_num in meta_ignored_numbers:
            continue

        # Se o número é um dos IDs de ref (ex.: 1 de "S1"), mas o regex pegou só dígito, verificar
        if raw_num in [r.lstrip("SMPsmp") for r in cited_refs]:
            # Verificar se faz parte do ref citado no texto
            continue

        if not is_number_allowed(raw_num, allowed_numbers):
            violations.append(
                f"O número '{raw_num}' citado no texto não existe nos números permitidos de FATOS."
            )

    # 4. Validar nomes citados no texto (SPEC §9.7: nomes devem estar em facts ou ser 'Pessoa X')
    allowed_people = extract_allowed_people(facts)

    # 4.1 Validação de pseudônimos "Pessoa [A-Z]+"
    pseudonym_pattern = re.compile(r"\b(Pessoa\s+[A-Z]+)\b")
    for match in pseudonym_pattern.findall(full_text):
        if allowed_people and match.lower() not in allowed_people:
            violations.append(f"O pseudônimo '{match}' citado não existe nas pessoas dos fatos.")

    # 4.2 Validação de nomes compostos alucinados (ex: 'Roberto Silva', 'Mariana Souza')
    compound_name_pattern = re.compile(r"\b([A-Z][a-zÀ-ÿ]{2,}\s+[A-Z][a-zÀ-ÿ]{2,})\b")
    technical_compound_terms = {
        "pull request", "lead time", "cycle time", "sprint review", "code review",
        "centralização freeman", "centralizacao freeman", "fator ônibus", "fator onibus",
        "fator de", "rede de", "taxa de", "risco de", "tempo de", "tempo médio",
        "dados de", "membros ativos", "pontos de", "visão geral", "visao geral",
        "tarefas atrasadas", "projeto cognis", "software livre", "trabalho em",
    }
    for match in compound_name_pattern.findall(full_text):
        m_lower = match.lower()
        if m_lower in technical_compound_terms:
            continue
        # Se contiver preposição 'de', 'em', 'da', etc. no meio (ex: "Taxa de", "Risco de")
        if any(prep in m_lower for prep in (" de ", " em ", " da ", " do ", " para ")):
            continue
        # Se for nome composto e não for nenhum membro do time
        if allowed_people and not any(p in m_lower or m_lower in p for p in allowed_people):
            violations.append(f"O nome '{match}' citado não corresponde a nenhum membro do projeto.")

    # 4.3 Menções com preposições de autoria/atribuição a terceiros (ex: "desenvolvedor Roberto", "com Carlos")
    contextual_person_pattern = re.compile(
        r"\b(?:desenvolvedor|membro|colega|autor|revisor)\s+([A-Z][a-zÀ-ÿ]{2,})\b",
        re.IGNORECASE,
    )
    for match in contextual_person_pattern.findall(full_text):
        m_lower = match.lower()
        if m_lower in ("pessoa", "externo", "ativo", "principal", "exclusivo"):
            continue
        if allowed_people and not any(p in m_lower or m_lower in p for p in allowed_people):
            violations.append(f"O nome '{match}' citado não corresponde a nenhum membro do projeto.")

    passed = len(violations) == 0
    return ValidationResult(
        passed=passed,
        violations=violations,
        parsed_section=parsed_section,
    )


def format_retry_feedback(violations: list[str]) -> str:
    """
    Formata as violações para inclusão no prompt de retry do LLM (SPEC §9.7).
    """
    bullet_points = "\n".join(f"- {v}" for v in violations)
    return (
        "A resposta anterior foi reprovada pelas seguintes violações:\n"
        f"{bullet_points}\n\n"
        "Regras estritas de correção:\n"
        "1. Cite SOMENTE referências (refs) existentes no bloco FATOS.\n"
        "2. Copie os números exatamente como aparecem em FATOS; nunca calcule ou invente novos números.\n"
        "3. Não cite pessoas fora do bloco FATOS.\n"
        "Por favor, gere a análise corrigida em formato JSON válido conforme o schema."
    )
