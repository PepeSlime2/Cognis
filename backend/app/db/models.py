from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class UTCDateTime(TypeDecorator[dt.datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: dt.datetime | None, dialect: Any
    ) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Datas devem incluir fuso horário")
        utc_value = value.astimezone(dt.timezone.utc)
        if dialect.name == "sqlite":
            return utc_value.replace(tzinfo=None)
        return utc_value

    def process_result_value(
        self, value: dt.datetime | None, dialect: Any
    ) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            if dialect.name != "sqlite":
                raise ValueError("O banco retornou uma data sem fuso horário")
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True, nullable=True)
    name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ProviderConnection(Base):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_provider_connection_user_provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    external_login: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    access_token_enc: Mapped[str] = mapped_column(String)
    refresh_token_enc: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    scope: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ok")
    connected_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    history_days: Mapped[int] = mapped_column(Integer, default=90)
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_interval_min: Mapped[int] = mapped_column(Integer, default=60)
    next_sync_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ProjectSource(Base):
    __tablename__ = "project_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(512))
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    cursor_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ColumnMapping(Base):
    __tablename__ = "column_mappings"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    column_uid: Mapped[str] = mapped_column(String(512), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16), default="auto")


class Sprint(Base):
    __tablename__ = "sprints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    start_date: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    end_date: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class PersonOverride(Base):
    __tablename__ = "person_overrides"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    person_uid: Mapped[str] = mapped_column(String(512), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str | None] = mapped_column(String(80), nullable=True)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utc_now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    progress_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    stats_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    errors_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "window_from",
            "window_to",
            "config_hash",
            "data_version",
            name="uq_metric_snapshot_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    window_from: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    window_to: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    config_hash: Mapped[str] = mapped_column(String(128))
    data_version: Mapped[str] = mapped_column(String(36))
    bundle_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(32))
    window_from: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    window_to: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    person_uid: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    facts_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    validation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    window_from: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    window_to: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    person_uid: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    model_json_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    files_json: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    analysis_id: Mapped[str | None] = mapped_column(ForeignKey("analyses.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utc_now)
