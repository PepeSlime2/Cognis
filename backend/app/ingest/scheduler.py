from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from neo4j import Driver
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import or_, select

from ..db import session as db_session
from ..db.models import Project, SyncRun, utc_now
from ..project_sync import ACTIVE_STATUSES, schedule_project_sync

logger = logging.getLogger(__name__)


def execute_scheduler_tick(
    driver: Driver,
    executor: ThreadPoolExecutor,
) -> list[str]:
    """
    Verifica no banco projetos com auto_sync=True e next_sync_at <= now (ou nulo),
    sem execução ativa, e agenda a sincronização.
    Retorna os IDs dos projetos que foram enfileirados.
    """
    scheduled_project_ids: list[str] = []
    now = utc_now()

    with db_session.SessionLocal() as session:
        active_project_ids_subquery = (
            select(SyncRun.project_id)
            .where(SyncRun.status.in_(ACTIVE_STATUSES))
        )

        projects = session.scalars(
            select(Project)
            .where(
                Project.auto_sync.is_(True),
                or_(
                    Project.next_sync_at.is_(None),
                    Project.next_sync_at <= now,
                ),
                Project.id.not_in(active_project_ids_subquery),
            )
        ).all()

        for project in projects:
            project_id = project.id
            user_id = project.user_id
            try:
                schedule_project_sync(
                    session,
                    user_id,
                    project_id,
                    driver,
                    executor,
                )
                project.next_sync_at = now + timedelta(
                    minutes=project.sync_interval_min
                )
                session.commit()
                scheduled_project_ids.append(project_id)
            except HTTPException as exc:
                if exc.status_code == 409:
                    continue
                logger.warning(
                    "Scheduler pulou projeto %s: status_code=%s, detail=%s",
                    project_id,
                    exc.status_code,
                    exc.detail,
                )
                project.next_sync_at = now + timedelta(
                    minutes=project.sync_interval_min
                )
                session.commit()
            except Exception as exc:
                logger.exception(
                    "Erro ao submeter projeto %s pelo scheduler: %s",
                    project_id,
                    exc,
                )
                project.next_sync_at = now + timedelta(
                    minutes=project.sync_interval_min
                )
                session.commit()

    return scheduled_project_ids


async def run_scheduler_tick(app: FastAPI) -> list[str]:
    """Executa um ciclo do scheduler em thread separada para não bloquear o loop de eventos."""
    driver: Driver | None = getattr(app.state, "neo4j_driver", None)
    executor: ThreadPoolExecutor | None = getattr(app.state, "sync_executor", None)
    if driver is None or executor is None:
        return []
    return await asyncio.to_thread(execute_scheduler_tick, driver, executor)


async def _scheduler_loop(app: FastAPI, poll_interval_seconds: float) -> None:
    logger.info(
        "Scheduler de sincronização ativo (intervalo de verificação: %.1fs)",
        poll_interval_seconds,
    )
    while True:
        try:
            await asyncio.sleep(poll_interval_seconds)
            await run_scheduler_tick(app)
        except asyncio.CancelledError:
            logger.info("Scheduler de sincronização cancelado.")
            break
        except Exception as exc:
            logger.exception("Erro durante ciclo do scheduler: %s", exc)


def start_scheduler(
    app: FastAPI, poll_interval_seconds: float | None = None
) -> asyncio.Task[Any] | None:
    """Inicia a tarefa periódica em background para agendamento de sincronizações."""
    if os.getenv("COGNIS_DISABLE_SCHEDULER") == "1":
        logger.info("Scheduler de sincronização desabilitado por variável de ambiente.")
        return None

    if poll_interval_seconds is None:
        try:
            poll_interval_seconds = float(
                os.getenv("COGNIS_SYNC_SCHEDULER_INTERVAL", "60.0")
            )
        except ValueError:
            poll_interval_seconds = 60.0

    return asyncio.create_task(_scheduler_loop(app, poll_interval_seconds))


async def stop_scheduler(task: asyncio.Task[Any] | None) -> None:
    """Para o scheduler cancelando a tarefa e aguardando sua finalização."""
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.warning("Exceção ao encerrar o scheduler: %s", exc)
