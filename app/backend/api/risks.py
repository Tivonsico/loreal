from __future__ import annotations

import hashlib
from bisect import bisect_right
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.api.dependencies import require_customer_service
from app.backend.db import get_db
from app.backend.models import (
    AdverseReactionDetail,
    Conversation,
    Message,
    Order,
    ReplacementDetail,
    ReturnDetail,
    WorkOrder,
    WorkOrderStatusLog,
)
from app.backend.schemas import (
    RiskEvidenceOut,
    RiskKind,
    RiskOverviewOut,
    RiskTrendPointOut,
    RiskWarningOut,
    RiskWarningPage,
    SourceReferenceOut,
)

router = APIRouter(
    prefix="/api/v1/management",
    tags=["management-risks"],
    dependencies=[Depends(require_customer_service)],
)

RULE_VERSION = "risk-v1"
SHANGHAI_NAME = "Asia/Shanghai"
MODERN_SHANGHAI_START = datetime(1992, 1, 1, tzinfo=UTC)
LOOKBACK_DAYS = 30
RESPONSE_SLA = timedelta(hours=2)
EXCERPT_LIMIT = 200
EVIDENCE_REF_LIMIT = 5
EMOTION_TERMS = ("生气", "失望", "严重", "受不了", "红肿", "刺痛", "过敏")
PUBLIC_COMPLAINT_TERMS = ("曝光", "平台投诉", "消协", "媒体", "小红书投诉", "公开投诉")
REFUND_TYPES = {"offline_payment", "after_sale_return"}
KIND_TITLES = {
    "emotion_escalation": "情绪升级",
    "repeat_contact": "重复进线",
    "repeat_refund": "重复退款",
    "public_complaint": "舆情投诉",
    "service_timeout": "服务超时",
}
BASE_SEVERITY = {
    "emotion_escalation": "high",
    "repeat_contact": "medium",
    "repeat_refund": "medium",
    "public_complaint": "high",
    "service_timeout": "low",
}


def _shanghai(earliest_data_at: datetime | None = None) -> tzinfo:
    try:
        return ZoneInfo(SHANGHAI_NAME)
    except ZoneInfoNotFoundError as exc:
        boundary = _utc(earliest_data_at) or datetime.now(UTC)
        if boundary < MODERN_SHANGHAI_START:
            raise HTTPException(
                status_code=503,
                detail="历史数据需要 IANA Asia/Shanghai 时区数据库",
            ) from exc
        # Shanghai has observed UTC+08:00 without DST throughout this modern data domain.
        return timezone(timedelta(hours=8), SHANGHAI_NAME)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _local_date(value: datetime, timezone: tzinfo) -> date:
    return _utc(value).astimezone(timezone).date()


def _ref(source_type: str, source_id: str | int) -> SourceReferenceOut:
    return SourceReferenceOut(source_type=source_type, source_id=str(source_id))


def _warning_id(rule: str, primary_ref: SourceReferenceOut, customer_id: str) -> str:
    raw = f"{RULE_VERSION}|{rule}|{primary_ref.source_type}:{primary_ref.source_id}|{customer_id}"
    return f"rw_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _event_bounds(
    conversations: list[Conversation],
    messages: list[Message],
    orders: list[Order],
    work_orders: list[WorkOrder],
    logs: list[WorkOrderStatusLog],
) -> tuple[datetime | None, datetime | None]:
    values = (
        [item.created_at for item in conversations]
        + [item.created_at for item in messages]
        + [
            value
            for item in orders
            for value in (item.ordered_at, item.paid_at, item.shipped_at, item.updated_at)
            if value is not None
        ]
        + [
            value
            for item in work_orders
            for value in (item.opened_at, item.closed_at, item.updated_at)
            if value is not None
        ]
        + [item.created_at for item in logs]
    )
    normalized = [_utc(value) for value in values]
    return (
        min(normalized, default=None),
        max(normalized, default=None),
    )


def _elevated(
    work_order: WorkOrder,
    urgent_ids: set[int],
    abnormal_ids: set[int],
    adverse_ids: set[int],
) -> bool:
    return (
        work_order.ticket_type == "adverse_reaction"
        or work_order.id in urgent_ids
        or work_order.id in abnormal_ids
        or work_order.id in adverse_ids
    )


def _any_elevated(
    candidates: list[WorkOrder],
    signal_ids: tuple[set[int], set[int], set[int]],
) -> bool:
    urgent_ids, abnormal_ids, adverse_ids = signal_ids
    return any(
        _elevated(item, urgent_ids, abnormal_ids, adverse_ids) for item in candidates
    )


def _representative_work_order(
    candidates: list[WorkOrder],
    signal_ids: tuple[set[int], set[int], set[int]],
    explicit_external_id: str | None = None,
) -> WorkOrder | None:
    if explicit_external_id:
        explicit = next(
            (item for item in candidates if item.external_id == explicit_external_id),
            None,
        )
        if explicit:
            return explicit
    urgent_ids, abnormal_ids, adverse_ids = signal_ids

    def precedence(item: WorkOrder) -> tuple[bool, bool, datetime]:
        return (
            _elevated(item, urgent_ids, abnormal_ids, adverse_ids),
            item.status != "completed" and item.closed_at is None,
            _utc(item.closed_at or item.updated_at or item.opened_at or item.created_at),
        )

    best = max((precedence(item) for item in candidates), default=None)
    return min(
        (item for item in candidates if precedence(item) == best),
        key=lambda item: item.external_id,
        default=None,
    )


def _resolve_as_of(
    requested: date | None,
    latest: datetime | None,
    timezone: tzinfo,
) -> date:
    if requested is not None:
        return requested
    return latest.astimezone(timezone).date() if latest else datetime.now(timezone).date()


def _status(
    work_order: WorkOrder | None,
    logs_by_work_order: dict[int, list[WorkOrderStatusLog]],
    response_at: datetime | None,
) -> tuple[str, str, str | None, datetime | None]:
    if work_order and (work_order.status == "completed" or work_order.closed_at):
        resolved = _utc(work_order.closed_at or work_order.updated_at)
        return "closed", "关联工单已完成", work_order.assignee, resolved
    if response_at is not None:
        return (
            "closed",
            "已有后续客服回复",
            work_order.assignee if work_order else None,
            response_at,
        )
    if work_order and (work_order.assignee or logs_by_work_order.get(work_order.id)):
        basis = "关联工单已有负责人" if work_order.assignee else "关联工单已有处理日志"
        return "processing", basis, work_order.assignee, None
    return "pending_confirmation", "尚无完成、回复或处理证据", None, None


def _build_warning(
    *,
    rule: RiskKind,
    occurred_at: datetime,
    customer_id: str,
    buyer_nickname: str | None,
    primary_ref: SourceReferenceOut,
    summary: str,
    conversation: Conversation | None,
    work_order: WorkOrder | None,
    evidence: list[RiskEvidenceOut],
    evidence_message_ids: list[int],
    logs_by_work_order: dict[int, list[WorkOrderStatusLog]],
    response_at: datetime | None = None,
    elevated: bool = False,
) -> RiskWarningOut:
    status, status_basis, assignee, resolved_at = _status(
        work_order, logs_by_work_order, response_at
    )
    severity = "high" if elevated else BASE_SEVERITY[rule]
    source_refs: list[SourceReferenceOut] = []
    seen_refs: set[tuple[str, str]] = set()
    for item in evidence:
        key = (item.source_ref.source_type, item.source_ref.source_id)
        if key not in seen_refs:
            seen_refs.add(key)
            source_refs.append(item.source_ref)
    return RiskWarningOut(
        id=_warning_id(rule, primary_ref, customer_id),
        rule_code=rule,
        kind=rule,
        severity=severity,
        status=status,
        status_basis=status_basis,
        assignee=assignee,
        occurred_at=_utc(occurred_at),
        first_response_at=response_at,
        resolved_at=resolved_at,
        conversation_id=(
            conversation.id
            if conversation
            else work_order.conversation_id
            if work_order
            else None
        ),
        customer_id=customer_id,
        buyer_nickname=buyer_nickname,
        order_external_id=work_order.order_external_id if work_order else None,
        work_order_external_id=work_order.external_id if work_order else None,
        title=KIND_TITLES[rule],
        summary=summary,
        evidence_message_ids=sorted(set(evidence_message_ids)),
        source_refs=source_refs[:EVIDENCE_REF_LIMIT],
        evidence=evidence,
    )


def _collect_warnings(
    db: Session,
) -> tuple[list[RiskWarningOut], datetime | None, datetime | None]:
    conversations = list(db.scalars(select(Conversation)))
    messages = list(db.scalars(select(Message)))
    orders = list(db.scalars(select(Order)))
    work_orders = list(db.scalars(select(WorkOrder)))
    logs = list(db.scalars(select(WorkOrderStatusLog)))
    earliest, latest = _event_bounds(conversations, messages, orders, work_orders, logs)

    conversation_by_id = {item.id: item for item in conversations}
    customer_messages_by_conversation: dict[str, list[Message]] = defaultdict(list)
    service_messages_by_conversation: dict[str, list[Message]] = defaultdict(list)
    for message in messages:
        target = (
            service_messages_by_conversation
            if message.sender_role == "customer_service"
            else customer_messages_by_conversation
            if message.sender_role == "customer"
            else None
        )
        if target is not None:
            target[message.conversation_id].append(message)
    for grouped_messages in (
        customer_messages_by_conversation,
        service_messages_by_conversation,
    ):
        for group in grouped_messages.values():
            group.sort(key=lambda item: (_utc(item.created_at), item.id))
    service_times_by_conversation = {
        key: [_utc(item.created_at) for item in group]
        for key, group in service_messages_by_conversation.items()
    }
    work_orders_by_conversation: dict[str, list[WorkOrder]] = defaultdict(list)
    for work_order in work_orders:
        if work_order.conversation_id:
            work_orders_by_conversation[work_order.conversation_id].append(work_order)
    logs_by_work_order: dict[int, list[WorkOrderStatusLog]] = defaultdict(list)
    for log in logs:
        logs_by_work_order[log.work_order_id].append(log)

    work_order_ids = [item.id for item in work_orders]
    urgent_ids = {
        item.work_order_id
        for item in db.scalars(
            select(ReplacementDetail).where(
                ReplacementDetail.work_order_id.in_(work_order_ids),
                ReplacementDetail.is_urgent.is_(True),
            )
        )
    } if work_order_ids else set()
    abnormal_ids = {
        item.work_order_id
        for item in db.scalars(
            select(ReturnDetail).where(
                ReturnDetail.work_order_id.in_(work_order_ids),
                ReturnDetail.is_abnormal.is_(True),
            )
        )
    } if work_order_ids else set()
    adverse_ids = {
        item.work_order_id
        for item in db.scalars(
            select(AdverseReactionDetail).where(
                AdverseReactionDetail.work_order_id.in_(work_order_ids)
            )
        )
    } if work_order_ids else set()

    signal_ids = (urgent_ids, abnormal_ids, adverse_ids)

    def next_service_message(conversation_id: str, after: datetime) -> Message | None:
        times = service_times_by_conversation.get(conversation_id, [])
        index = bisect_right(times, _utc(after))
        group = service_messages_by_conversation.get(conversation_id, [])
        return group[index] if index < len(group) else None

    warnings: list[RiskWarningOut] = []
    for conversation in conversations:
        candidates = work_orders_by_conversation.get(conversation.id, [])
        conversation_elevated = _any_elevated(candidates, signal_ids)
        customer_messages = customer_messages_by_conversation.get(conversation.id, [])
        neutral_seen = False
        escalation_recorded = False
        for message in customer_messages:
            content = message.content or ""
            work_order = _representative_work_order(
                candidates,
                signal_ids,
                message.related_work_order_external_id,
            )
            emotion_hit = any(term in content for term in EMOTION_TERMS)
            if neutral_seen and emotion_hit and not escalation_recorded:
                response = next_service_message(conversation.id, message.created_at)
                ref = _ref("message", message.id)
                warnings.append(
                    _build_warning(
                        rule="emotion_escalation",
                        occurred_at=message.created_at,
                        customer_id=conversation.customer_id,
                        buyer_nickname=conversation.buyer_nickname,
                        primary_ref=ref,
                        summary="同一会话中客户由未命中关注词转为命中升级词",
                        conversation=conversation,
                        work_order=work_order,
                        evidence=[
                            RiskEvidenceOut(
                                source_ref=ref,
                                occurred_at=_utc(message.created_at),
                                label="升级消息",
                                excerpt=content[:EXCERPT_LIMIT] or None,
                            )
                        ],
                        evidence_message_ids=[message.id],
                        logs_by_work_order=logs_by_work_order,
                        response_at=_utc(response.created_at) if response else None,
                        elevated=conversation_elevated,
                    )
                )
                escalation_recorded = True
            if not emotion_hit and content.strip():
                neutral_seen = True

            if any(term in content for term in PUBLIC_COMPLAINT_TERMS):
                response = next_service_message(conversation.id, message.created_at)
                ref = _ref("message", message.id)
                warnings.append(
                    _build_warning(
                        rule="public_complaint",
                        occurred_at=message.created_at,
                        customer_id=conversation.customer_id,
                        buyer_nickname=conversation.buyer_nickname,
                        primary_ref=ref,
                        summary="客户消息命中 risk-v1 公开投诉词表",
                        conversation=conversation,
                        work_order=work_order,
                        evidence=[
                            RiskEvidenceOut(
                                source_ref=ref,
                                occurred_at=_utc(message.created_at),
                                label="投诉消息",
                                excerpt=content[:EXCERPT_LIMIT],
                            )
                        ],
                        evidence_message_ids=[message.id],
                        logs_by_work_order=logs_by_work_order,
                        response_at=_utc(response.created_at) if response else None,
                        elevated=conversation_elevated,
                    )
                )

            response = next_service_message(conversation.id, message.created_at)
            deadline = _utc(message.created_at) + RESPONSE_SLA
            if response is None or _utc(response.created_at) > deadline:
                ref = _ref("message", message.id)
                warnings.append(
                    _build_warning(
                        rule="service_timeout",
                        occurred_at=deadline,
                        customer_id=conversation.customer_id,
                        buyer_nickname=conversation.buyer_nickname,
                        primary_ref=ref,
                        summary="客户消息在 2 小时响应时限内未收到客服回复",
                        conversation=conversation,
                        work_order=work_order,
                        evidence=[
                            RiskEvidenceOut(
                                source_ref=ref,
                                occurred_at=_utc(message.created_at),
                                label="等待回复的客户消息",
                                excerpt=content[:EXCERPT_LIMIT] or None,
                            )
                        ],
                        evidence_message_ids=[message.id],
                        logs_by_work_order=logs_by_work_order,
                        response_at=_utc(response.created_at) if response else None,
                        elevated=conversation_elevated,
                    )
                )

    conversations_by_customer: dict[str, list[tuple[datetime, Conversation]]] = defaultdict(list)
    for conversation in conversations:
        customer_messages = customer_messages_by_conversation.get(conversation.id, [])
        occurred = customer_messages[0].created_at if customer_messages else conversation.created_at
        conversations_by_customer[conversation.customer_id].append((_utc(occurred), conversation))
    for customer_id, group in conversations_by_customer.items():
        group.sort(key=lambda item: (item[0], item[1].id))
        for index, (occurred, conversation) in enumerate(group):
            prior = [
                item
                for item in group[:index]
                if occurred - item[0] <= timedelta(days=LOOKBACK_DAYS)
            ]
            if not prior:
                continue
            ref = _ref("conversation", conversation.id)
            candidates = work_orders_by_conversation.get(conversation.id, [])
            work_order = _representative_work_order(candidates, signal_ids)
            warnings.append(
                _build_warning(
                    rule="repeat_contact",
                    occurred_at=occurred,
                    customer_id=customer_id,
                    buyer_nickname=conversation.buyer_nickname,
                    primary_ref=ref,
                    summary=f"30 日内第 {len(prior) + 1} 次发起会话",
                    conversation=conversation,
                    work_order=work_order,
                    evidence=[
                        RiskEvidenceOut(
                            source_ref=ref,
                            occurred_at=occurred,
                            label="重复进线会话",
                        )
                    ],
                    evidence_message_ids=[],
                    logs_by_work_order=logs_by_work_order,
                    elevated=_any_elevated(candidates, signal_ids),
                )
            )

    refunds_by_customer: dict[str, list[tuple[datetime, WorkOrder]]] = defaultdict(list)
    for work_order in work_orders:
        if work_order.customer_id and work_order.ticket_type in REFUND_TYPES:
            refunds_by_customer[work_order.customer_id].append(
                (_utc(work_order.opened_at or work_order.created_at), work_order)
            )
    for customer_id, group in refunds_by_customer.items():
        group.sort(key=lambda item: (item[0], item[1].external_id))
        for index, (occurred, work_order) in enumerate(group):
            prior = [
                item
                for item in group[:index]
                if occurred - item[0] <= timedelta(days=LOOKBACK_DAYS)
            ]
            if not prior:
                continue
            conversation = conversation_by_id.get(work_order.conversation_id)
            ref = _ref("work_order", work_order.external_id)
            warnings.append(
                _build_warning(
                    rule="repeat_refund",
                    occurred_at=occurred,
                    customer_id=customer_id,
                    buyer_nickname=work_order.buyer_nickname,
                    primary_ref=ref,
                    summary=f"30 日内第 {len(prior) + 1} 个退款或退货工单",
                    conversation=conversation,
                    work_order=work_order,
                    evidence=[
                        RiskEvidenceOut(
                            source_ref=ref,
                            occurred_at=occurred,
                            label="重复退款工单",
                        )
                    ],
                    evidence_message_ids=[],
                    logs_by_work_order=logs_by_work_order,
                    elevated=work_order.id in urgent_ids
                    or work_order.id in abnormal_ids
                    or work_order.id in adverse_ids,
                )
            )

    warnings.sort(key=lambda item: (item.occurred_at, item.id), reverse=True)
    return warnings, earliest, latest


@router.get("/risks/overview", response_model=RiskOverviewOut)
def risk_overview(
    as_of_date: date | None = None,
    db: Session = Depends(get_db),
) -> RiskOverviewOut:
    warnings, earliest, latest = _collect_warnings(db)
    timezone = _shanghai(earliest)
    selected_date = _resolve_as_of(as_of_date, latest, timezone)
    selected = [
        item
        for item in warnings
        if _local_date(item.occurred_at, timezone) == selected_date
    ]
    closed = [item for item in selected if item.status == "closed"]
    durations = [
        (item.resolved_at - item.occurred_at).total_seconds() / 3600
        for item in closed
        if item.resolved_at is not None and item.resolved_at >= item.occurred_at
    ]
    trend = []
    for offset in range(6, -1, -1):
        bucket = selected_date - timedelta(days=offset)
        trend.append(
            RiskTrendPointOut(
                date=bucket.isoformat(),
                warning_count=sum(
                    1 for item in warnings if _local_date(item.occurred_at, timezone) == bucket
                ),
            )
        )
    return RiskOverviewOut(
        as_of_date=selected_date.isoformat(),
        data_latest_at=latest,
        warning_count=len(selected),
        high_open_count=sum(
            1 for item in selected if item.severity == "high" and item.status != "closed"
        ),
        average_resolution_hours=round(sum(durations) / len(durations), 2) if durations else None,
        average_resolution_sample_count=len(durations),
        closure_rate=round(len(closed) / len(selected), 4) if selected else 0.0,
        closure_rate_sample_count=len(selected),
        trend=trend,
    )


@router.get("/risks", response_model=RiskWarningPage)
def risk_list(
    kind: RiskKind | None = None,
    severity: str | None = Query(default=None, pattern="^(low|medium|high)$"),
    status: str | None = Query(
        default=None, pattern="^(pending_confirmation|processing|closed)$"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    as_of_date: date | None = None,
    db: Session = Depends(get_db),
) -> RiskWarningPage:
    warnings, earliest, latest = _collect_warnings(db)
    timezone = _shanghai(earliest)
    selected_date = _resolve_as_of(as_of_date, latest, timezone)
    filtered = [
        item
        for item in warnings
        if _local_date(item.occurred_at, timezone) == selected_date
        and (kind is None or item.kind == kind)
        and (severity is None or item.severity == severity)
        and (status is None or item.status == status)
    ]
    start = (page - 1) * page_size
    return RiskWarningPage(
        as_of_date=selected_date.isoformat(),
        data_latest_at=latest,
        items=filtered[start : start + page_size],
        page=page,
        page_size=page_size,
        total=len(filtered),
    )


@router.get("/risks/{warning_id}", response_model=RiskWarningOut)
def risk_detail(warning_id: str, db: Session = Depends(get_db)) -> RiskWarningOut:
    warnings, _, _ = _collect_warnings(db)
    warning = next((item for item in warnings if item.id == warning_id), None)
    if warning is None:
        raise HTTPException(status_code=404, detail="风险预警不存在")
    return warning
