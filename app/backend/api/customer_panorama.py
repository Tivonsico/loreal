from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.backend.api.dependencies import require_customer_service
from app.backend.db import get_db
from app.backend.models import Conversation, Message, Order, WorkOrder
from app.backend.schemas import CustomerPanoramaOut, ServiceTrailNodeOut, SourceReferenceOut

router = APIRouter(
    prefix="/api/v1/management",
    tags=["management-panorama"],
    dependencies=[Depends(require_customer_service)],
)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _ref(kind: str, identity: str | int) -> SourceReferenceOut:
    return SourceReferenceOut(source_type=kind, source_id=str(identity))


@router.get(
    "/conversations/{conversation_id}/panorama", response_model=CustomerPanoramaOut
)
def customer_panorama(
    conversation_id: str, db: Session = Depends(get_db)
) -> CustomerPanoramaOut:
    selected = db.get(Conversation, conversation_id)
    if selected is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    conversations = list(
        db.scalars(select(Conversation).where(Conversation.customer_id == selected.customer_id))
    )
    conversation_ids = [item.id for item in conversations]
    orders = list(
        db.scalars(
            select(Order)
            .where(Order.customer_id == selected.customer_id)
            .order_by(Order.ordered_at.desc(), Order.created_at.desc())
        )
    )
    work_orders = list(
        db.scalars(
            select(WorkOrder)
            .where(
                or_(
                    WorkOrder.customer_id == selected.customer_id,
                    WorkOrder.conversation_id.in_(conversation_ids),
                )
            )
            .order_by(WorkOrder.opened_at.desc(), WorkOrder.created_at.desc())
        )
    )
    messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id.in_(conversation_ids))
            .order_by(Message.created_at, Message.id)
        )
    )
    latest_data_at = max(
        [_as_utc(item.created_at) for item in messages]
        + [_as_utc(item.created_at) for item in conversations],
        default=datetime.now(UTC),
    )
    floor = latest_data_at - timedelta(days=30)
    consulted = {
        item.conversation_id
        for item in messages
        if item.sender_role == "customer" and _as_utc(item.created_at) >= floor
    }

    region = None
    for order in orders:
        extra = order.extra if isinstance(order.extra, dict) else {}
        province = str(extra.get("province") or "").strip()
        city = str(extra.get("city") or "").strip()
        if province or city:
            region = " ".join(part for part in (province, city) if part)[:100]
            break

    fact_tags = []
    if len(orders) >= 2:
        fact_tags.append("复购客户")
    if len(work_orders) >= 2:
        fact_tags.append("多次售后")
    if any(item.ticket_type == "adverse_reaction" for item in work_orders):
        fact_tags.append("有肌肤不适记录")

    trail: list[ServiceTrailNodeOut] = []
    for order in orders:
        trail.append(
            ServiceTrailNodeOut(
                kind="order_created",
                occurred_at=_as_utc(order.ordered_at or order.created_at),
                title="创建订单",
                detail=order.product_name,
                source_ref=_ref("order", order.external_id),
            )
        )
    for conversation in conversations:
        first = next((item for item in messages if item.conversation_id == conversation.id), None)
        if first:
            trail.append(
                ServiceTrailNodeOut(
                    kind="consultation",
                    occurred_at=_as_utc(first.created_at),
                    title="发起咨询",
                    detail=conversation.title,
                    source_ref=_ref("conversation", conversation.id),
                )
            )
    for ticket in work_orders:
        trail.append(
            ServiceTrailNodeOut(
                kind="work_order_opened",
                occurred_at=_as_utc(ticket.opened_at or ticket.created_at),
                title="创建售后",
                detail=ticket.description or ticket.external_id,
                source_ref=_ref("work_order", ticket.external_id),
            )
        )
        if ticket.closed_at:
            trail.append(
                ServiceTrailNodeOut(
                    kind="work_order_closed",
                    occurred_at=_as_utc(ticket.closed_at),
                    title="售后完成",
                    detail=ticket.resolution,
                    source_ref=_ref("work_order", ticket.external_id),
                )
            )
    trail.sort(key=lambda item: item.occurred_at)

    amounts = [item.total_amount for item in orders if item.total_amount is not None]
    return CustomerPanoramaOut(
        conversation_id=selected.id,
        customer_id=selected.customer_id,
        buyer_nickname=selected.buyer_nickname,
        region=region,
        recorded_paid_amount=sum(amounts, Decimal("0")),
        order_count=len(orders),
        consultation_count_30d=len(consulted),
        after_sales_count=len(work_orders),
        latest_order_at=(orders[0].ordered_at or orders[0].created_at) if orders else None,
        fact_tags=fact_tags[:4],
        service_trail=trail[-4:],
    )
