# Decisões de arquitetura

As decisões abaixo transcrevem as escolhas da [especificação](./SPEC.md). Mudanças futuras devem ser registradas aqui no mesmo formato.

| ID | Decisão | Motivo | Alternativa descartada |
|---|---|---|---|
| D-01 | Backend 100% Python (FastAPI), sem Node.js. | Centraliza grafos, IA e relatórios no backend existente. | Node.js + Python. |
| D-02 | Métricas em Python puro com NetworkX sobre grafos montados em memória por projeto/janela; interface permite plugar GDS depois. | Grafos de equipe são pequenos, NetworkX é determinístico e fácil de testar. | Neo4j GDS como motor principal. |
| D-03 | Neo4j guarda fatos do grafo; SQLite guarda estado da aplicação. | Jobs, snapshots e relatórios são dados relacionais/documentais. | Guardar tudo no Neo4j. |
| D-04 | LLM local via Ollama, modelo `llama3.1:8b`, acessado por HTTP. | Privacidade e menor número de dependências. | SDK Ollama ou serviço remoto. |
| D-05 | O LLM apenas interpreta métricas e signals determinísticos; números são validados e há fallback por template. | Reduz risco de erros aritméticos e alucinações. | LLM analisando dados brutos. |
| D-06 | O projeto é o tenant; cada projeto pertence a um usuário na v1. | Isolamento simples e seguro. | Grafo global compartilhado. |
| D-07 | Relatórios usam um modelo JSON e renderizadores HTML, DOCX e PDF. | Compatibilidade com Windows e formatos previstos. | WeasyPrint ou Playwright. |
| D-08 | Sem Alembic na v1; usar `Base.metadata.create_all()` e recriar o banco SQLite de desenvolvimento quando o schema mudar. | Menos componentes na versão inicial. | Migrações versionadas. |
| D-09 | Frontend React 19 + Vite + TypeScript + CSS Modules; Cytoscape para o grafo e SVG próprio para linhas. | Mantém a stack existente e evita incompatibilidade com wrappers. | `react-cytoscapejs` e Recharts. |
| D-10 | Jobs usam `ThreadPoolExecutor`, tabela `sync_runs` e agendamento asyncio. | Evita adicionar Celery/Redis ou APScheduler. | Celery/Redis ou APScheduler. |
| D-11 | Persistir apenas metadados; não guardar corpos de commits, PRs ou comentários nem e-mails em claro. | Privacidade/LGPD e minimização de dados. | Persistir texto completo. |
| D-12 | Rótulos dos nós em inglês e tipos de relação em português. | Consistência do modelo do grafo. | — |

## Histórico

- 2026-10-10: decisões iniciais transcritas da COGNIS_SPEC.md (v1.0).
