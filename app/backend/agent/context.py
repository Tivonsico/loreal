from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.backend.models import Conversation, Message, Order, Product, WorkOrder
from app.backend.service_trail import MAX_TRAIL_NODES, build_trail_rows

MAX_CHAT_CHARS = 12_000


def stable_context_fingerprint(context: dict[str, Any]) -> str:
    """Hash semantic context while ignoring capture time and a prior fingerprint."""
    payload = dict(context)
    snapshot = dict(payload.get("snapshot") or {})
    snapshot.pop("captured_at", None)
    snapshot.pop("fingerprint", None)
    payload["snapshot"] = snapshot
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_value
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _record(status: str, selected_by: str | None = None, record: dict | None = None) -> dict:
    return {"status": status, "selected_by": selected_by, "record": record}


def _safe_order(order: Order) -> dict[str, Any]:
    fields = (
        "external_id",
        "status",
        "product_external_id",
        "product_name",
        "quantity",
        "total_amount",
        "logistics_company",
        "logistics_no",
        "ordered_at",
        "paid_at",
        "shipped_at",
    )
    return {field: _json_value(getattr(order, field)) for field in fields}


def _safe_product(product: Product) -> dict[str, Any]:
    fields = ("external_id", "sku", "name", "brand", "description", "price")
    return {field: _json_value(getattr(product, field)) for field in fields}


def _safe_work_order(work_order: WorkOrder) -> dict[str, Any]:
    fields = (
        "external_id",
        "ticket_type",
        "order_external_id",
        "status",
        "description",
        "resolution",
        "opened_at",
        "closed_at",
    )
    return {field: _json_value(getattr(work_order, field)) for field in fields}


def _resolve_order(db: Session, conversation: Conversation, messages: list[Message]) -> dict:
    direct = db.scalar(select(Order).where(Order.conversation_id == conversation.id))
    references = {
        item.related_order_external_id for item in messages if item.related_order_external_id
    }
    if direct and references - {direct.external_id}:
        return {**_record("conflict"), "references": sorted(references)}
    if direct:
        return {
            **_record("present", "conversation_relation", _safe_order(direct)),
            "references": sorted(references),
        }
    if len(references) > 1:
        return {**_record("conflict"), "references": sorted(references)}
    if references:
        external_id = next(iter(references))
        order = db.scalar(select(Order).where(Order.external_id == external_id))
        if order is None:
            return {**_record("referenced_not_found"), "references": [external_id]}
        if order.customer_id != conversation.customer_id:
            return {**_record("filtered"), "references": [external_id]}
        return {
            **_record("present", "message_reference", _safe_order(order)),
            "references": [external_id],
        }
    return {**_record("not_linked"), "references": []}


def _resolve_work_order(
    db: Session, conversation: Conversation, messages: list[Message]
) -> dict:
    direct = db.scalar(select(WorkOrder).where(WorkOrder.conversation_id == conversation.id))
    references = {
        item.related_work_order_external_id
        for item in messages
        if item.related_work_order_external_id
    }
    if direct and references - {direct.external_id}:
        return {**_record("conflict"), "references": sorted(references)}
    if direct:
        return {
            **_record("present", "conversation_relation", _safe_work_order(direct)),
            "references": sorted(references),
        }
    if len(references) > 1:
        return {**_record("conflict"), "references": sorted(references)}
    if references:
        external_id = next(iter(references))
        work_order = db.scalar(select(WorkOrder).where(WorkOrder.external_id == external_id))
        if work_order is None:
            return {**_record("referenced_not_found"), "references": [external_id]}
        if work_order.customer_id and work_order.customer_id != conversation.customer_id:
            return {**_record("filtered"), "references": [external_id]}
        return {
            **_record("present", "message_reference", _safe_work_order(work_order)),
            "references": [external_id],
        }
    return {**_record("not_linked"), "references": []}


def _safe_service_trail(db: Session, conversation: Conversation) -> list[dict[str, Any]]:
    """Latest trail nodes so the model writes summaries against real node titles."""
    conversations = list(
        db.scalars(
            select(Conversation).where(Conversation.customer_id == conversation.customer_id)
        )
    )
    conversation_ids = [item.id for item in conversations]
    orders = list(
        db.scalars(
            select(Order)
            .where(Order.customer_id == conversation.customer_id)
            .order_by(Order.ordered_at.desc(), Order.created_at.desc())
        )
    )
    work_orders = list(
        db.scalars(
            select(WorkOrder).where(
                or_(
                    WorkOrder.customer_id == conversation.customer_id,
                    WorkOrder.conversation_id.in_(conversation_ids),
                )
            )
        )
    )
    message_times = db.execute(
        select(Message.conversation_id, Message.created_at).order_by(Message.created_at, Message.id)
    ).all()
    rows = build_trail_rows(orders, conversations, work_orders, message_times)[-MAX_TRAIL_NODES:]
    return [
        {
            "title": row["title"],
            "detail": (row["detail"] or "")[:80],
            "occurred_at": row["occurred_at"].isoformat(),
        }
        for row in rows
    ]


def assemble_context(db: Session, conversation: Conversation) -> dict[str, Any]:
    messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at, Message.id)
        )
    )
    order = _resolve_order(db, conversation, messages)
    work_order = _resolve_work_order(db, conversation, messages)
    product = _record("not_linked")
    order_record = order.get("record")
    if order_record and order_record.get("product_external_id"):
        product_row = db.scalar(
            select(Product).where(Product.external_id == order_record["product_external_id"])
        )
        product = (
            _record("present", "selected_order", _safe_product(product_row))
            if product_row
            else _record("referenced_not_found", "selected_order")
        )

    selected: list[dict[str, Any]] = []
    used_chars = 0
    omitted = 0
    for message in reversed(messages):
        content = (message.content or "").strip()
        if not content:
            continue
        if used_chars + len(content) > MAX_CHAT_CHARS and selected:
            omitted += 1
            continue
        selected.append(
            {
                "id": message.id,
                "sender_role": message.sender_role,
                "content": content[:MAX_CHAT_CHARS],
                "created_at": message.created_at.isoformat(),
                "related_order_external_id": message.related_order_external_id,
                "related_work_order_external_id": message.related_work_order_external_id,
            }
        )
        used_chars += len(content)
    selected.reverse()
    last_message_id = messages[-1].id if messages else None
    envelope = {
        "schema": "customer-service-context.v1",
        "conversation": {
            "id": conversation.id,
            "source_external_id": conversation.source_external_id,
            "customer_id": conversation.customer_id,
            "buyer_nickname": conversation.buyer_nickname,
            "status": conversation.status,
        },
        "snapshot": {
            "captured_at": datetime.now(UTC).isoformat(),
            "last_message_id": last_message_id,
            "message_count": len(messages),
        },
        "chat": {
            "status": "present" if selected else "empty",
            "messages": selected,
            "included_count": len(selected),
            "omitted_count": omitted,
        },
        "order": order,
        "product": product,
        "work_order": work_order,
        "service_trail": _safe_service_trail(db, conversation),
        "reply_handbook": {"status": "source_unavailable", "candidates": []},
    }
    envelope["snapshot"]["fingerprint"] = stable_context_fingerprint(envelope)
    return envelope
