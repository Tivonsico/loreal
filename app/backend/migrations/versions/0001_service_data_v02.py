"""Add the v0.2 service-data management schema.

Revision ID: 0001_service_data_v02
Revises: None
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.backend import models  # noqa: F401
from app.backend.db import Base

revision: str = "0001_service_data_v02"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _assert_single_relation(table_name: str, column_name: str) -> None:
    duplicate = op.get_bind().execute(
        sa.text(
            f"SELECT {column_name}, COUNT(*) AS amount FROM {table_name} "
            f"WHERE {column_name} IS NOT NULL GROUP BY {column_name} HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate:
        raise RuntimeError(
            f"Cannot migrate: {table_name}.{column_name} contains duplicate value "
            f"{duplicate[0]!r}. Resolve duplicates before upgrading."
        )


def upgrade() -> None:
    conversation_columns = _column_names("conversations")
    with op.batch_alter_table("conversations") as batch:
        if "source_external_id" not in conversation_columns:
            batch.add_column(sa.Column("source_external_id", sa.String(100), nullable=True))
        if "buyer_nickname" not in conversation_columns:
            batch.add_column(sa.Column("buyer_nickname", sa.String(100), nullable=True))
    op.create_index(
        "ix_conversations_source_external_id",
        "conversations",
        ["source_external_id"],
        unique=True,
    )
    op.create_index(
        "ix_conversations_buyer_nickname", "conversations", ["buyer_nickname"]
    )

    order_columns = _column_names("orders")
    order_additions = [
        sa.Column("buyer_nickname", sa.String(100), nullable=True),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("product_name", sa.String(300), nullable=True),
        sa.Column("logistics_company", sa.String(100), nullable=True),
        sa.Column("logistics_no", sa.String(100), nullable=True),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_stage", sa.String(30), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
    ]
    _assert_single_relation("orders", "conversation_id")
    with op.batch_alter_table("orders") as batch:
        for column in order_additions:
            if column.name not in order_columns:
                batch.add_column(column)
        batch.create_unique_constraint("uq_orders_conversation_id", ["conversation_id"])
    op.create_index("ix_orders_buyer_nickname", "orders", ["buyer_nickname"])
    op.create_index("ix_orders_logistics_no", "orders", ["logistics_no"])

    message_columns = _column_names("messages")
    message_additions = [
        sa.Column("source_external_id", sa.String(100), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=True),
        sa.Column("raw_content", sa.Text(), nullable=True),
        sa.Column("related_order_external_id", sa.String(100), nullable=True),
        sa.Column("related_work_order_external_id", sa.String(100), nullable=True),
    ]
    with op.batch_alter_table("messages") as batch:
        for column in message_additions:
            if column.name not in message_columns:
                batch.add_column(column)
        batch.create_unique_constraint(
            "uq_message_conversation_sequence", ["conversation_id", "sequence_no"]
        )
    op.create_index(
        "ix_messages_source_external_id", "messages", ["source_external_id"], unique=True
    )

    bind = op.get_bind()
    for table_name in (
        "work_orders",
        "replacement_details",
        "offline_payment_details",
        "logistics_details",
        "adverse_reaction_details",
        "return_details",
        "work_order_status_logs",
        "import_batches",
        "import_row_errors",
    ):
        Base.metadata.tables[table_name].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in (
        "import_row_errors",
        "import_batches",
        "work_order_status_logs",
        "return_details",
        "adverse_reaction_details",
        "logistics_details",
        "offline_payment_details",
        "replacement_details",
        "work_orders",
    ):
        Base.metadata.tables[table_name].drop(bind, checkfirst=True)

    op.drop_index("ix_messages_source_external_id", table_name="messages")
    with op.batch_alter_table("messages") as batch:
        batch.drop_constraint("uq_message_conversation_sequence", type_="unique")
        for column_name in (
            "related_work_order_external_id",
            "related_order_external_id",
            "raw_content",
            "sequence_no",
            "source_external_id",
        ):
            batch.drop_column(column_name)

    op.drop_index("ix_orders_logistics_no", table_name="orders")
    op.drop_index("ix_orders_buyer_nickname", table_name="orders")
    with op.batch_alter_table("orders") as batch:
        batch.drop_constraint("uq_orders_conversation_id", type_="unique")
        for column_name in (
            "shipped_at",
            "payment_stage",
            "paid_at",
            "ordered_at",
            "logistics_no",
            "logistics_company",
            "product_name",
            "unit_price",
            "buyer_nickname",
        ):
            batch.drop_column(column_name)

    op.drop_index("ix_conversations_buyer_nickname", table_name="conversations")
    op.drop_index("ix_conversations_source_external_id", table_name="conversations")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("buyer_nickname")
        batch.drop_column("source_external_id")
