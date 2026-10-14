from __future__ import annotations

from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_router import get_current_user_id
from .db import repository
from .db.models import (
    ColumnMapping,
    Project,
    ProjectSource,
    ProviderConnection,
    SyncRun,
    utc_now,
)
from .db.session import get_db_session
from .github_collector import fetch_user_repos
from .trello_collector import fetch_user_boards
from .trello_tokens import (
    TrelloReconnectRequired,
    TrelloTokenRefreshError,
    refresh_if_needed,
)
from .project_sync import schedule_project_sync, sync_run_payload

router = APIRouter(prefix="/projects", tags=["projects"])
SYNC_INTERVALS = {15, 30, 60, 360, 1440}
ALLOWED_COLUMN_CATEGORIES = {"todo", "doing", "review", "done", "backlog"}


class ColumnMappingUpdateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_uid: str
    category: str

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        if value not in ALLOWED_COLUMN_CATEGORIES:
            raise ValueError(
                f"Categoria inválida. Deve ser uma de: {', '.join(sorted(ALLOWED_COLUMN_CATEGORIES))}"
            )
        return value


class UpdateColumnsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[ColumnMappingUpdateItem]


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    timezone: str = "America/Sao_Paulo"
    history_days: int = Field(default=90, ge=7, le=365)
    auto_sync: bool = False
    sync_interval_min: int = 60

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("O nome do projeto não pode ficar vazio")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Fuso horário inválido") from None
        return value

    @field_validator("sync_interval_min")
    @classmethod
    def validate_sync_interval(cls, value: int) -> int:
        if value not in SYNC_INTERVALS:
            raise ValueError("Intervalo de sincronização inválido")
        return value


class ProjectSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_sync: bool
    sync_interval_min: int = 60
    timezone: str | None = None
    history_days: int | None = Field(default=None, ge=7, le=365)
    settings_json: dict[str, Any] | None = None

    @field_validator("sync_interval_min")
    @classmethod
    def validate_sync_interval(cls, value: int) -> int:
        if value not in SYNC_INTERVALS:
            raise ValueError("Intervalo de sincronização inválido")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Fuso horário inválido") from None
        return value


class ProjectSourcesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    github_repos: list[str] = Field(default_factory=list, max_length=20)
    trello_boards: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_source_count_and_duplicates(self) -> ProjectSourcesIn:
        sources = self.github_repos + self.trello_boards
        if len(sources) > 20:
            raise ValueError("O projeto pode ter no máximo 20 fontes")
        if len(set(self.github_repos)) != len(self.github_repos):
            raise ValueError("A lista de repositórios contém duplicatas")
        if len(set(self.trello_boards)) != len(self.trello_boards):
            raise ValueError("A lista de boards contém duplicatas")
        if any(not source.strip() for source in sources):
            raise ValueError("IDs de fontes não podem ficar vazios")
        return self


def _project_payload(project: Project, sources: list[ProjectSource] | None = None) -> dict:
    payload = {
        "id": project.id,
        "name": project.name,
        "timezone": project.timezone,
        "history_days": project.history_days,
        "auto_sync": project.auto_sync,
        "sync_interval_min": project.sync_interval_min,
        "next_sync_at": (
            project.next_sync_at.isoformat() if project.next_sync_at else None
        ),
        "settings_json": project.settings_json or {},
        "created_at": project.created_at.isoformat(),
    }
    if sources is not None:
        payload["sources"] = [
            {
                "provider": source.provider,
                "external_id": source.external_id,
                "display_name": source.display_name,
                "enabled": source.enabled,
            }
            for source in sources
        ]
    return payload


@router.get("")
def list_projects(
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    projects = db_session.scalars(
        select(Project)
        .where(Project.user_id == user_id)
        .order_by(Project.created_at, Project.id)
    )
    return [_project_payload(project) for project in projects]


@router.post("", status_code=201)
def create_project(
    body: ProjectIn,
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    project = Project(user_id=user_id, **body.model_dump())
    if project.auto_sync:
        project.next_sync_at = utc_now() + timedelta(minutes=project.sync_interval_min)
    db_session.add(project)
    db_session.commit()
    return _project_payload(project)


@router.get("/{project_id}")
def get_project(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    project = repository.get_project_for_user(db_session, project_id, user_id)
    sources = db_session.scalars(
        select(ProjectSource)
        .where(ProjectSource.project_id == project.id)
        .order_by(ProjectSource.provider, ProjectSource.external_id)
    ).all()
    return _project_payload(project, sources)


@router.put("/{project_id}")
def update_project(
    project_id: str,
    body: ProjectIn,
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    project = repository.get_project_for_user(db_session, project_id, user_id)
    prev_auto_sync = project.auto_sync
    for field, value in body.model_dump().items():
        setattr(project, field, value)
    if project.auto_sync:
        if not prev_auto_sync or project.next_sync_at is None:
            project.next_sync_at = utc_now() + timedelta(minutes=project.sync_interval_min)
    else:
        project.next_sync_at = None
    db_session.commit()
    return _project_payload(project)


@router.get("/{project_id}/settings")
def get_project_settings(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    project = repository.get_project_for_user(db_session, project_id, user_id)
    return {
        "auto_sync": project.auto_sync,
        "sync_interval_min": project.sync_interval_min,
        "next_sync_at": (
            project.next_sync_at.isoformat() if project.next_sync_at else None
        ),
        "timezone": project.timezone,
        "history_days": project.history_days,
        "settings_json": project.settings_json or {},
    }


@router.put("/{project_id}/settings")
def update_project_settings(
    project_id: str,
    body: ProjectSettingsIn,
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    project = repository.get_project_for_user(db_session, project_id, user_id)
    prev_auto_sync = project.auto_sync
    prev_interval = project.sync_interval_min

    project.auto_sync = body.auto_sync
    project.sync_interval_min = body.sync_interval_min
    if body.timezone is not None:
        project.timezone = body.timezone
    if body.history_days is not None:
        project.history_days = body.history_days
    if body.settings_json is not None:
        project.settings_json = body.settings_json

    if project.auto_sync:
        if (
            not prev_auto_sync
            or project.next_sync_at is None
            or project.next_sync_at <= utc_now()
            or prev_interval != project.sync_interval_min
        ):
            project.next_sync_at = utc_now() + timedelta(minutes=project.sync_interval_min)
    else:
        project.next_sync_at = None

    db_session.commit()
    sources = db_session.scalars(
        select(ProjectSource)
        .where(ProjectSource.project_id == project.id)
        .order_by(ProjectSource.provider, ProjectSource.external_id)
    ).all()
    return _project_payload(project, sources)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    project = repository.get_project_for_user(db_session, project_id, user_id)
    db_session.delete(project)
    db_session.commit()


@router.post("/{project_id}/sync", status_code=202)
def start_project_sync(
    project_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    run = schedule_project_sync(
        db_session,
        user_id,
        project_id,
        request.app.state.neo4j_driver,
        request.app.state.sync_executor,
    )
    return {"run_id": run.id, "status": run.status, "progress": run.progress_json}


@router.get("/{project_id}/sync-runs")
def list_project_sync_runs(
    project_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    project = repository.get_project_for_user(db_session, project_id, user_id)
    runs = db_session.scalars(
        select(SyncRun)
        .where(SyncRun.project_id == project.id)
        .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
        .limit(limit)
    ).all()
    return [sync_run_payload(run) for run in runs]


@router.get("/{project_id}/sync-runs/{run_id}")
def get_project_sync_run(
    project_id: str,
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    project = repository.get_project_for_user(db_session, project_id, user_id)
    run = db_session.scalar(
        select(SyncRun).where(
            SyncRun.id == run_id,
            SyncRun.project_id == project.id,
        )
    )
    if run is None:
        raise HTTPException(404, "Execução de sincronização não encontrada")
    return sync_run_payload(run)


@router.get("/{project_id}/columns")
def list_project_columns(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    project = repository.get_project_for_user(db_session, project_id, user_id)
    columns = db_session.scalars(
        select(ColumnMapping)
        .where(ColumnMapping.project_id == project.id)
        .order_by(ColumnMapping.name, ColumnMapping.column_uid)
    ).all()
    warnings: list[str] = []
    if any(col.source == "auto" for col in columns):
        warnings.append("columns_unconfirmed")

    return {
        "columns": [
            {
                "column_uid": col.column_uid,
                "name": col.name,
                "category": col.category,
                "source": col.source,
            }
            for col in columns
        ],
        "warnings": warnings,
    }


@router.put("/{project_id}/columns")
def update_project_columns(
    project_id: str,
    body: UpdateColumnsIn | list[ColumnMappingUpdateItem],
    request: Request,
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    project = repository.get_project_for_user(db_session, project_id, user_id)
    column_items = body if isinstance(body, list) else body.columns

    existing_mappings = {
        col.column_uid: col
        for col in db_session.scalars(
            select(ColumnMapping).where(ColumnMapping.project_id == project.id)
        ).all()
    }

    neo4j_updates: list[dict[str, str]] = []
    for item in column_items:
        mapping = existing_mappings.get(item.column_uid)
        if mapping:
            mapping.category = item.category
            mapping.source = "user"
            neo4j_updates.append({"column_uid": item.column_uid, "category": item.category})
        else:
            raise HTTPException(404, f"Coluna com ID '{item.column_uid}' não encontrada.")

    db_session.commit()

    # Atualiza nós :Column no Neo4j caso disponíveis
    driver = getattr(request.app.state, "neo4j_driver", None)
    if driver and neo4j_updates:
        try:
            with driver.session() as n4j_session:
                n4j_session.run(
                    """
                    UNWIND $updates AS upd
                    MATCH (c:Column {project_id: $project_id, uid: upd.column_uid})
                    SET c.category = upd.category
                    """,
                    project_id=project.id,
                    updates=neo4j_updates,
                )
        except Exception:
            pass

    columns = db_session.scalars(
        select(ColumnMapping)
        .where(ColumnMapping.project_id == project.id)
        .order_by(ColumnMapping.name, ColumnMapping.column_uid)
    ).all()
    warnings: list[str] = []
    if any(col.source == "auto" for col in columns):
        warnings.append("columns_unconfirmed")

    return {
        "columns": [
            {
                "column_uid": col.column_uid,
                "name": col.name,
                "category": col.category,
                "source": col.source,
            }
            for col in columns
        ],
        "warnings": warnings,
    }


def _available_sources(
    body: ProjectSourcesIn,
    user_id: str,
    session: Session,
) -> list[ProjectSource]:
    available: dict[str, dict[str, str]] = {}
    if body.github_repos:
        github_connection = session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.user_id == user_id,
                ProviderConnection.provider == "github",
            )
        )
        if github_connection is None:
            raise HTTPException(400, "GitHub não conectado")
        github_token = repository.get_provider_token(session, user_id, "github")
        if not github_token:
            raise HTTPException(400, "GitHub não conectado")
        repos = fetch_user_repos(github_token)
        available["github"] = {
            repo["full_name"]: repo["full_name"] for repo in repos
        }

    if body.trello_boards:
        try:
            trello_token = refresh_if_needed(session, user_id)
        except TrelloReconnectRequired:
            raise HTTPException(
                401, "Trello precisa ser conectado novamente"
            ) from None
        except TrelloTokenRefreshError:
            raise HTTPException(
                502, "Não foi possível renovar a conexão com o Trello"
            ) from None
        if not trello_token:
            raise HTTPException(400, "Trello não conectado")
        boards = fetch_user_boards(trello_token)
        available["trello"] = {
            board["id"]: board["name"] for board in boards
        }

    sources: list[ProjectSource] = []
    for provider, source_ids in (
        ("github", body.github_repos),
        ("trello", body.trello_boards),
    ):
        for source_id in source_ids:
            display_name = available.get(provider, {}).get(source_id)
            if display_name is None:
                raise HTTPException(
                    422, f"Fonte selecionada não está disponível em {provider}"
                )
            sources.append(
                ProjectSource(
                    provider=provider,
                    external_id=source_id,
                    display_name=display_name,
                    enabled=True,
                )
            )
    return sources


@router.put("/{project_id}/sources")
def replace_project_sources(
    project_id: str,
    body: ProjectSourcesIn,
    user_id: str = Depends(get_current_user_id),
    db_session: Session = Depends(get_db_session),
):
    project = repository.get_project_for_user(db_session, project_id, user_id)
    sources = _available_sources(body, user_id, db_session)
    existing_sources = db_session.scalars(
        select(ProjectSource).where(ProjectSource.project_id == project.id)
    ).all()
    for source in existing_sources:
        db_session.delete(source)
    db_session.add_all(
        [
            ProjectSource(
                project_id=project.id,
                provider=source.provider,
                external_id=source.external_id,
                display_name=source.display_name,
                enabled=source.enabled,
            )
            for source in sources
        ]
    )
    db_session.commit()
    saved_sources = db_session.scalars(
        select(ProjectSource)
        .where(ProjectSource.project_id == project.id)
        .order_by(ProjectSource.provider, ProjectSource.external_id)
    ).all()
    return _project_payload(project, saved_sources)
