# COGNIS — Análise de Redes de Colaboração e Fluxo de Software

O **COGNIS** é uma plataforma que transforma dados e metadados de engenharia de software (GitHub e Trello) em um **grafo de colaboração multidimensional**, calculando métricas de redes e fluxo de processos em Python puro, detectando padrões de risco determinísticos (*signals*), fornecendo interpretações contextuais via LLM local (Ollama com Llama 3.1 8B) com validação anti-alucinação estrita e renderizando uma visualização interativa de ponta com Cytoscape ("Constelação viva") e exportação de relatórios profissionais em HTML, DOCX e PDF.

---

## Sumário

- [Visão Geral e Arquitetura](#visão-geral-e-arquitetura)
- [Pré-requisitos](#pré-requisitos)
- [Guia Rápido de Instalação e Execução](#guia-rápido-de-instalação-e-execução)
- [Dataset de Demonstração (Seed Demo)](#dataset-de-demonstração-seed-demo)
- [Roteiro de Exploração da Interface](#roteiro-de-exploração-da-interface)
- [Suíte de Testes e Validação](#suíte-de-testes-e-validação)
- [Segurança, Ética e LGPD](#segurança-ética-e-lgpd)
- [Documentação Técnica](#documentação-técnica)

---

## Visão Geral e Arquitetura

O sistema é dividido em duas aplicações principais com isolamento estrito de responsabilidades:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React 19 + Vite)                      │
│   • Visualização do Grafo (Cytoscape + layout fCoSE + Efeitos "Constelação")│
│   • Séries Temporais SVG nativas (EvolutionChart)                       │
│   • Painéis de Signals, Métricas, Pessoas, Relatórios e Configurações  │
└────────────────────────────────────▲───────────────────────────────────┘
                                     │ HTTP REST / Cookies de Sessão
┌────────────────────────────────────▼───────────────────────────────────┐
│                        BACKEND (FastAPI + Python 3.11)                 │
│   • Motor de Métricas em Python Puro + NetworkX (Grafos A, B, C, D)    │
│   • Motor Determinístico de Signals (15 regras pt-BR sem IA)           │
│   • Pipeline LLM Local (Ollama llama3.1:8b) + Validador Anti-Alucinação│
│   • Renderizadores de Relatórios (HTML autocontido, Word DOCX, PDF)   │
└───────────────────▲───────────────────────────────▲────────────────────┘
                    │                               │
┌───────────────────▼────────────┐  ┌───────────────▼────────────────────┐
│         SQLite (Local)         │  │          Neo4j 5 (Docker)          │
│   • Usuários, Sessões, Sprints │  │   • Fatos do Grafo (Pessoas, PRs,  │
│   • Conexões e Tokens Fernet   │  │     Commits, Reviews, Tarefas)     │
│   • Snapshots, Análises e Jobs │  │   • Consultas parametrizadas (pid) │
└────────────────────────────────┘  └────────────────────────────────────┘
```

- **Métricas são determinísticas:** Calculadas exclusivamente em Python com NetworkX. O modelo de linguagem **nunca** faz aritmética, somas ou estimativas de números.
- **Validação anti-alucinação:** Todo texto gerado por IA passa por um validador estrito que confere cada número e referência citada contra os fatos quantitativos antes de exibir ou salvar. Se o Ollama estiver offline ou reprovar na validação, o sistema aciona fallback automático para templates determinísticos.
- **Isolamento de tenant:** Todo acesso a dados filtra estritamente por `project_id` e valida a propriedade do usuário logado.

---

## Pré-requisitos

1. **Python 3.11+** (com `pip` e suporte a ambientes virtuais)
2. **Node.js** (v18+ ou v20+) e **npm**
3. **Docker & Docker Compose** (para executar o container do Neo4j 5)
4. *(Opcional)* **Ollama** instalado localmente com o modelo `llama3.1:8b`:
   ```bash
   ollama pull llama3.1:8b
   ```
   *Nota: Se o Ollama não estiver instalado ou rodando, o COGNIS funciona perfeitamente utilizando o gerador de análise determinístico por regras (selo de fallback).*

---

## Guia Rápido de Instalação e Execução

### 1. Clonar o repositório e configurar variáveis de ambiente

Na raiz do projeto:

```powershell
# Criar o arquivo de configuração do backend a partir do modelo
Copy-Item backend/env.example backend/.env
```

> **Importante:** Revise `backend/.env` se desejar alterar credenciais locais. Para desenvolvimento local padrão, os valores de exemplo funcionam diretamente.

### 2. Iniciar o banco de dados Neo4j

Suba o container do Neo4j via Docker Compose:

```powershell
docker compose --env-file backend/.env up -d
```

O Neo4j estará acessível em `bolt://localhost:7687` e a interface web do Neo4j Browser em `http://localhost:7474`.

### 3. Configurar e executar o Backend

Abra um terminal na pasta `backend`:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- A API estará disponível em: `http://localhost:8000`
- Documentação interativa Swagger: `http://localhost:8000/docs`
- Health check de infraestrutura: `http://localhost:8000/health`

### 4. Configurar e executar o Frontend

Abra outro terminal na pasta `frontend`:

```powershell
cd frontend
npm install
npm run dev
```

- A interface web estará disponível em: `http://localhost:5173`

---

## Dataset de Demonstração (Seed Demo)

O COGNIS possui um gerador de dados sintéticos determinísticos calibrado para demonstrar e testar todas as funcionalidades do sistema sem depender de credenciais externas do GitHub ou Trello.

Para criar o projeto demo e seus dados:

```powershell
# Na raiz do projeto (com o ambiente virtual do backend ativado):
python scripts/seed_demo.py
```

O script criará de forma idempotente:
- **Usuário Demo:** `demo@cognis.test` (Senha: `demo123456`)
- **Projeto:** `Demo COGNIS`
- **4 Sprints** com cronologia de eventos completa
- **6 Colaboradores** com os 6 padrões de engenharia plantados (§15.2):

| Padrão Plantado | Detalhes do Cenário | Resultado Observável no Sistema |
|---|---|---|
| **Concentração de Reviews** | Bruno realiza ~60% de todas as revisões de código | Disparo do signal `REVIEW_CONCENTRATION` e alerta de sobrecarga |
| **Gargalo de Módulo (Bus Factor 1)** | Diego é o autor exclusivo do módulo crítico `api/payments` | Disparo de `BUS_FACTOR_1` e nó com halo de risco pulsante |
| **Silos de Especialidade** | Backend (Ana, Bruno, Diego) e Frontend (Carla, Elisa) isolados | Detecção de 2 comunidades com poucas pontes (`SILOS`) |
| **Membro Isolado** | Felipe atua de forma periférica com $\le 1$ colaborador | Disparo de `ISOLATED_MEMBER` com halo de atenção |
| **Atraso de Tarefas** | Sprint 3 com ~30% de tarefas entregues após o prazo | Disparo de `LATE_RATE_HIGH` ao selecionar a Sprint 3 |
| **Queda de Colaboração** | Sprint 4 com redução drástica na densidade e peso/pessoa | Disparo de `COLLAB_DROP` ao comparar períodos |

---

## Roteiro de Exploração da Interface

Após executar o seed demo, acesse `http://localhost:5173/login`:

1. **Autenticação**:
   - Entre com `demo@cognis.test` / `demo123456`.
2. **Dashboard de Projetos**:
   - Veja o card do projeto **Demo COGNIS** com contadores e atalhos rápidos. Clique em **Abrir Grafo →**.
3. **Explorando o Grafo de Colaboração (`/p/demo-cognis-project`)**:
   - **Visualização**: Nós dimensionados por métricas de centralidade (Grau, PageRank, Intermediação) e coloridos por comunidades Louvain ou nível de risco.
   - **Interações**:
     - *Hover*: destaca vizinhos imediatos e atenua os demais nós.
     - *Clique em um nó*: abre a aba de detalhes na barra lateral direita, calculando métricas individuais em tempo real e ativando animação de fluxo nas arestas incidentes.
     - *Caminho Mais Curto*: selecione origem e destino para ver o pulso luminoso viajando pelos intermediários.
     - *Modo Foco*: isola o nó e seus parceiros diretos no canvas.
4. **Painel de Signals e Diagnósticos Interativos**:
   - Na barra lateral direita, clique na aba **Insights**:
   - Veja os cartões ordenados por severidade (`high`, `medium`, `info`).
   - Clique em qualquer sinal (ex.: `BUS_FACTOR_1` em Diego ou `REVIEW_CONCENTRATION` em Bruno) para ver a câmera animar e destacar automaticamente os nós envolvidos.
5. **Geração de Análise com IA / Templates (`/p/demo-cognis-project/analysis`)**:
   - Clique em **Gerar Análise com IA**:
   - Se o Ollama estiver ativo, a análise é produzida pelo modelo local `llama3.1:8b` (Selo verde).
   - Se o Ollama estiver inativo, o motor determinístico gera o relatório contextual por templates (Selo âmbar).
   - Abra o modal **Ver dados usados** para inspecionar o payload exato de fatos JSON utilizados, com suporte a toggle de anonimização reversível (*Pessoa A*, *Pessoa B*).
6. **Métricas da Equipe & Séries Temporais (`/p/demo-cognis-project/metrics`)**:
   - Catálogo estruturado com tooltips e fórmulas matemáticas oficiais.
   - Componente `EvolutionChart` em SVG nativo comparando métricas ao longo das sprints com alerta visual para quedas de colaboração.
7. **Pessoas e Resolução de Identidades (`/p/demo-cognis-project/people`)**:
   - Tabela alfabética (sem rankings) com índices ponderados e contadores brutos.
   - Modais para unificação (*merge*) e separação (*split*) de identidades entre provedores e mapeamento de links Git/Trello.
8. **Exportação de Relatórios Executivos**:
   - Clique em **Exportar Relatório** na barra lateral esquerda:
   - Escolha entre os 5 tipos canônicos (Sprint, Gerencial, Individual, Gargalos, Colaboração) e baixe nos formatos **HTML autocontido**, **Word (.docx)** ou **PDF**.
9. **Configurações e Exclusão LGPD (`/settings`)**:
   - Gerenciamento de conexões GitHub/Trello e mapeamento de colunas Kanban.
   - **Zona de Perigo (LGPD)**: botão de exclusão permanente que apaga o grafo no Neo4j, arquivos gerados e dados no banco SQLite com confirmação em 2 passos.

---

## Suíte de Testes e Validação

O projeto possui cobertura abrangente de testes automatizados unitários, de integração, performance e segurança.

### 1. Testes do Backend (`pytest`)

```powershell
cd backend
pytest -q
```
*Executa 223 testes automatizados cobrindo cálculo matemático de métricas, validador LLM, renderizadores de relatórios (HTML, DOCX, PDF), auditoria de segurança multi-tenant e exclusão LGPD.*

### 2. Lint e Build do Frontend

```powershell
cd frontend
npm run lint
npm run build
```
*Valida conformidade com regras ESLint do TypeScript e compila o bundle de produção via Vite sem erros.*

### 3. Benchmark de Performance

Mede o tempo de resposta do motor analítico com carga sintética densa (40 pessoas, 400 tarefas, 250 PRs, 500+ reviews):

```powershell
python backend/scripts/run_perf_benchmark.py
```
*Resultados registrados em [`docs/perf.md`](./docs/perf.md): cálculo frio processado em ~0,098 s (< 5% do limite estipulado de 2,0 s).*

### 4. Avaliação do LLM

Executa as 5 fixtures de validação do TCC contra o modelo local ou validador:

```powershell
python backend/tests/llm_eval/run_eval.py -n 5
```

---

## Segurança, Ética e LGPD

1. **Checklist de Segurança (§13.1)**:
   - Credenciais de provedores e tokens armazenados com criptografia simétrica Fernet.
   - Isolamento estrito de tenant: toda consulta valida que o recurso pertence ao usuário autenticado (retornando `404 Not Found` em acessos não autorizados para impedir enumeração).
   - Consultas Cypher no Neo4j 100% parametrizadas com `project_id`.
   - Rate limiting no endpoint de autenticação (5 tentativas/min por IP+e-mail).
   - Proteção CSRF com validação de `Origin` e cookie seguro `SameSite=Lax`.
   - Relatório detalhado disponível em [`docs/security_audit.md`](./docs/security_audit.md).

2. **Uso Responsável das Métricas e Lei de Goodhart (§13.4)**:
   - Indicadores destinam-se a identificar gargalos de processo e padrões de colaboração, **não a avaliar desempenho ou mérito individual**.
   - O sistema não adota rankings punitivos (*leaderboards*).
   - Todas as telas e relatórios individuais apresentam avisos de uso ético responsável.

3. **Direito à Eliminação / LGPD (§13.3)**:
   - A exclusão do projeto apaga permanentemente todos os nós e arestas no Neo4j (`MATCH (n {project_id: $pid}) ... DETACH DELETE n`), remove todos os arquivos físicos gerados no disco e limpa os registros do banco relacional.

---

## Documentação Técnica

- [`COGNIS_SPEC.md`](./COGNIS_SPEC.md) / [`docs/SPEC.md`](./docs/SPEC.md): Especificação técnica e arquitetural completa do sistema.
- [`docs/decisions.md`](./docs/decisions.md): Registro de decisões de arquitetura (ADRs) e histórico datado de entregas.
- [`docs/perf.md`](./docs/perf.md): Resultados das medições de performance para 400 nós.
- [`docs/security_audit.md`](./docs/security_audit.md): Matriz de evidências e auditoria de segurança conforme o checklist §13.1.
- [`docs/open-questions.md`](./docs/open-questions.md): Resoluções das questões arquiteturais do projeto.
