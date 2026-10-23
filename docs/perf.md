# COGNIS — Relatório de Desempenho e Medições (F10.3)

> **Data da aferição:** 2026-10-22  
> **Ambiente de Teste:** Windows 10 (AMD64) | Python 3.11.9 (CPython)  
> **Banco de Dados:** SQLite (snapshots em disco) + Neo4j Community  
> **Critério de Aceite SPEC F10.3:** Grafo com até 400 nós fluidos; bundle de métricas < 2 s; medições registradas em `docs/perf.md`.

---

## 1. Resumo Executivo dos Resultados

Todas as metas de desempenho estabelecidas na especificação do projeto (§12.5 e §16 F10.3) foram superadas com ampla margem de segurança:

| Cenário de Teste | Meta / Limite do SPEC | Média Obtida | Mínimo | Máximo | Status |
|---|---|---|---|---|---|
| **Serialização Cytoscape (400 nós, 1.490 arestas)** | < 200 ms | **6,44 ms** | 2,41 ms | 54,08 ms | ✅ **Aprovado** |
| **Cálculo do Bundle de Métricas (Frio / Sem Cache)** | < 2,00 s | **0,098 s (97,9 ms)** | 0,081 s | 0,137 s | ✅ **Aprovado** (< 5% do teto) |
| **Recuperação do Bundle (Snapshot Cache Hit)** | < 50 ms | **1,97 ms** | 1,53 ms | 2,40 ms | ✅ **Aprovado** |

---

## 2. Metodologia de Benchmark

Os testes foram executados de forma determinística utilizando o script de benchmark [`backend/scripts/run_perf_benchmark.py`](file:///c:/Users/pedro/Documents/TCC_Sistema/TCC_Sistema/backend/scripts/run_perf_benchmark.py) e a suíte automatizada de testes [`backend/tests/test_performance.py`](file:///c:/Users/pedro/Documents/TCC_Sistema/TCC_Sistema/backend/tests/test_performance.py).

### Carga de Dados Sintética Densa:
- **Pessoas / Desenvolvedores:** 40 integrantes ativos na equipe.
- **Tarefas (Tasks):** 400 tarefas distribuídas em estados `done`, `doing` e `todo`, com dependências críticas (`TaskDependencyFact`), datas de criação, início, entrega planejada e retrabalho intencional.
- **Pull Requests e Revisões:** 250 PRs com 500+ revisões cruzadas (`APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`).
- **Interações e Comunicação:** 300 comentários entre membros e dezenas de commits vinculados a múltiplos módulos do repositório.

---

## 3. Decomposição do Tempo de Cálculo por Etapa

A tabela abaixo detalha o tempo gasto em cada camada do motor analítico em Python puro com NetworkX para o conjunto de 40 colaboradores e 400 tarefas:

```text
+-------------------------------------------------------------+
| Etapa do Pipeline                               | Duração   |
+-------------------------------------------------------------+
| 1. Construção do CollabGraph (G_d, G_u)         |   9,93 ms |
| 2. Métricas de Grafo NetworkX (Louvain/Pagerank)|  53,11 ms |
| 3. Métricas Individuais de Pessoa (Catálogo B)  |   1,90 ms |
| 4. Métricas de Equipe, Silos e Bus Factor (C)   |  11,53 ms |
| 5. Métricas de Fluxo, WIP e Rework (D)          |   5,30 ms |
| 6. Detecção Determinística de Sinais de Risco   |   0,48 ms |
+-------------------------------------------------------------+
| Soma Total das Etapas Analíticas                |  82,26 ms |
+-------------------------------------------------------------+
```

### Destaques Arquiteturais:
1. **NetworkX e Algoritmos de Grafos:** Os cálculos de `betweenness_centrality`, `closeness_centrality`, `pagerank` e particionamento de comunidades via Louvain consomem ~53 ms para uma rede de 40 colaboradores densamente conectados.
2. **Snapshot Caching (SPEC §7.5):** Ao consultar a mesma janela temporal com a mesma versão de dados e configurações (`config_hash`), o backend evita o recálculo e responde diretamente do cache em menos de 2 milissegundos.
3. **Serialização e Truncamento Seguro:** Para visualização no Cytoscape, a função `build_cytoscape_elements` agrega os 400 nós e até 1.500 arestas, calculando graus normalizados e agrupamentos de arestas em apenas 6,4 ms.

---

## 4. Como Reproduzir as Medições

Para reproduzir os testes e verificar os tempos na sua máquina:

```powershell
# No diretório backend/
python -m scripts.run_perf_benchmark

# Ou rodar a suíte de testes com validação automática de asserts:
pytest tests/test_performance.py -v
```
