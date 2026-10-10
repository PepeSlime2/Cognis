"""
App principal do backend COGNIS.

Rodar:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .auth_router import get_current_user_id, router as auth_router
from .config import app_config
from .github_collector import collect_repo, fetch_user_repos
from .neo4j_writer import Neo4jWriter
from .trello_collector import collect_board, fetch_user_boards
from .user_store import UserStore

app = FastAPI(title="COGNIS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[app_config.frontend_url],
    allow_credentials=True,  # obrigatório pra cookie httpOnly ir/voltar entre front e back
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


@app.get("/auth/me")
def me(user_id: str = Depends(get_current_user_id)):
    with UserStore() as store:
        connections = store.get_connections(user_id)
    return {"user_id": user_id, "connections": connections}


@app.delete("/auth/{provider}")
def disconnect(provider: str, user_id: str = Depends(get_current_user_id)):
    if provider not in ("github", "trello"):
        raise HTTPException(404, "provider desconhecido")
    with UserStore() as store:
        store.disconnect_provider(user_id, provider)
    return {"ok": True}


# ---------------- listar o que o usuário pode sincronizar ----------------

@app.get("/github/repos")
def list_github_repos(user_id: str = Depends(get_current_user_id)):
    with UserStore() as store:
        token = store.get_provider_token(user_id, "github")
    if not token:
        raise HTTPException(400, "GitHub não conectado")
    return fetch_user_repos(token)


@app.get("/trello/boards")
def list_trello_boards(user_id: str = Depends(get_current_user_id)):
    with UserStore() as store:
        token = store.get_provider_token(user_id, "trello")
    if not token:
        raise HTTPException(400, "Trello não conectado")
    return fetch_user_boards(token)


# ---------------- sync ----------------

class SyncIn(BaseModel):
    github_repos: list[str] = []   # ex: ["owner/repo"]
    trello_boards: list[str] = []  # ex: ["idDoBoard"]


@app.post("/sync")
def sync(body: SyncIn, user_id: str = Depends(get_current_user_id)):
    with UserStore() as store:
        github_token = store.get_provider_token(user_id, "github")
        trello_token = store.get_provider_token(user_id, "trello")

    if body.github_repos and not github_token:
        raise HTTPException(400, "GitHub não conectado")
    if body.trello_boards and not trello_token:
        raise HTTPException(400, "Trello não conectado")

    resultado = {"github_repos": [], "trello_boards": [], "erros": []}
    with Neo4jWriter() as writer:
        writer.ensure_constraints()

        for repo in body.github_repos:
            try:
                collect_repo(github_token, repo, writer)
                resultado["github_repos"].append(repo)
            except Exception as e:
                resultado["erros"].append(f"github:{repo}: {e}")

        for board_id in body.trello_boards:
            try:
                collect_board(trello_token, board_id, writer)
                resultado["trello_boards"].append(board_id)
            except Exception as e:
                resultado["erros"].append(f"trello:{board_id}: {e}")

    return resultado
