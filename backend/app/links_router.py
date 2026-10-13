from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from neo4j import Driver
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .auth_router import get_current_user_id
from .database import get_neo4j_driver
from .db import repository
from .db.session import get_db_session
from .linker import (
    create_manual_link,
    delete_manual_link,
    list_project_links,
)

router = APIRouter(prefix="/projects", tags=["links"])


class LinkCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_uid: str | None = None
    task_uid: str | None = None
    target_uid: str


class LinkDeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_uid: str | None = None
    task_uid: str | None = None
    target_uid: str


@router.get("/{project_id}/links")
def get_project_links(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_db_session),
    driver: Driver = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    repository.get_project_for_user(session, project_id, user_id)
    return list_project_links(driver, project_id)


@router.post("/{project_id}/links", status_code=status.HTTP_201_CREATED)
def post_project_link(
    project_id: str,
    payload: LinkCreateIn,
    user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_db_session),
    driver: Driver = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    repository.get_project_for_user(session, project_id, user_id)
    src = payload.source_uid or payload.task_uid
    if not src:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "É necessário informar source_uid ou task_uid.",
        )
    try:
        return create_manual_link(driver, project_id, src, payload.target_uid)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@router.delete("/{project_id}/links")
def delete_project_link(
    project_id: str,
    payload: LinkDeleteIn | None = None,
    source_uid: str | None = Query(default=None),
    task_uid: str | None = Query(default=None),
    target_uid: str | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_db_session),
    driver: Driver = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    repository.get_project_for_user(session, project_id, user_id)
    src = (
        (payload.source_uid or payload.task_uid)
        if payload and (payload.source_uid or payload.task_uid)
        else (source_uid or task_uid)
    )
    tgt = (payload.target_uid if payload and payload.target_uid else target_uid)
    if not src or not tgt:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "É necessário informar source_uid/task_uid e target_uid.",
        )
    deleted = delete_manual_link(driver, project_id, src, tgt)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vínculo não encontrado.")
    return {"deleted": True, "source_uid": src, "target_uid": tgt}
