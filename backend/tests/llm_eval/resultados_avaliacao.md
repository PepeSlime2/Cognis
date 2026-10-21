# Relatório de Avaliação do LLM — COGNIS

> Avaliação automatizada de fidelidade e conformidade de IA local (SPEC §9.9, §18.2).
> Data de execução: 2026-10-21 21:27:39 UTC
> Modelo avaliado: `llama3.1:8b` (Ollama up: False)

## Resumo Consolidado

- **Total de avaliações**: 50 (5 cenários × 10 rodadas)
- **% JSON válido no schema Pydantic**: **100.0%** (50/50)
- **% Aprovado no validador sem retry**: **100.0%** (50/50)
- **Média de violações por tentativa**: 0.0
- **Tempo médio de resposta**: 0.0 s

## Resultados por Cenário

| Cenário | Rodadas | % JSON Válido | % Aprovado sem Retry | Média Violações | Tempo Médio (s) |
|---|---|---|---|---|---|
| `bus_factor` | 10 | 100.0% | 100.0% | 0.0 | 0.0 s |
| `dados_insuficientes` | 10 | 100.0% | 100.0% | 0.0 | 0.0 s |
| `equipe_saudavel` | 10 | 100.0% | 100.0% | 0.0 | 0.0 s |
| `gargalo_review` | 10 | 100.0% | 100.0% | 0.0 | 0.0 s |
| `silos` | 10 | 100.0% | 100.0% | 0.0 | 0.0 s |

## Tabela Detalhada para Anotação Humana (TCC §18.2)

| Cenário | Rodada | JSON OK | Aprovado sem Retry | Violações | Source | Tempo (s) | Alucinação Humana (0/1) | Utilidade (1–5) |
|---|---|---|---|---|---|---|---|---|
| `bus_factor` | 1 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `bus_factor` | 2 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `bus_factor` | 3 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `bus_factor` | 4 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `bus_factor` | 5 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `bus_factor` | 6 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `bus_factor` | 7 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `bus_factor` | 8 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `bus_factor` | 9 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `bus_factor` | 10 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `dados_insuficientes` | 1 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `dados_insuficientes` | 2 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `dados_insuficientes` | 3 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `dados_insuficientes` | 4 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `dados_insuficientes` | 5 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `dados_insuficientes` | 6 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `dados_insuficientes` | 7 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `dados_insuficientes` | 8 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `dados_insuficientes` | 9 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `dados_insuficientes` | 10 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `equipe_saudavel` | 1 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `equipe_saudavel` | 2 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `equipe_saudavel` | 3 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `equipe_saudavel` | 4 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `equipe_saudavel` | 5 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `equipe_saudavel` | 6 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `equipe_saudavel` | 7 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `equipe_saudavel` | 8 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `equipe_saudavel` | 9 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `equipe_saudavel` | 10 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `gargalo_review` | 1 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `gargalo_review` | 2 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `gargalo_review` | 3 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `gargalo_review` | 4 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `gargalo_review` | 5 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `gargalo_review` | 6 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `gargalo_review` | 7 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `gargalo_review` | 8 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `gargalo_review` | 9 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `gargalo_review` | 10 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `silos` | 1 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `silos` | 2 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `silos` | 3 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `silos` | 4 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `silos` | 5 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `silos` | 6 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `silos` | 7 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `silos` | 8 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `silos` | 9 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
| `silos` | 10 | Sim | Sim | 0 | `template` | 0.0 | 0 | 5 |
