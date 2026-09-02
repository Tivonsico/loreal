from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.agent import ASSISTANCE_AGENT_NAME
from app.backend.agent.context import assemble_context
from app.backend.api.dependencies import require_customer_service
from app.backend.db import get_db
from app.backend.models import (
    AdverseReactionDetail,
    Conversation,
    Message,
    Order,
    WorkOrder,
    WorkOrderStatusLog,
)
from app.backend.schemas import (
    CustomerAddressOut,
    CustomerAfterSalesSummaryOut,
    CustomerIdentityOut,
    CustomerInsightOut,
    CustomerMetricsOut,
    CustomerOrderSummaryOut,
    CustomerPanoramaOut,
    CustomerTagOut,
    DerivedMoodOut,
    PanoramaSnapshotOut,
    ServiceTrailNodeOut,
    SourceReferenceOut,
)

router = APIRouter(
    prefix="/api/v1/management",
    tags=["management-panorama"],
    dependencies=[Depends(require_customer_service)],
)

CONCERN_TERMS = ("过敏", "红肿", "刺痛", "投诉", "退款", "生气", "焦虑", "严重")
LOOKBACK_DAYS = 30
EVIDENCE_REF_LIMIT = 5
RECENT_ITEM_LIMIT = 5
TRAIL_LIMIT = 4
VALUE_TIER_THRESHOLD = Decimal("500")
TICKET_TYPE_LABELS = {
    "replacement_exchange": "补发换货",
    "offline_payment": "线下退款",
    "logistics": "物流售后",
    "adverse_reaction": "不良反应售后",
    "after_sale_return": "退货退款",
}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _latest(values: list[datetime | None]) -> datetime | None:
    normalized = [_utc(value) for value in values if value is not None]
    return max(normalized) if normalized else None


def _ref(source_type: str, source_id: str | int) -> SourceReferenceOut:
    return SourceReferenceOut(source_type=source_type, source_id=str(source_id))


def _safe_place(extra: object, key: str) -> str | None:
    if not isinstance(extra, dict):
        return None
    value = extra.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:100] if value else None


def _ticket_label(ticket_type: str) -> str:
    return TICKET_TYPE_LABELS.get(ticket_type, "售后服务")


@router.get(
    "/conversations/{conversation_id}/panorama",
    response_model=CustomerPanoramaOut,
)
def customer_panorama(
    conversation_id: str,
    db: Session = Depends(get_db),
) -> CustomerPanoramaOut:
    selected = db.get(Conversation, conversation_id)
    if selected is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    customer_id = selected.customer_id
    conversations = list(
        db.scalars(
            select(Conversation)
            .where(Conversation.customer_id == customer_id)
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
        )
    )
    conversation_ids = [item.id for item in conversations]
    messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id.in_(conversation_ids))
            .order_by(Message.created_at.desc(), Message.id.desc())
        )
    )
    customer_messages_by_conversation: dict[str, list[Message]] = defaultdict(list)
    for message in messages:
        if message.sender_role == "customer":
            customer_messages_by_conversation[message.conversation_id].append(message)
    orders = list(
        db.scalars(
            select(Order)
            .where(Order.customer_id == customer_id)
            .order_by(Order.ordered_at.desc(), Order.created_at.desc(), Order.id.desc())
        )
    )
    work_orders = list(
        db.scalars(
            select(WorkOrder)
            .where(WorkOrder.customer_id == customer_id)
            .order_by(WorkOrder.opened_at.desc(), WorkOrder.created_at.desc(), WorkOrder.id.desc())
        )
    )
    order_refs = [_ref("order", item.external_id) for item in orders[:EVIDENCE_REF_LIMIT]]
    work_order_refs = [
        _ref("work_order", item.external_id) for item in work_orders[:EVIDENCE_REF_LIMIT]
    ]
    work_order_ids = [item.id for item in work_orders]
    logs = (
        list(
            db.scalars(
                select(WorkOrderStatusLog)
                .where(WorkOrderStatusLog.work_order_id.in_(work_order_ids))
                .order_by(WorkOrderStatusLog.created_at.desc(), WorkOrderStatusLog.id.desc())
            )
        )
        if work_order_ids
        else []
    )

    data_latest_at = _latest(
        [item.created_at for item in messages]
        + [value for item in orders for value in (item.ordered_at, item.paid_at, item.shipped_at)]
        + [value for item in work_orders for value in (item.opened_at, item.closed_at)]
        + [item.created_at for item in logs]
    )
    consultation_floor = (data_latest_at or datetime.now(UTC)) - timedelta(
        days=LOOKBACK_DAYS
    )
    consultation_count = sum(
        1
        for conversation in conversations
        if any(
            _utc(message.created_at) >= consultation_floor
            for message in customer_messages_by_conversation.get(conversation.id, [])
        )
    )
    paid_values = [item.total_amount for item in orders if item.total_amount is not None]
    recorded_paid_amount = sum(paid_values, Decimal("0"))
    average_order_value = (
        recorded_paid_amount / len(paid_values) if paid_values else Decimal("0")
    )

    tags: list[CustomerTagOut] = []
    if len(orders) >= 2:
        tags.append(
            CustomerTagOut(
                code="repeat_buyer",
                label="复购用户",
                basis=f"同一 customer_id 下记录到 {len(orders)} 笔订单",
                source_refs=order_refs,
            )
        )
    if len(work_orders) >= 2:
        tags.append(
            CustomerTagOut(
                code="repeat_after_sales",
                label="多次售后",
                basis=f"同一 customer_id 下记录到 {len(work_orders)} 个售后工单",
                source_refs=work_order_refs,
            )
        )

    address_groups: dict[tuple[str | None, str | None], list[Order]] = defaultdict(list)
    for order in orders:
        province = _safe_place(order.extra, "province")
        city = _safe_place(order.extra, "city")
        if province or city:
            address_groups[(province, city)].append(order)
    addresses = [
        CustomerAddressOut(
            province=place[0],
            city=place[1],
            order_count=len(group),
            last_used_at=_latest([item.ordered_at or item.created_at for item in group]),
        )
        for place, group in address_groups.items()
    ]
    addresses.sort(
        key=lambda item: item.last_used_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    if len(addresses) > 1:
        tags.append(
            CustomerTagOut(
                code="multi_region",
                label="多地区收货",
                basis=f"订单记录中出现 {len(addresses)} 组省市信息",
                source_refs=order_refs,
            )
        )

    adverse_by_id = {
        item.work_order_id: item
        for item in db.scalars(
            select(AdverseReactionDetail).where(
                AdverseReactionDetail.work_order_id.in_(work_order_ids)
            )
        )
    } if work_order_ids else {}
    skin_types = sorted(
        {
            detail.skin_type.strip()
            for detail in adverse_by_id.values()
            if detail.skin_type and detail.skin_type.strip()
        }
    )
    for skin_type in skin_types[:3]:
        sources = [
            _ref("work_order", item.external_id)
            for item in work_orders
            if adverse_by_id.get(item.id)
            and adverse_by_id[item.id].skin_type
            and adverse_by_id[item.id].skin_type.strip() == skin_type
        ]
        tags.append(
            CustomerTagOut(
                code=f"skin_type:{skin_type}",
                label=skin_type,
                basis="来自售后不良反应工单中记录的肤质字段",
                source_refs=sources[:EVIDENCE_REF_LIMIT],
            )
        )
    if paid_values:
        tier = (
            "high_recorded_value"
            if average_order_value >= VALUE_TIER_THRESHOLD
            else "standard_recorded_value"
        )
        tags.append(
            CustomerTagOut(
                code=tier,
                label="高记录客单" if tier == "high_recorded_value" else "常规记录客单",
                basis=(
                    "记录订单平均实付为 "
                    f"{average_order_value.quantize(Decimal('0.01'))} 元；"
                    f"阈值 {VALUE_TIER_THRESHOLD} 元"
                ),
                source_refs=order_refs,
            )
        )

    trail: list[ServiceTrailNodeOut] = []
    for order in orders:
        occurred_at = _utc(order.ordered_at or order.created_at)
        trail.append(
            ServiceTrailNodeOut(
                kind="order_created",
                occurred_at=occurred_at,
                title="创建订单",
                detail=order.product_name,
                source_ref=_ref("order", order.external_id),
            )
        )
    for conversation in conversations:
        customer_messages = customer_messages_by_conversation.get(conversation.id, [])
        if customer_messages:
            first_message = min(
                customer_messages,
                key=lambda item: (_utc(item.created_at), item.id),
            )
            trail.append(
                ServiceTrailNodeOut(
                    kind="consultation",
                    occurred_at=_utc(first_message.created_at),
                    title="发起咨询",
                    detail=conversation.title,
                    source_ref=_ref("conversation", conversation.id),
                )
            )
    for item in work_orders:
        trail.append(
            ServiceTrailNodeOut(
                kind="work_order_opened",
                occurred_at=_utc(item.opened_at or item.created_at),
                title="创建售后",
                detail=f"{_ticket_label(item.ticket_type)}申请 · 工单 {item.external_id}",
                source_ref=_ref("work_order", item.external_id),
            )
        )
        if item.closed_at:
            trail.append(
                ServiceTrailNodeOut(
                    kind="work_order_closed",
                    occurred_at=_utc(item.closed_at),
                    title="售后闭环",
                    detail=(
                        item.resolution.strip()
                        if item.resolution and item.resolution.strip()
                        else (
                            f"{_ticket_label(item.ticket_type)}已处理完成"
                            f" · 工单 {item.external_id}"
                        )
                    ),
                    source_ref=_ref("work_order", item.external_id),
                )
            )
    deduped: dict[tuple[str, datetime, str, str], ServiceTrailNodeOut] = {}
    for node in trail:
        key = (
            node.kind,
            node.occurred_at,
            node.source_ref.source_type,
            node.source_ref.source_id,
        )
        deduped[key] = node
    ordered_trail = sorted(
        deduped.values(),
        key=lambda node: (
            node.occurred_at,
            node.source_ref.source_type,
            node.source_ref.source_id,
            node.kind,
        ),
        reverse=False,
    )

    customer_messages = [item for item in messages if item.sender_role == "customer"]
    latest_customer_message = customer_messages[0] if customer_messages else None
    mood = "unknown"
    mood_basis = "没有可用于判断的客户文本消息"
    if latest_customer_message and latest_customer_message.content:
        concerned = any(term in latest_customer_message.content for term in CONCERN_TERMS)
        mood = "concerned" if concerned else "calm"
        mood_basis = "最近一条客户文本命中关注词" if concerned else "最近一条客户文本未命中关注词"

    return CustomerPanoramaOut(
        snapshot=PanoramaSnapshotOut(
            generated_at=datetime.now(UTC),
            basis_last_message_id=messages[0].id if messages else None,
            data_latest_at=data_latest_at,
        ),
        identity=CustomerIdentityOut(
            customer_id=customer_id,
            buyer_nickname=selected.buyer_nickname,
        ),
        metrics=CustomerMetricsOut(
            recorded_paid_amount=recorded_paid_amount,
            order_count=len(orders),
            average_order_value=average_order_value,
            consultation_count_30d=consultation_count,
            after_sales_count=len(work_orders),
            latest_order_at=_latest([item.ordered_at or item.created_at for item in orders]),
        ),
        tags=tags,
        addresses=addresses,
        recent_orders=[
            CustomerOrderSummaryOut(
                external_id=item.external_id,
                product_name=item.product_name,
                recorded_paid_amount=item.total_amount,
                status=item.status,
                ordered_at=_utc(item.ordered_at),
            )
            for item in orders[:RECENT_ITEM_LIMIT]
        ],
        recent_after_sales=[
            CustomerAfterSalesSummaryOut(
                external_id=item.external_id,
                ticket_type=item.ticket_type,
                status=item.status,
                assignee=item.assignee,
                opened_at=_utc(item.opened_at),
                closed_at=_utc(item.closed_at),
            )
            for item in work_orders[:RECENT_ITEM_LIMIT]
        ],
        service_trail=ordered_trail[-TRAIL_LIMIT:],
        service_trail_total=min(len(ordered_trail), TRAIL_LIMIT),
        derived_mood=DerivedMoodOut(
            value=mood,
            basis_message_id=latest_customer_message.id if latest_customer_message else None,
            basis=mood_basis,
        ),
    )


@router.post(
    "/conversations/{conversation_id}/panorama/analysis",
    response_model=CustomerInsightOut,
)
def customer_panorama_analysis(
    conversation_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> CustomerInsightOut:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    context = assemble_context(db, conversation)
    panorama = customer_panorama(conversation_id, db)
    context["customer_journey"] = [
        node.model_dump(mode="json") for node in panorama.service_trail
    ]
    try:
        agent = request.app.state.agent_registry.get(ASSISTANCE_AGENT_NAME)
        analysis = agent.run(context)
    except (LookupError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="AI 用户洞察暂时不可用") from exc

    if analysis.sentiment == "concerned":
        emotion_label = "焦虑" if analysis.urgency == "high" else "需要安抚"
    else:
        emotion_label = "情绪已缓和" if analysis.urgency != "normal" else "平稳"
    risk_level = (
        "high"
        if analysis.urgency == "high"
        else "medium"
        if analysis.urgency == "medium" or analysis.risks
        else "low"
    )
    return CustomerInsightOut(
        generated_at=analysis.analyzed_at,
        mode=analysis.mode,
        intent=analysis.intent,
        summary=analysis.summary,
        sentiment=analysis.sentiment,
        emotion_label=emotion_label,
        sentiment_confidence=analysis.sentiment_confidence,
        sentiment_reason=analysis.sentiment_reason,
        urgency=analysis.urgency,
        risk_level=risk_level,
        evidence_message_ids=analysis.evidence_message_ids,
        degraded_reason=analysis.degraded_reason,
        journey_insights=analysis.journey_insights,
        assistance=analysis,
    )
