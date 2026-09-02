from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.backend.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


def uuid_str() -> str:
    return str(uuid.uuid4())


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    source_external_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, index=True, nullable=True
    )
    customer_id: Mapped[str] = mapped_column(String(100), index=True)
    buyer_nickname: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(100), index=True)
    buyer_nickname: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    product_external_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("products.external_id"), nullable=True, index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id"), nullable=True, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(50), default="unknown", index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    logistics_company: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logistics_no: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence_no", name="uq_message_conversation_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_external_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, index=True, nullable=True
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    sender_role: Mapped[str] = mapped_column(String(20), index=True)
    sequence_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message_type: Mapped[str] = mapped_column(String(20), index=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_order_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    related_work_order_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    media_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class RealtimeEvent(Base):
    __tablename__ = "realtime_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    message_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("messages.id", ondelete="CASCADE"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    ticket_type: Mapped[str] = mapped_column(String(40), index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id"), unique=True, index=True, nullable=True
    )
    order_external_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("orders.external_id"), index=True, nullable=True
    )
    customer_id: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    buyer_nickname: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    source_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReplacementDetail(Base):
    __tablename__ = "replacement_details"

    work_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), primary_key=True
    )
    issue_kind: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_tracking_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    replacement_tracking_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logistics_company: Mapped[str | None] = mapped_column(String(100), nullable=True)
    warehouse: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False)


class OfflinePaymentDetail(Base):
    __tablename__ = "offline_payment_details"

    work_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), primary_key=True
    )
    payment_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    masked_real_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    masked_account: Mapped[str | None] = mapped_column(String(100), nullable=True)
    related_tracking_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transfer_status: Mapped[str | None] = mapped_column(String(50), nullable=True)


class LogisticsDetail(Base):
    __tablename__ = "logistics_details"

    work_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), primary_key=True
    )
    issue_kind: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logistics_company: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tracking_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    warehouse: Mapped[str | None] = mapped_column(String(200), nullable=True)
    order_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    handling_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)


class AdverseReactionDetail(Base):
    __tablename__ = "adverse_reaction_details"

    work_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), primary_key=True
    )
    channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skin_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    product_batch_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    affected_area: Mapped[str | None] = mapped_column(String(200), nullable=True)
    symptoms: Mapped[str | None] = mapped_column(Text, nullable=True)
    onset_after: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stopped_use: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sought_medical_care: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class ReturnDetail(Base):
    __tablename__ = "return_details"

    work_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), primary_key=True
    )
    package_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    return_tracking_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logistics_company: Mapped[str | None] = mapped_column(String(100), nullable=True)
    refund_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    receipt_advice: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_abnormal: Mapped[bool] = mapped_column(Boolean, default=False)


class WorkOrderStatusLog(Base):
    __tablename__ = "work_order_status_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    filename: Mapped[str] = mapped_column(String(300))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="previewed", index=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImportRowError(Base):
    __tablename__ = "import_row_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    sheet_name: Mapped[str] = mapped_column(String(100))
    row_number: Mapped[int] = mapped_column(Integer)
    column_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_code: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
