from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .auth_router import get_current_user_id
from .database import get_neo4j_driver
from .db import repository
from .db.session import get_db_session
from .identity_service import (
    find_merge_suggestions,
    list_people_for_project,
    merge_people,
    split_person,
)

router = APIRouter(prefix="/projects", tags=["people"])


class PersonPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=255)
    excluded: bool | None = None


class PeopleMergeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep_person_id: str
    merge_person_ids: list[str] = Field(min_length=1)


class PeopleSplitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_uid: str


@router.get("/{project_id}/people")
def get_project_people(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_db_session),
    driver: Driver = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    repository.get_project_for_user(session, project_id, user_id)
    people = list_people_for_project(
        driver, project_id, user_id=user_id, db_session=session
    )
    suggestions = find_merge_suggestions(people)
    return {
        "project_id": project_id,
        "people": people,
        "suggestions": suggestions,
    }


@router.post("/{project_id}/people/merge")
def post_merge_people(
    project_id: str,
    payload: PeopleMergeIn,
    user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_db_session),
    driver: Driver = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    repository.get_project_for_user(session, project_id, user_id)
    try:
        person = merge_people(
            driver,
            project_id=project_id,
            keep_person_uid=payload.keep_person_id,
            merge_person_uids=payload.merge_person_ids,
        )
        return {
            "project_id": project_id,
            "person": person,
        }
    except ValueError as err:
        raise HTTPException(400, str(err)) from None
    except RuntimeError as err:
        raise HTTPException(500, str(err)) from None


@router.post("/{project_id}/people/{person_uid}/split")
def post_split_person(
    project_id: str,
    person_uid: str,
    payload: PeopleSplitIn,
    user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_db_session),
    driver: Driver = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    repository.get_project_for_user(session, project_id, user_id)
    try:
        result = split_person(
            driver,
            project_id=project_id,
            person_uid=person_uid,
            account_uid=payload.account_uid,
        )
        return {
            "project_id": project_id,
            **result,
        }
    except ValueError as err:
        raise HTTPException(400, str(err)) from None


@router.patch("/{project_id}/people/{person_uid}")
def patch_project_person(
    project_id: str,
    person_uid: str,
    payload: PersonPatchIn,
    user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_db_session),
    driver: Driver = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    repository.get_project_for_user(session, project_id, user_id)

    if payload.display_name is None and payload.excluded is None:
        raise HTTPException(
            422, "Pelo menos um campo ('display_name' ou 'excluded') deve ser informado."
        )

    # 1. Atualizar ou criar PersonOverride no SQLite
    override = repository.set_person_override(
        session,
        project_id=project_id,
        person_uid=person_uid,
        display_name=payload.display_name,
        excluded=payload.excluded,
    )

    # 2. Refletir a atualização no nó Person no Neo4j
    update_cypher = """
    MATCH (p:Person {uid: $person_uid, project_id: $project_id})
    SET p.excluded = $excluded
    FOREACH (_ IN CASE WHEN $display_name IS NOT NULL THEN [1] ELSE [] END |
        SET p.display_name = $display_name
    )
    RETURN p.uid AS person_uid,
           p.display_name AS display_name,
           coalesce(p.excluded, false) AS excluded
    """

    with driver.session() as neo4j_session:
        result = neo4j_session.run(
            update_cypher,
            project_id=project_id,
            person_uid=person_uid,
            excluded=override.excluded,
            display_name=override.display_name,
        )
        record = result.single()
        if not record:
            raise HTTPException(404, "Pessoa não encontrada no grafo.")

        return {
            "project_id": project_id,
            "person_uid": record["person_uid"],
            "display_name": record["display_name"],
            "excluded": record["excluded"],
        }
