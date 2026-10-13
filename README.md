# COGNIS

O COGNIS transforma metadados de GitHub e Trello em um grafo de colaboração. A especificação de desenvolvimento está em [`COGNIS_SPEC.md`](./COGNIS_SPEC.md), com uma cópia em [`docs/SPEC.md`](./docs/SPEC.md).

O projeto está dividido em duas aplicações:

- `frontend/`: React + Vite
- `backend/`: API FastAPI, OAuth GitHub/Trello e integração com Neo4j

## Pré-requisitos

- Python 3.11+
- Node.js e npm
- Docker Compose

## Neo4j

Na raiz do projeto, garanta que `backend/.env` existe. Se necessário, crie-o a partir do exemplo e configure uma senha local para o Neo4j:

```powershell
Copy-Item backend/env.example backend/.env
```

Em seguida, inicie o Neo4j com o volume persistente definido no Compose. O comando usa `NEO4J_PASSWORD` de `backend/.env`:

```powershell
docker compose --env-file backend/.env up -d
```

Não compartilhe nem versione `backend/.env`. O Neo4j ficará disponível em `localhost:7687` e sua interface web em `http://localhost:7474`.

## Backend (Windows / PowerShell)

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item env.example .env }
uvicorn app.main:app --reload --port 8000
```

Configure as credenciais OAuth e os segredos locais em `backend/.env`. A API fica em `http://localhost:8000`; documentação interativa em `http://localhost:8000/docs`.
O estado da conexão com o Neo4j pode ser consultado em `http://localhost:8000/health`.

## Frontend

Em outro terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

Acesse `http://localhost:5173`.

## Fixtures de contrato (GitHub e Trello)

Para capturar amostras reais redigidas para testes dos coletores, repositórios
públicos do GitHub podem ser consultados sem token. Para repositórios privados,
configure `COGNIS_FIXTURE_GITHUB_TOKEN` temporariamente usando entrada segura e
execute na raiz do projeto:

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\capture_fixtures.py --github-repo PepeSlime2/SongsMix
```

Para um repositório privado, configure o token em variável de ambiente apenas
durante a execução:

```powershell
$secureToken = Read-Host "Token GitHub" -AsSecureString
$env:COGNIS_FIXTURE_GITHUB_TOKEN = [System.Net.NetworkCredential]::new("", $secureToken).Password
.\backend\.venv\Scripts\python.exe .\scripts\capture_fixtures.py --github-repo owner/repo
Remove-Item Env:COGNIS_FIXTURE_GITHUB_TOKEN
Remove-Variable secureToken
```

Para o Trello, use o mesmo padrão de entrada segura com `COGNIS_FIXTURE_TRELLO_TOKEN`
e `--trello-board-id <id>`. O script não imprime tokens ou respostas da API;
remove e-mails, logins, URLs pessoais e texto livre antes de salvar em
`backend/tests/fixtures/`. Revise as amostras antes de adicioná-las ao Git e nunca
coloque tokens em arquivos versionados.
