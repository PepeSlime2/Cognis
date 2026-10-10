# COGNIS

O projeto está dividido em duas aplicações:

- `frontend/`: React + Vite
- `backend/`: API FastAPI, OAuth GitHub/Trello e integração com Neo4j

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

Acesse `http://localhost:5173`.

## Backend

No Windows:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item env.example .env
uvicorn main:app --reload --port 8000
```

Configure os segredos OAuth e do Neo4j no `backend/.env`. O Neo4j precisa estar disponível em `localhost:7687`. Para iniciar com Docker:

```powershell
docker run -d --name cognis-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/senha neo4j:5
```

Documentação da API: `http://localhost:8000/docs`.

Para executar a sincronização sem a API:

```powershell
cd backend
python run_sync.py
```
