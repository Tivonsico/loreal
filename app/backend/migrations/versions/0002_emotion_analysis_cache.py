"""Add persistent emotion-analysis runs and per-conversation cache.

Revision ID: 0002_emotion_analysis_cache
Revises: 0001_service_data_v02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_emotion_analysis_cache"
down_revision: str | None = "0001_service_data_v02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "emotion_analysis_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_kind", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("succeeded_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_emotion_analysis_runs_analysis_kind", "emotion_analysis_runs", ["analysis_kind"]
    )
    op.create_index("ix_emotion_analysis_runs_status", "emotion_analysis_runs", ["status"])

    op.create_table(
        "conversation_emotion_analyses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("analysis_kind", sa.String(50), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("agent_version", sa.String(50), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "conversation_id", "analysis_kind", name="uq_conversation_emotion_kind"
        ),
    )
    op.create_index(
        "ix_conversation_emotion_analyses_conversation_id",
        "conversation_emotion_analyses",
        ["conversation_id"],
    )
    op.create_index(
        "ix_conversation_emotion_analyses_analysis_kind",
        "conversation_emotion_analyses",
        ["analysis_kind"],
    )
    op.create_index(
        "ix_conversation_emotion_analyses_content_fingerprint",
        "conversation_emotion_analyses",
        ["content_fingerprint"],
    )
    op.create_index(
        "ix_conversation_emotion_analyses_status",
        "conversation_emotion_analyses",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("conversation_emotion_analyses")
    op.drop_table("emotion_analysis_runs")
