from typing import Literal

from fastapi import APIRouter, Depends, Query
from neo4j import Driver
from sqlalchemy.orm import Session

from .auth_router import get_current_user_id
from .database import get_neo4j_driver
from .db import repository
from .db.session import get_db_session
from .graph_service import get_project_graph

router = APIRouter(prefix="/projects", tags=["graph"])


@router.get("/{project_id}/graph")
def read_project_graph(
    project_id: str,
    layer: Literal["all", "people", "tasks", "artifacts"] = "all",
    max_nodes: int = Query(default=400, ge=1, le=400),
    min_weight: float = Query(default=1, ge=0),
    include_bots: bool = False,
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
    driver: Driver = Depends(get_neo4j_driver),
):
    repository.get_project_for_user(db_session, project_id, user_id)
    return get_project_graph(
        driver,
        project_id,
        layer,
        max_nodes,
        min_weight,
        include_bots,
    )
