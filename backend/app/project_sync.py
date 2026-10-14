from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from neo4j import Driver
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import repository
from .db import session as db_session
from .db.graph_schema import ensure_graph_schema
from .db.models import ProjectSource, SyncRun, utc_now
from .github_v2_collector import sync_github_project
from .identity_service import sync_people_for_project
from .linker import link_project_in_graph
from .neo4j_v2_writer import Neo4jV2Writer
from .ingest.ratelimit import RateLimitPaused
from .trello_tokens import (
    TrelloReconnectRequired,
    TrelloTokenRefreshError,
    refresh_if_needed,
)
from .trello_v2_collector import sync_trello_project

ACTIVE_STATUSES = ("queued", "running")
_active_project_ids: set[str] = set()
_active_projects_lock = threading.Lock()


def mark_interrupted_sync_runs() -> None:
    with db_session.SessionLocal() as session:
        runs = session.scalars(
            select(SyncRun).where(SyncRun.status.in_(ACTIVE_STATUSES))
        ).all()
        for run in runs:
            run.status = "failed"
            run.finished_at = utc_now()
            run.errors_json = [
                {
                    "code": "interrupted",
                    "message": "A sincronização foi interrompida pela reinicialização do servidor.",
                }
            ]
            run.progress_json = {
                "stage": "done",
                "message": "A sincronização foi interrompida.",
            }
        session.commit()


def schedule_project_sync(
    session: Session,
    user_id: str,
    project_id: str,
    driver: Driver,
    executor: ThreadPoolExecutor,
) -> SyncRun:
    project = repository.get_project_for_user(session, project_id, user_id)
    github_sources = session.scalars(
        select(ProjectSource).where(
            ProjectSource.project_id == project.id,
            ProjectSource.provider == "github",
            ProjectSource.enabled.is_(True),
        )
    ).all()
    trello_sources = session.scalars(
        select(ProjectSource).where(
            ProjectSource.project_id == project.id,
            ProjectSource.provider == "trello",
            ProjectSource.enabled.is_(True),
        )
    ).all()
    total_sources = len(github_sources) + len(trello_sources)
    if total_sources == 0:
        raise HTTPException(400, "O projeto não possui fontes ativas.")
    if github_sources and not repository.get_provider_token(session, user_id, "github"):
        raise HTTPException(400, "GitHub não conectado")
    if trello_sources:
        try:
            trello_token = refresh_if_needed(session, user_id)
        except TrelloReconnectRequired:
            raise HTTPException(401, "Trello precisa ser conectado novamente") from None
        except TrelloTokenRefreshError:
            raise HTTPException(502, "Não foi possível renovar a conexão com o Trello") from None
        if not trello_token:
            raise HTTPException(400, "Trello não conectado")

    with _active_projects_lock:
        active_run = session.scalar(
            select(SyncRun.id)
            .where(
                SyncRun.project_id == project.id,
                SyncRun.status.in_(ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if project.id in _active_project_ids or active_run is not None:
            raise HTTPException(409, "Já existe uma sincronização ativa neste projeto.")

        run = SyncRun(
            project_id=project.id,
            status="queued",
            progress_json={
                "stage": "queued",
                "done": 0,
                "total": total_sources,
                "message": "A sincronização está aguardando para iniciar.",
            },
        )
        session.add(run)
        session.commit()
        _active_project_ids.add(project.id)
        try:
            executor.submit(
                _run_project_sync,
                run.id,
                project.id,
                user_id,
                driver,
            )
        except RuntimeError as error:
            _active_project_ids.discard(project.id)
            run.status = "failed"
            run.finished_at = utc_now()
            run.errors_json = [
                {
                    "code": "WorkerUnavailable",
                    "message": "Não foi possível iniciar a sincronização.",
                }
            ]
            run.progress_json = {
                "stage": "failed",
                "message": "Não foi possível iniciar a sincronização.",
            }
            session.commit()
            raise HTTPException(
                503, "O serviço de sincronização está indisponível."
            ) from error
    return run


def _run_project_sync(
    run_id: str,
    project_id: str,
    user_id: str,
    driver: Driver,
) -> None:
    try:
        with db_session.SessionLocal() as session:
            run = session.get(SyncRun, run_id)
            if run is None:
                return
            run.status = "running"
            run.progress_json = {
                "stage": "github:commits",
                "done": 0,
                "message": "Coletando dados dos repositórios GitHub.",
            }
            session.commit()

            def update_progress(done: int, total: int, message: str) -> None:
                current_run = session.get(SyncRun, run_id)
                if current_run is None:
                    raise RuntimeError("Execução de sincronização não encontrada.")
                current_run.progress_json = {
                    "stage": "done" if done == total else "github:commits",
                    "done": done,
                    "total": total,
                    "message": message,
                }
                session.commit()

            github_sources = session.scalars(
                select(ProjectSource).where(
                    ProjectSource.project_id == project_id,
                    ProjectSource.provider == "github",
                    ProjectSource.enabled.is_(True),
                )
            ).all()
            trello_sources = session.scalars(
                select(ProjectSource).where(
                    ProjectSource.project_id == project_id,
                    ProjectSource.provider == "trello",
                    ProjectSource.enabled.is_(True),
                )
            ).all()

            ensure_graph_schema(driver)
            writer = Neo4jV2Writer(driver)
            completed: list[dict[str, Any]] = []
            errors: list[dict[str, Any]] = []

            if github_sources or (not github_sources and not trello_sources):
                result = sync_github_project(
                    session,
                    user_id,
                    project_id,
                    writer,
                    progress_callback=update_progress,
                )
                completed.extend(result.get("completed", []))
                errors.extend(result.get("errors", []))

            if trello_sources:
                trello_result = sync_trello_project(
                    session,
                    user_id,
                    project_id,
                    writer,
                    progress_callback=update_progress,
                )
                completed.extend(trello_result.get("completed", []))
                errors.extend(trello_result.get("errors", []))

            if errors and completed:
                status = "partial"
            elif errors:
                status = "failed"
            else:
                status = "success"

            node_counts: dict[str, int] = {}
            relationship_counts: dict[str, int] = {}
            unresolved_relationships = 0
            for source_result in completed:
                counts = source_result.get("counts", {})
                for label, count in counts.get("nodes", {}).items():
                    node_counts[label] = node_counts.get(label, 0) + count
                for relation, count in counts.get("relationships", {}).items():
                    relationship_counts[relation] = (
                        relationship_counts.get(relation, 0) + count
                    )
                unresolved_relationships += counts.get("unresolved_relationships", 0)

            if hasattr(driver, "session"):
                try:
                    people_stats = sync_people_for_project(driver, project_id, session)
                    if people_stats.get("people_created"):
                        node_counts["Person"] = (
                            node_counts.get("Person", 0) + people_stats["people_created"]
                        )
                    if people_stats.get("relationships_created"):
                        relationship_counts["TEM_CONTA"] = (
                            relationship_counts.get("TEM_CONTA", 0)
                            + people_stats["relationships_created"]
                        )
                except Exception as e:
                    errors.append(
                        {
                            "code": "people_sync_error",
                            "message": f"Erro ao sincronizar pessoas: {e}",
                        }
                    )

                try:
                    link_stats = link_project_in_graph(driver, project_id)
                    if link_stats.get("text_links"):
                        relationship_counts["RELACIONADA_A"] = (
                            relationship_counts.get("RELACIONADA_A", 0)
                            + link_stats["text_links"]
                        )
                except Exception as e:
                    errors.append(
                        {
                            "code": "links_sync_error",
                            "message": f"Erro ao resolver vínculos do projeto: {e}",
                        }
                    )

            current_run = session.get(SyncRun, run_id)
            if current_run is None:
                raise RuntimeError("Execução de sincronização não encontrada.")
            current_run.status = status
            current_run.finished_at = utc_now()
            current_run.progress_json = {
                "stage": "done",
                "done": len(completed) + len(errors),
                "total": len(completed) + len(errors),
                "message": (
                    "Sincronização concluída."
                    if status == "success"
                    else "Sincronização concluída com falhas."
                ),
            }
            repo_failed_count = sum(1 for e in errors if "source_id" in e)
            repos_succeeded = sum(1 for s in completed if "repository" in s)
            boards_succeeded = sum(1 for s in completed if "board" in s)
            current_run.stats_json = {
                "repositories_succeeded": repos_succeeded or len(completed),
                "repositories_failed": repo_failed_count,
                "boards_succeeded": boards_succeeded,
                "nodes": node_counts,
                "relationships": relationship_counts,
                "unresolved_relationships": unresolved_relationships,
            }
            current_run.errors_json = errors
            if status in ("success", "partial"):
                project = repository.get_project_for_user(
                    session, project_id, user_id
                )
                project.next_sync_at = utc_now() + timedelta(
                    minutes=project.sync_interval_min
                )
            session.commit()
    except RateLimitPaused as rl_exc:
        with db_session.SessionLocal() as session:
            run = session.get(SyncRun, run_id)
            if run is not None:
                run.status = "paused_rate_limit"
                run.finished_at = utc_now()
                run.errors_json = [
                    {
                        "code": "RateLimitPaused",
                        "message": str(rl_exc),
                    }
                ]
                run.progress_json = {
                    "stage": "paused_rate_limit",
                    "message": f"Sincronização pausada devido ao rate limit do GitHub até {rl_exc.reset_at.isoformat()}.",
                }
            project = repository.get_project_for_user(session, project_id, user_id)
            project.next_sync_at = rl_exc.reset_at
            session.commit()
    except Exception as error:
        with db_session.SessionLocal() as session:
            run = session.get(SyncRun, run_id)
            if run is not None:
                run.status = "failed"
                run.finished_at = utc_now()
                run.errors_json = [
                    {
                        "code": type(error).__name__,
                        "message": "Não foi possível concluir a sincronização.",
                    }
                ]
                run.progress_json = {
                    "stage": "done",
                    "message": "Não foi possível concluir a sincronização.",
                }
                project = repository.get_project_for_user(session, project_id, user_id)
                project.next_sync_at = utc_now() + timedelta(
                    minutes=project.sync_interval_min
                )
                session.commit()
    finally:
        with _active_projects_lock:
            _active_project_ids.discard(project_id)


def sync_run_payload(run: SyncRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "project_id": run.project_id,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "progress": run.progress_json or {},
        "stats": run.stats_json or {},
        "errors": run.errors_json or [],
    }
