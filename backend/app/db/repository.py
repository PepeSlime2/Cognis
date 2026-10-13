from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..security import decrypt_token, encrypt_token
from .models import PersonOverride, Project, ProviderConnection


def get_project_for_user(session: Session, project_id: str, user_id: str) -> Project:
    project = session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id,
        )
    )
    if project is None:
        raise HTTPException(404, "Projeto não encontrado")
    return project

def save_provider_connection(
    session: Session,
    user_id: str,
    provider: str,
    external_login: str,
    access_token: str,
    display_name: str | None = None,
    avatar_url: str | None = None,
    scope: str | None = None,
    refresh_token: str | None = None,
    expires_at: datetime | None = None,
) -> None:
    encrypted_token = encrypt_token(access_token)
    encrypted_refresh_token = (
        encrypt_token(refresh_token) if refresh_token is not None else None
    )
    connection = session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.user_id == user_id,
            ProviderConnection.provider == provider,
        )
    )
    if connection is None:
        connection = ProviderConnection(
            user_id=user_id,
            provider=provider,
            external_login=external_login,
            access_token_enc=encrypted_token,
        )
        session.add(connection)
    connection.external_login = external_login
    connection.display_name = display_name
    connection.avatar_url = avatar_url
    connection.access_token_enc = encrypted_token
    connection.scope = scope
    if refresh_token is not None:
        connection.refresh_token_enc = encrypted_refresh_token
    if expires_at is not None:
        connection.expires_at = expires_at
    connection.status = "ok"
    connection.connected_at = datetime.now(timezone.utc)


def get_connections(session: Session, user_id: str) -> dict:
    connections = session.scalars(
        select(ProviderConnection).where(ProviderConnection.user_id == user_id)
    )
    return {
        connection.provider: {
            "username": connection.external_login,
            "connected_at": connection.connected_at.isoformat(),
            "status": connection.status,
        }
        for connection in connections
    }


def get_provider_token(session: Session, user_id: str, provider: str) -> str | None:
    connection = session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.user_id == user_id,
            ProviderConnection.provider == provider,
        )
    )
    if connection is None:
        return None
    return decrypt_token(connection.access_token_enc)


def disconnect_provider(session: Session, user_id: str, provider: str) -> None:
    connection = session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.user_id == user_id,
            ProviderConnection.provider == provider,
        )
    )
    if connection is not None:
        session.delete(connection)


def get_person_overrides(session: Session, project_id: str) -> list[PersonOverride]:
    return list(
        session.scalars(
            select(PersonOverride).where(PersonOverride.project_id == project_id)
        ).all()
    )


def get_person_override(
    session: Session, project_id: str, person_uid: str
) -> PersonOverride | None:
    return session.get(PersonOverride, (project_id, person_uid))


def set_person_override(
    session: Session,
    project_id: str,
    person_uid: str,
    display_name: str | None = None,
    excluded: bool | None = None,
    role: str | None = None,
) -> PersonOverride:
    override = session.get(PersonOverride, (project_id, person_uid))
    if override is None:
        override = PersonOverride(
            project_id=project_id,
            person_uid=person_uid,
            display_name=display_name.strip() if display_name else None,
            excluded=excluded if excluded is not None else False,
            role=role.strip() if role else None,
        )
        session.add(override)
    else:
        if display_name is not None:
            override.display_name = display_name.strip() if display_name else None
        if excluded is not None:
            override.excluded = excluded
        if role is not None:
            override.role = role.strip() if role else None
    session.commit()
    session.refresh(override)
    return override

