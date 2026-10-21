"""
App principal do backend COGNIS.

Rodar:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_router import get_current_user_id, router as auth_router
from .config import app_config
from .database import create_neo4j_driver, get_neo4j_driver
from .db import repository
from .db.models import User
from .db.session import create_database, get_db_session
from .github_collector import collect_repo, fetch_user_repos
from .neo4j_writer import Neo4jWriter
from .trello_collector import collect_board, fetch_user_boards
from .trello_tokens import (
    TrelloReconnectRequired,
    TrelloTokenRefreshError,
    refresh_if_needed,
)
from .projects_router import router as projects_router
from .people_router import router as people_router
from .links_router import router as links_router
from .graph_router import router as graph_router
from .metrics_router import router as metrics_router
from .sprints_router import router as sprints_router
from .analyses_router import router as analyses_router
from .ingest.scheduler import start_scheduler, stop_scheduler
from .project_sync import mark_interrupted_sync_runs
from .llm.client import check_ollama_health


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_database()
    mark_interrupted_sync_runs()
    driver = create_neo4j_driver()
    app.state.neo4j_driver = driver
    app.state.sync_executor = ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="cognis-sync"
    )
    scheduler_task = start_scheduler(app)
    app.state.sync_scheduler_task = scheduler_task
    try:
        yield
    finally:
        await stop_scheduler(scheduler_task)
        app.state.sync_executor.shutdown(wait=True)
        driver.close()


app = FastAPI(title="COGNIS API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_config.allowed_frontend_origins,
    allow_credentials=True,  # obrigatório pra cookie httpOnly ir/voltar entre front e back
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(people_router)
app.include_router(links_router)
app.include_router(graph_router)
app.include_router(metrics_router)
app.include_router(sprints_router)
app.include_router(analyses_router)


@app.middleware("http")
async def validate_request_origin(request: Request, call_next):
    if request.method.upper() != "GET":
        origin = request.headers.get("origin") or request.headers.get("referer")
        if not origin or not _matches_frontend_origin(origin):
            return JSONResponse(
                status_code=403,
                content={"detail": "Origem da requisição não autorizada"},
            )
    return await call_next(request)


def _matches_frontend_origin(value: str) -> bool:
    try:
        request_url = urlsplit(value)
        request_origin = (request_url.scheme.lower(), request_url.netloc.lower())
        return any(
            request_origin
            == (frontend.scheme.lower(), frontend.netloc.lower())
            for frontend in map(urlsplit, app_config.allowed_frontend_origins)
        )
    except ValueError:
        return False


@app.get("/health")
def health(
    response: Response,
    driver: Driver = Depends(get_neo4j_driver),
):
    try:
        driver.verify_connectivity()
    except (DriverError, Neo4jError):
        response.status_code = 503
        return {"status": "error", "neo4j": "unavailable"}

    ollama_info = check_ollama_health()
    return {
        "status": "ok",
        "neo4j": "connected",
        "ollama": ollama_info,
    }


@app.get("/auth/me")
def me(
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    user = db_session.get(User, user_id)
    return {
        "user_id": user_id,
        "email": user.email if user else None,
        "name": user.name if user else None,
        "connections": repository.get_connections(db_session, user_id),
    }


@app.delete("/auth/{provider}")
def disconnect(
    provider: str,
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    if provider not in ("github", "trello"):
        raise HTTPException(404, "provider desconhecido")
    repository.disconnect_provider(db_session, user_id, provider)
    db_session.commit()
    return {"ok": True}


# ---------------- listar o que o usuário pode sincronizar ----------------

@app.get("/github/repos")
def list_github_repos(
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    token = repository.get_provider_token(db_session, user_id, "github")
    if not token:
        raise HTTPException(400, "GitHub não conectado")
    return fetch_user_repos(token)


@app.get("/trello/boards")
def list_trello_boards(
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    try:
        token = refresh_if_needed(db_session, user_id)
    except TrelloReconnectRequired:
        raise HTTPException(401, "Trello precisa ser conectado novamente") from None
    except TrelloTokenRefreshError:
        raise HTTPException(
            502, "Não foi possível renovar a conexão com o Trello"
        ) from None
    if not token:
        raise HTTPException(400, "Trello não conectado")
    return fetch_user_boards(token)


# ---------------- sync ----------------

class SyncIn(BaseModel):
    github_repos: list[str] = []   # ex: ["owner/repo"]
    trello_boards: list[str] = []  # ex: ["idDoBoard"]


@app.post("/sync")
def sync(
    body: SyncIn,
    user_id: str = Depends(get_current_user_id),
    driver: Driver = Depends(get_neo4j_driver),
    db_session: Session = Depends(get_db_session),
):
    github_token = repository.get_provider_token(db_session, user_id, "github")
    trello_token = None
    if body.trello_boards:
        try:
            trello_token = refresh_if_needed(db_session, user_id)
        except TrelloReconnectRequired:
            raise HTTPException(
                401, "Trello precisa ser conectado novamente"
            ) from None
        except TrelloTokenRefreshError:
            raise HTTPException(
                502, "Não foi possível renovar a conexão com o Trello"
            ) from None

    if body.github_repos and not github_token:
        raise HTTPException(400, "GitHub não conectado")
    if body.trello_boards and not trello_token:
        raise HTTPException(400, "Trello não conectado")

    resultado = {"github_repos": [], "trello_boards": [], "erros": []}
    with Neo4jWriter(driver) as writer:
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
