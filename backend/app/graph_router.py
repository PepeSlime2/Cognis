from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from neo4j import Driver
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_router import get_current_user_id
from .database import get_neo4j_driver
from .db import repository
from .db.models import Sprint
from .db.session import get_db_session
from .graph_service import get_project_graph
from .metrics.windows import default_window, parse_window, window_from_sprint

router = APIRouter(prefix="/projects", tags=["graph"])


@router.get("/{project_id}/graph")
def read_project_graph(
    project_id: str,
    layer: Literal["all", "people", "tasks", "artifacts"] = "all",
    max_nodes: int = Query(default=400, ge=1, le=400),
    min_weight: float = Query(default=1, ge=0),
    include_bots: bool = False,
    sprint_id: str | None = Query(default=None),
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    window: str | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
    driver: Driver = Depends(get_neo4j_driver),
):
    project = repository.get_project_for_user(db_session, project_id, user_id)

    # Resolução de janela/sprint
    time_window = None
    if sprint_id:
        sprint = db_session.execute(
            select(Sprint).where(Sprint.id == sprint_id, Sprint.project_id == project.id)
        ).scalar_one_or_none()
        if sprint is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sprint não encontrada",
            )
        time_window = window_from_sprint(sprint, timezone=project.timezone)
    elif from_date and to_date:
        try:
            time_window = parse_window(from_date, to_date, timezone=project.timezone)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(err),
            ) from err
    elif window and window.endswith("d"):
        try:
            days = int(window.replace("d", ""))
            time_window = default_window(timezone=project.timezone, days=days)
        except ValueError:
            pass

    graph = get_project_graph(
        driver,
        project_id,
        layer,
        max_nodes,
        min_weight,
        include_bots,
    )
    if time_window:
        graph["window"] = time_window.to_dict()
    return graph
