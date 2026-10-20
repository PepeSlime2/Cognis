from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_router import get_current_user_id
from .db import repository
from .db.models import Sprint
from .db.session import get_db_session
from .metrics.windows import get_zone_info, parse_window

router = APIRouter(prefix="/projects", tags=["sprints"])


class SprintCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    start_date: str = Field(..., description="Data de início civil (YYYY-MM-DD)")
    end_date: str = Field(..., description="Data de término civil (YYYY-MM-DD)")


class SprintUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    start_date: str | None = Field(None, description="Data de início civil (YYYY-MM-DD)")
    end_date: str | None = Field(None, description="Data de término civil (YYYY-MM-DD)")


def _format_sprint_dict(sprint: Sprint, timezone: str) -> dict[str, Any]:
    tz = get_zone_info(timezone)
    start_civil = sprint.start_date.astimezone(tz).date().isoformat() if sprint.start_date else None
    end_civil = sprint.end_date.astimezone(tz).date().isoformat() if sprint.end_date else None

    return {
        "id": sprint.id,
        "project_id": sprint.project_id,
        "name": sprint.name,
        "start_date": sprint.start_date.isoformat() if sprint.start_date else None,
        "end_date": sprint.end_date.isoformat() if sprint.end_date else None,
        "start_civil": start_civil,
        "end_civil": end_civil,
    }


@router.get("/{project_id}/sprints")
def list_project_sprints(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Lista todas as sprints cadastradas para o projeto."""
    project = repository.get_project_for_user(db, project_id, user_id)
    sprints = list(
        db.scalars(
            select(Sprint)
            .where(Sprint.project_id == project.id)
            .order_by(Sprint.start_date.asc())
        ).all()
    )
    return [_format_sprint_dict(s, project.timezone) for s in sprints]


@router.post("/{project_id}/sprints", status_code=status.HTTP_201_CREATED)
def create_project_sprint(
    project_id: str,
    payload: SprintCreateRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Cria uma nova sprint vinculada ao projeto."""
    project = repository.get_project_for_user(db, project_id, user_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O nome da sprint não pode ser vazio.",
        )

    try:
        w = parse_window(payload.start_date, payload.end_date, timezone=project.timezone)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err

    sprint = Sprint(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name=name,
        start_date=w.start_utc,
        end_date=w.end_utc - dt.timedelta(seconds=1),
    )
    db.add(sprint)
    db.commit()
    db.refresh(sprint)

    return _format_sprint_dict(sprint, project.timezone)


@router.put("/{project_id}/sprints/{sprint_id}")
def update_project_sprint(
    project_id: str,
    sprint_id: str,
    payload: SprintUpdateRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Atualiza nome e/ou datas de uma sprint existente."""
    project = repository.get_project_for_user(db, project_id, user_id)
    sprint = db.scalar(
        select(Sprint).where(
            Sprint.id == sprint_id,
            Sprint.project_id == project.id,
        )
    )
    if sprint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sprint não encontrada.",
        )

    tz = get_zone_info(project.timezone)
    current_start = (
        sprint.start_date.astimezone(tz).date().isoformat() if sprint.start_date else None
    )
    current_end = (
        sprint.end_date.astimezone(tz).date().isoformat() if sprint.end_date else None
    )

    new_start = payload.start_date or current_start
    new_end = payload.end_date or current_end

    if payload.name is not None:
        clean_name = payload.name.strip()
        if not clean_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O nome da sprint não pode ser vazio.",
            )
        sprint.name = clean_name

    if (payload.start_date is not None or payload.end_date is not None) and new_start and new_end:
        try:
            w = parse_window(new_start, new_end, timezone=project.timezone)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(err),
            ) from err

        sprint.start_date = w.start_utc
        sprint.end_date = w.end_utc - dt.timedelta(seconds=1)

    db.commit()
    db.refresh(sprint)

    return _format_sprint_dict(sprint, project.timezone)


@router.delete("/{project_id}/sprints/{sprint_id}")
def delete_project_sprint(
    project_id: str,
    sprint_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db_session),
) -> dict[str, bool]:
    """Exclui uma sprint do projeto."""
    project = repository.get_project_for_user(db, project_id, user_id)
    sprint = db.scalar(
        select(Sprint).where(
            Sprint.id == sprint_id,
            Sprint.project_id == project.id,
        )
    )
    if sprint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sprint não encontrada.",
        )

    db.delete(sprint)
    db.commit()
    return {"ok": True}
