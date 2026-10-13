from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ..config import app_config
from .models import Base

_is_sqlite = app_config.database_url.startswith("sqlite")
engine = create_engine(
    app_config.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_database() -> None:
    Base.metadata.create_all(bind=engine)


def get_db_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
