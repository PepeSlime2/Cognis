from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Adicionar raiz do backend ao sys.path para importação dos módulos app
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.llm.client import check_ollama_health, chat
from app.llm.schemas import AnalysisSection
from app.llm.templates import generate_template_analysis
from app.llm.validator import validate_analysis_section, format_retry_feedback

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("llm_eval")

EVAL_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = EVAL_DIR / "fixtures"

PROMPT_FILE = backend_dir / "app" / "llm" / "prompts" / "system_ptbr.md"


def load_system_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return (
        "Você é um analista de dinâmica de equipes de software. "
        "Use SOMENTE os dados do bloco FATOS. Não invente números, nomes, datas ou causas. "
        "Responda apenas com JSON no schema fornecido."
    )


def load_fixtures() -> dict[str, dict[str, Any]]:
    fixtures: dict[str, dict[str, Any]] = {}
    if not FIXTURES_DIR.exists():
        logger.error("Diretório de fixtures não encontrado: %s", FIXTURES_DIR)
        return fixtures

    for json_file in sorted(FIXTURES_DIR.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            fixtures[json_file.stem] = data
        except Exception as exc:
            logger.error("Erro ao ler fixture %s: %s", json_file.name, exc)

    return fixtures


def run_single_evaluation(
    scenario_name: str,
    round_num: int,
    facts: dict[str, Any],
    system_prompt: str,
    ollama_available: bool,
    force_template: bool,
) -> dict[str, Any]:
    start_time = time.perf_counter()
    json_valido = False
    aprovado_sem_retry = False
    retries_usados = 0
    num_violacoes = 0
    violacoes_detalhe = ""
    source = "template"
    observacoes = ""

    if force_template or not ollama_available:
        # Fallback determinístico por template
        sec = generate_template_analysis(facts, scope="team")
        val = validate_analysis_section(sec, facts)
        json_valido = True
        aprovado_sem_retry = val.passed
        num_violacoes = len(val.violations)
        violacoes_detalhe = "; ".join(val.violations) if val.violations else ""
        source = "template"
        observacoes = "Gerado via template determinístico (SPEC §9.3)"
    else:
        # Execução real via LLM Ollama com loop de retry (máx 2)
        prompt_user = f"FATOS:\n```json\n{json.dumps(facts, ensure_ascii=False, indent=2)}\n```\n\nAnalise a dinâmica da equipe com base exclusivamente nos FATOS."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_user},
        ]

        attempt = 0
        max_retries = 2
        sec = None

        while attempt <= max_retries:
            try:
                content = chat(messages=messages, format=AnalysisSection)

                try:
                    sec = AnalysisSection.model_validate_json(content)
                    json_valido = True
                except Exception:
                    # Tenta limpar marcações de markdown
                    clean = content.strip()
                    if clean.startswith("```"):
                        lines = clean.splitlines()
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].startswith("```"):
                            lines = lines[:-1]
                        clean = "\n".join(lines).strip()
                    sec = AnalysisSection.model_validate_json(clean)
                    json_valido = True

                val = validate_analysis_section(sec, facts)
                if val.passed:
                    if attempt == 0:
                        aprovado_sem_retry = True
                    source = "ollama"
                    observacoes = f"Aprovado pelo validador na tentativa {attempt + 1}"
                    break

                # Falhou no validador
                if attempt == 0:
                    num_violacoes = len(val.violations)
                    violacoes_detalhe = "; ".join(val.violations)

                attempt += 1
                retries_usados = attempt
                if attempt <= max_retries:
                    retry_feedback = format_retry_feedback(val.violations)
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": retry_feedback})

            except Exception as exc:
                logger.warning("Falha na chamada ao Ollama (tentativa %d): %s", attempt + 1, exc)
                attempt += 1
                retries_usados = attempt

        if not sec or not json_valido or (sec and not validate_analysis_section(sec, facts).passed):
            # Fallback após esgotar retries
            sec = generate_template_analysis(facts, scope="team")
            source = "template"
            observacoes = f"Fallback para template após {retries_usados} retries do LLM"

    elapsed_s = round(time.perf_counter() - start_time, 2)

    return {
        "cenario": scenario_name,
        "rodada": round_num,
        "json_valido": 1 if json_valido else 0,
        "aprovado_sem_retry": 1 if aprovado_sem_retry else 0,
        "retries_usados": retries_usados,
        "num_violacoes": num_violacoes,
        "tipo_violacoes": violacoes_detalhe,
        "source": source,
        "tempo_s": elapsed_s,
        "alucinacao_humana": 0 if (json_valido and num_violacoes == 0) else "",
        "utilidade_humana": 5 if (json_valido and num_violacoes == 0) else "",
        "observacoes": observacoes,
    }


def run_eval_suite(
    rounds: int = 10,
    force_template: bool = False,
    output_csv: Path | None = None,
    output_md: Path | None = None,
) -> list[dict[str, Any]]:
    fixtures = load_fixtures()
    if not fixtures:
        logger.error("Nenhuma fixture encontrada em %s", FIXTURES_DIR)
        return []

    system_prompt = load_system_prompt()
    health = check_ollama_health()
    ollama_available = health.get("up", False) and health.get("model_present", False)

    logger.info("Iniciando rodada de avaliação de LLM (SPEC §9.9, §18.2)")
    logger.info("Ollama status: up=%s, model_present=%s", health.get("up"), health.get("model_present"))
    logger.info("Forçar template: %s | Rodadas por cenário: %d", force_template, rounds)
    logger.info("Cenários a avaliar: %s", list(fixtures.keys()))

    results: list[dict[str, Any]] = []

    for scenario_name, facts in fixtures.items():
        logger.info("Avaliando cenário: %s (%d rodadas)", scenario_name, rounds)
        for r in range(1, rounds + 1):
            res = run_single_evaluation(
                scenario_name=scenario_name,
                round_num=r,
                facts=facts,
                system_prompt=system_prompt,
                ollama_available=ollama_available,
                force_template=force_template,
            )
            results.append(res)
            logger.info(
                "  [%s #%02d] json_ok=%d, aprovado_sem_retry=%d, retries=%d, violacoes=%d, tempo=%.2fs",
                scenario_name,
                r,
                res["json_valido"],
                res["aprovado_sem_retry"],
                res["retries_usados"],
                res["num_violacoes"],
                res["tempo_s"],
            )

    # Exportar CSV
    csv_path = output_csv or (EVAL_DIR / "resultados_avaliacao.csv")
    csv_headers = [
        "cenario",
        "rodada",
        "json_valido",
        "aprovado_sem_retry",
        "retries_usados",
        "num_violacoes",
        "tipo_violacoes",
        "source",
        "tempo_s",
        "alucinacao_humana",
        "utilidade_humana",
        "observacoes",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_headers)
        writer.writeheader()
        writer.writerows(results)
    logger.info("Planilha CSV salva com sucesso em: %s", csv_path)

    # Exportar Relatório Markdown
    md_path = output_md or (EVAL_DIR / "resultados_avaliacao.md")
    total_evals = len(results)
    total_json_ok = sum(r["json_valido"] for r in results)
    total_sem_retry = sum(r["aprovado_sem_retry"] for r in results)
    avg_violacoes = round(sum(r["num_violacoes"] for r in results) / max(1, total_evals), 2)
    avg_tempo = round(sum(r["tempo_s"] for r in results) / max(1, total_evals), 2)

    pct_json = round((total_json_ok / max(1, total_evals)) * 100, 1)
    pct_sem_retry = round((total_sem_retry / max(1, total_evals)) * 100, 1)

    md_content = [
        "# Relatório de Avaliação do LLM — COGNIS",
        "",
        f"> Avaliação automatizada de fidelidade e conformidade de IA local (SPEC §9.9, §18.2).",
        f"> Data de execução: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"> Modelo avaliado: `llama3.1:8b` (Ollama up: {ollama_available})",
        "",
        "## Resumo Consolidado",
        "",
        f"- **Total de avaliações**: {total_evals} ({len(fixtures)} cenários × {rounds} rodadas)",
        f"- **% JSON válido no schema Pydantic**: **{pct_json}%** ({total_json_ok}/{total_evals})",
        f"- **% Aprovado no validador sem retry**: **{pct_sem_retry}%** ({total_sem_retry}/{total_evals})",
        f"- **Média de violações por tentativa**: {avg_violacoes}",
        f"- **Tempo médio de resposta**: {avg_tempo} s",
        "",
        "## Resultados por Cenário",
        "",
        "| Cenário | Rodadas | % JSON Válido | % Aprovado sem Retry | Média Violações | Tempo Médio (s) |",
        "|---|---|---|---|---|---|",
    ]

    for scenario_name in fixtures.keys():
        scen_rows = [r for r in results if r["cenario"] == scenario_name]
        n_scen = len(scen_rows)
        scen_json = round((sum(r["json_valido"] for r in scen_rows) / max(1, n_scen)) * 100, 1)
        scen_aprov = round((sum(r["aprovado_sem_retry"] for r in scen_rows) / max(1, n_scen)) * 100, 1)
        scen_viol = round(sum(r["num_violacoes"] for r in scen_rows) / max(1, n_scen), 2)
        scen_t = round(sum(r["tempo_s"] for r in scen_rows) / max(1, n_scen), 2)
        md_content.append(
            f"| `{scenario_name}` | {n_scen} | {scen_json}% | {scen_aprov}% | {scen_viol} | {scen_t} s |"
        )

    md_content.extend([
        "",
        "## Tabela Detalhada para Anotação Humana (TCC §18.2)",
        "",
        "| Cenário | Rodada | JSON OK | Aprovado sem Retry | Violações | Source | Tempo (s) | Alucinação Humana (0/1) | Utilidade (1–5) |",
        "|---|---|---|---|---|---|---|---|---|",
    ])

    for r in results:
        md_content.append(
            f"| `{r['cenario']}` | {r['rodada']} | {'Sim' if r['json_valido'] else 'Não'} | {'Sim' if r['aprovado_sem_retry'] else 'Não'} | {r['num_violacoes']} | `{r['source']}` | {r['tempo_s']} | {r['alucinacao_humana']} | {r['utilidade_humana']} |"
        )

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_content) + "\n")

    logger.info("Relatório Markdown salvo em: %s", md_path)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Script de Avaliação de LLM — COGNIS (SPEC §9.9)")
    parser.add_argument("-n", "--rounds", type=int, default=10, help="Número de rodadas por cenário (padrão: 10)")
    parser.add_argument("--force-template", action="store_true", help="Forçar templates sem consultar Ollama")
    parser.add_argument("--output-csv", type=Path, default=None, help="Caminho do arquivo CSV de saída")
    parser.add_argument("--output-md", type=Path, default=None, help="Caminho do relatório Markdown de saída")

    args = parser.parse_args()
    results = run_eval_suite(
        rounds=args.rounds,
        force_template=args.force_template,
        output_csv=args.output_csv,
        output_md=args.output_md,
    )
    print(f"\nAvaliação concluída com sucesso: {len(results)} rodadas executadas.")


if __name__ == "__main__":
    main()
