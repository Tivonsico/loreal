from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import Request
from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def create_database(database_url: str) -> tuple[Engine, sessionmaker[Session]]:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def upgrade_database(engine: Engine) -> None:
    """Create a fresh schema or upgrade an existing v0.1 database to v0.2."""
    from app.backend import models  # noqa: F401  # Register all tables with Base.metadata.

    backend_dir = Path(__file__).resolve().parent
    config = Config(backend_dir / "alembic.ini")
    config.set_main_option("script_location", str(backend_dir / "migrations"))

    existing_tables = set(inspect(engine).get_table_names())
    core_tables = {"conversations", "messages", "orders"}
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        if not (existing_tables & core_tables):
            Base.metadata.create_all(connection)
            command.stamp(config, "head")
        else:
            command.upgrade(config, "head")


def get_db(request: Request) -> Generator[Session, None, None]:
    with request.app.state.session_factory() as session:
        yield session
