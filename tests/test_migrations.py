from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.backend.db import upgrade_database

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _create_v01_schema(database_url: str) -> None:
    engine = create_engine(database_url)
    statements = (
        """CREATE TABLE conversations (
        id VARCHAR(36) PRIMARY KEY, customer_id VARCHAR(100) NOT NULL,
        title VARCHAR(200), status VARCHAR(30) NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)""",
        """CREATE TABLE products (
        id INTEGER PRIMARY KEY AUTOINCREMENT, external_id VARCHAR(100) NOT NULL UNIQUE,
        sku VARCHAR(100), name VARCHAR(300) NOT NULL, brand VARCHAR(200), description TEXT,
        price NUMERIC(12, 2), extra JSON NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)""",
        """CREATE TABLE orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, external_id VARCHAR(100) NOT NULL UNIQUE,
        customer_id VARCHAR(100) NOT NULL, product_external_id VARCHAR(100),
        conversation_id VARCHAR(36), status VARCHAR(50) NOT NULL, quantity INTEGER NOT NULL,
        total_amount NUMERIC(12, 2), extra JSON NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        FOREIGN KEY(product_external_id) REFERENCES products(external_id),
        FOREIGN KEY(conversation_id) REFERENCES conversations(id))""",
        """CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id VARCHAR(36) NOT NULL,
        sender_role VARCHAR(20) NOT NULL, message_type VARCHAR(20) NOT NULL, content TEXT,
        media_url VARCHAR(500), original_filename VARCHAR(300), mime_type VARCHAR(150),
        size_bytes INTEGER, created_at DATETIME NOT NULL,
        FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE)""",
        """CREATE TABLE realtime_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id VARCHAR(36) NOT NULL,
        message_id INTEGER NOT NULL UNIQUE, created_at DATETIME NOT NULL,
        FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE)""",
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(
            text(
                "INSERT INTO conversations VALUES "
                "('legacy-conversation', 'legacy-buyer', '旧会话', 'open', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO orders "
                "(external_id, customer_id, conversation_id, status, quantity, extra, "
                "created_at, updated_at) VALUES "
                "('ORDER-LEGACY', 'legacy-buyer', 'legacy-conversation', 'paid', 1, '{}', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
    engine.dispose()


def test_upgrade_preserves_v01_rows_and_adds_v02_schema(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    _create_v01_schema(database_url)
    engine = create_engine(database_url)

    upgrade_database(engine)

    table_names = set(inspect(engine).get_table_names())
    assert {"work_orders", "replacement_details", "import_batches"} <= table_names
    assert {"source_external_id", "buyer_nickname"} <= {
        column["name"] for column in inspect(engine).get_columns("conversations")
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM conversations")) == 1
        assert connection.scalar(text("SELECT external_id FROM orders")) == "ORDER-LEGACY"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0002_emotion_analysis_cache"
        )
        assert connection.scalar(text("SELECT COUNT(*) FROM conversation_emotion_analyses")) == 0
    engine.dispose()


def test_fresh_database_is_created_and_stamped(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")

    upgrade_database(engine)

    table_names = set(inspect(engine).get_table_names())
    assert {
        "conversations",
        "orders",
        "messages",
        "work_orders",
        "emotion_analysis_runs",
        "conversation_emotion_analyses",
        "alembic_version",
    } <= table_names
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0002_emotion_analysis_cache"
        )
    engine.dispose()


def test_fresh_database_migration_registers_models_in_clean_process(tmp_path) -> None:
    database_path = tmp_path / "isolated-fresh.db"
    probe = """
import sys

from sqlalchemy import create_engine, inspect, text

from app.backend.db import upgrade_database

engine = create_engine(f"sqlite:///{sys.argv[1]}")
upgrade_database(engine)
tables = set(inspect(engine).get_table_names())
required = {
    "conversations", "orders", "messages", "work_orders",
    "emotion_analysis_runs", "conversation_emotion_analyses", "alembic_version"
}
if not required <= tables:
    raise SystemExit(f"missing tables: {sorted(required - tables)}")
with engine.connect() as connection:
    revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
if revision != "0002_emotion_analysis_cache":
    raise SystemExit(f"unexpected revision: {revision}")
engine.dispose()
"""

    result = subprocess.run(
        [sys.executable, "-c", probe, str(database_path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
