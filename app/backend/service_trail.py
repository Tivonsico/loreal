"""Shared builder for the customer service trail (panorama API + AI context)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

MAX_TRAIL_NODES = 4


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def build_trail_rows(
    orders: list[Any],
    conversations: list[Any],
    work_orders: list[Any],
    messages: list[Any],
) -> list[dict[str, Any]]:
    """Build chronological trail rows; callers slice or convert as needed."""
    rows: list[dict[str, Any]] = []
    for order in orders:
        rows.append(
            {
                "kind": "order_created",
                "occurred_at": as_utc(order.ordered_at or order.created_at),
                "title": "创建订单",
                "detail": order.product_name,
                "source_type": "order",
                "source_id": order.external_id,
            }
        )
    for conversation in conversations:
        first = next(
            (item for item in messages if item.conversation_id == conversation.id), None
        )
        if first:
            rows.append(
                {
                    "kind": "consultation",
                    "occurred_at": as_utc(first.created_at),
                    "title": "发起咨询",
                    "detail": conversation.title,
                    "source_type": "conversation",
                    "source_id": conversation.id,
                }
            )
    for ticket in work_orders:
        rows.append(
            {
                "kind": "work_order_opened",
                "occurred_at": as_utc(ticket.opened_at or ticket.created_at),
                "title": "创建售后",
                "detail": ticket.description or ticket.external_id,
                "source_type": "work_order",
                "source_id": ticket.external_id,
            }
        )
        if ticket.closed_at:
            rows.append(
                {
                    "kind": "work_order_closed",
                    "occurred_at": as_utc(ticket.closed_at),
                    "title": "售后完成",
                    "detail": ticket.resolution,
                    "source_type": "work_order",
                    "source_id": ticket.external_id,
                }
            )
    rows.sort(key=lambda row: row["occurred_at"])
    return rows