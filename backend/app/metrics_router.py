from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from neo4j import Driver
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_router import get_current_user_id
from .database import get_neo4j_driver
from .db import repository
from .db.models import Project, Sprint
from .db.session import get_db_session
from .metrics.registry import get_catalog_dict
from .metrics.service import get_metrics_bundle
from .metrics.windows import default_window, parse_window, window_from_sprint

router = APIRouter(tags=["metrics"])


@router.get("/metrics/catalog")
def get_metrics_catalog():
    """Retorna o catálogo estático de métricas com fórmulas e descrições PT-BR (SPEC §7.2)."""
    return get_catalog_dict()


def _resolve_window(
    project: Project,
    db: Session,
    from_date: str | None,
    to_date: str | None,
    sprint_id: str | None,
):
    if sprint_id:
        sprint = db.execute(
            select(Sprint).where(Sprint.id == sprint_id, Sprint.project_id == project.id)
        ).scalar_one_or_none()
        if sprint is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sprint não encontrada",
            )
        return window_from_sprint(sprint, timezone=project.timezone)
    if from_date and to_date:
        try:
            return parse_window(from_date, to_date, timezone=project.timezone)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(err),
            ) from err
    return default_window(timezone=project.timezone)


@router.get("/projects/{pid}/metrics")
def get_project_metrics(
    pid: str,
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    sprint_id: str | None = Query(None),
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db_session),
    neo4j_driver: Driver = Depends(get_neo4j_driver),
):
    """Calcula ou recupera do snapshot cache o MetricsBundle do projeto (SPEC §7.5)."""
    project = repository.get_project_for_user(db, pid, user_id)
    window = _resolve_window(project, db, from_date, to_date, sprint_id)
    bundle = get_metrics_bundle(
        db=db,
        neo4j_driver=neo4j_driver,
        project=project,
        window=window,
        force_refresh=refresh,
    )
    return bundle


@router.get("/projects/{pid}/signals")
def get_project_signals(
    pid: str,
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    sprint_id: str | None = Query(None),
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db_session),
    neo4j_driver: Driver = Depends(get_neo4j_driver),
):
    """Retorna a lista de signals determinísticos detectados para a janela (SPEC §8 e §11)."""
    project = repository.get_project_for_user(db, pid, user_id)
    window = _resolve_window(project, db, from_date, to_date, sprint_id)
    bundle = get_metrics_bundle(
        db=db,
        neo4j_driver=neo4j_driver,
        project=project,
        window=window,
        force_refresh=refresh,
    )
    return bundle.get("signals", [])
