from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_router import get_current_user_id
from .database import get_neo4j_driver
from .db import repository
from .db.models import Analysis
from .db.session import SessionLocal, get_db_session
from .llm.pipeline import run_analysis_pipeline
from .metrics.windows import parse_window

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analyses"])


class AnalysisCreateRequest(BaseModel):
    scope: str = Field("team", description="Escopo: team, collaboration, risks, sprint, person")
    window: str | None = Field(None, description="Janela relativa: 7d, 14d, 30d, 90d")
    from_date: str | None = Field(None, alias="from", description="Data início YYYY-MM-DD")
    to_date: str | None = Field(None, alias="to", description="Data término YYYY-MM-DD")
    sprint_id: str | None = Field(None, description="ID da sprint para delimitar a janela")
    person_uid: str | None = Field(None, description="UID da pessoa para escopo person")
    anonymize: bool = Field(False, description="Anonimizar dados enviados ao LLM")
    force_template: bool = Field(False, description="Forçar geração via template sem consultar LLM")
    wait: bool = Field(False, description="Aguardar conclusão síncrona da análise")

    model_config = ConfigDict(populate_by_name=True)


def _format_analysis_dict(analysis: Analysis) -> dict[str, Any]:
    return {
        "id": analysis.id,
        "analysis_id": analysis.id,
        "project_id": analysis.project_id,
        "scope": analysis.scope,
        "status": analysis.status,
        "model": analysis.model,
        "source": analysis.source,
        "window": {
            "from": analysis.window_from.isoformat() if analysis.window_from else None,
            "to": analysis.window_to.isoformat() if analysis.window_to else None,
        },
        "person_uid": analysis.person_uid,
        "facts": analysis.facts_json,
        "result": analysis.result_json,
        "validation": analysis.validation_json,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


def _resolve_analysis_window(
    project: Project,
    db: Session,
    window_param: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    sprint_id: str | None = None,
) -> TimeWindow:
    from .db.models import Sprint
    from .metrics.windows import default_window, parse_window, window_from_sprint

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

    if window_param:
        try:
            days = int(window_param.lower().rstrip("d"))
            return default_window(timezone=project.timezone, days=days)
        except Exception:
            pass

    return default_window(timezone=project.timezone, days=30)


def _run_analysis_job_in_background(
    analysis_id: str,
    project_id: str,
    user_id: str,
    window_kwargs: dict[str, Any],
    scope: str,
    person_uid: str | None,
    anonymize: bool,
    force_template: bool,
) -> None:
    """Executa a análise em thread de background."""
    from .database import create_neo4j_driver

    neo4j_driver = create_neo4j_driver()
    try:
        with SessionLocal() as db:
            project = repository.get_project_for_user(db, project_id, user_id)
            window = _resolve_analysis_window(
                project=project,
                db=db,
                window_param=window_kwargs.get("window"),
                from_date=window_kwargs.get("from_date"),
                to_date=window_kwargs.get("to_date"),
                sprint_id=window_kwargs.get("sprint_id"),
            )
            run_analysis_pipeline(
                db=db,
                neo4j_driver=neo4j_driver,
                project=project,
                window=window,
                scope=scope,
                person_uid=person_uid,
                anonymize=anonymize,
                force_template=force_template,
                existing_analysis_id=analysis_id,
            )
    except Exception as exc:
        logger.exception("Erro ao executar análise em background (analysis_id=%s): %s", analysis_id, exc)
        with SessionLocal() as db:
            an = db.get(Analysis, analysis_id)
            if an:
                an.status = "failed"
                an.validation_json = {"error": str(exc)}
                db.commit()
    finally:
        neo4j_driver.close()


@router.post("/projects/{project_id}/analyses", status_code=status.HTTP_202_ACCEPTED)
def create_project_analysis(
    project_id: str,
    body: AnalysisCreateRequest,
    response: Response,
    request: Request,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db_session),
    neo4j_driver: Any = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    """
    Inicia uma análise por IA local ou template determinístico (SPEC §11).
    Retorna 202 com {id, analysis_id, status} ou resultado completo se wait=True.
    """
    project = repository.get_project_for_user(db, project_id, user_id)
    window = _resolve_analysis_window(
        project=project,
        db=db,
        window_param=body.window,
        from_date=body.from_date,
        to_date=body.to_date,
        sprint_id=body.sprint_id,
    )

    # Criação inicial da análise com status pending
    analysis = Analysis(
        project_id=project.id,
        scope=body.scope,
        window_from=window.start_utc,
        window_to=window.end_utc,
        person_uid=body.person_uid,
        status="pending",
        facts_json={},
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    # Modo síncrono ou quando explicitamente solicitado wait=True
    if body.wait:
        completed_analysis = run_analysis_pipeline(
            db=db,
            neo4j_driver=neo4j_driver,
            project=project,
            window=window,
            scope=body.scope,
            person_uid=body.person_uid,
            anonymize=body.anonymize,
            force_template=body.force_template,
            existing_analysis_id=analysis.id,
        )
        response.status_code = status.HTTP_200_OK
        return _format_analysis_dict(completed_analysis)

    # Submeter ao executor assíncrono do app caso exista
    executor = getattr(request.app.state, "sync_executor", None)
    window_kwargs = {
        "window": body.window,
        "from_date": body.from_date,
        "to_date": body.to_date,
        "sprint_id": body.sprint_id,
    }

    if executor:
        executor.submit(
            _run_analysis_job_in_background,
            analysis.id,
            project.id,
            user_id,
            window_kwargs,
            body.scope,
            body.person_uid,
            body.anonymize,
            body.force_template,
        )
    else:
        # Fallback síncrono imediato se não houver executor
        completed_analysis = run_analysis_pipeline(
            db=db,
            neo4j_driver=neo4j_driver,
            project=project,
            window=window,
            scope=body.scope,
            person_uid=body.person_uid,
            anonymize=body.anonymize,
            force_template=body.force_template,
            existing_analysis_id=analysis.id,
        )
        return _format_analysis_dict(completed_analysis)

    return {
        "id": analysis.id,
        "analysis_id": analysis.id,
        "project_id": analysis.project_id,
        "status": "pending",
        "scope": analysis.scope,
    }


@router.get("/analyses/{analysis_id}")
def get_analysis_by_id(
    analysis_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Retorna os detalhes e resultado de uma análise existente (SPEC §11)."""
    analysis = db.get(Analysis, analysis_id)
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Análise não encontrada",
        )

    # Validar isolamento de tenant
    _ = repository.get_project_for_user(db, analysis.project_id, user_id)
    return _format_analysis_dict(analysis)


@router.get("/projects/{project_id}/analyses")
def list_project_analyses(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Lista o histórico de análises do projeto (SPEC §11)."""
    project = repository.get_project_for_user(db, project_id, user_id)
    stmt = (
        select(Analysis)
        .where(Analysis.project_id == project.id)
        .order_by(Analysis.created_at.desc())
    )
    analyses = list(db.scalars(stmt))
    return [_format_analysis_dict(a) for a in analyses]
