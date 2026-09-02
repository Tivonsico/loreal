from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.api.dependencies import require_customer_service
from app.backend.db import get_db
from app.backend.models import (
    AdverseReactionDetail,
    Conversation,
    LogisticsDetail,
    OfflinePaymentDetail,
    Order,
    ReplacementDetail,
    ReturnDetail,
    WorkOrder,
    WorkOrderStatusLog,
    utc_now,
)
from app.backend.schemas import (
    WorkOrderCreate,
    WorkOrderDetailOut,
    WorkOrderOut,
    WorkOrderPage,
    WorkOrderStatusLogOut,
    WorkOrderStatusUpdate,
    WorkOrderType,
)

router = APIRouter(
    prefix="/api/v1/work-orders",
    tags=["work-orders"],
    dependencies=[Depends(require_customer_service)],
)
DETAIL_MODELS = {
    "replacement_exchange": ReplacementDetail,
    "offline_payment": OfflinePaymentDetail,
    "logistics": LogisticsDetail,
    "adverse_reaction": AdverseReactionDetail,
    "after_sale_return": ReturnDetail,
}
FORBIDDEN_ADVERSE_KEYS = {"medical_record", "病历", "phone", "手机号", "id_card", "身份证"}
ALLOWED_TRANSITIONS = {
    "pending": {"processing", "completed"},
    "processing": {"pending", "completed"},
    "completed": {"processing"},
}


def _model_values(record: Any) -> dict[str, Any]:
    if record is None:
        return {}
    return {
        column.name: getattr(record, column.name)
        for column in record.__table__.columns
        if column.name != "work_order_id"
    }


def work_order_detail(db: Session, record: WorkOrder) -> WorkOrderDetailOut:
    detail_model = DETAIL_MODELS[record.ticket_type]
    detail = db.get(detail_model, record.id)
    logs = list(
        db.scalars(
            select(WorkOrderStatusLog)
            .where(WorkOrderStatusLog.work_order_id == record.id)
            .order_by(WorkOrderStatusLog.id)
        )
    )
    return WorkOrderDetailOut(
        **WorkOrderOut.model_validate(record).model_dump(),
        detail=_model_values(detail),
        status_logs=[WorkOrderStatusLogOut.model_validate(item) for item in logs],
    )


def _validated_detail(ticket_type: str, detail: dict[str, Any]) -> dict[str, Any]:
    model = DETAIL_MODELS[ticket_type]
    allowed = {column.name for column in model.__table__.columns} - {"work_order_id"}
    unknown = set(detail) - allowed
    if unknown:
        raise HTTPException(status_code=422, detail=f"该工单类型不支持字段：{sorted(unknown)}")
    if ticket_type == "adverse_reaction" and FORBIDDEN_ADVERSE_KEYS & set(detail):
        raise HTTPException(status_code=422, detail="不良反应工单禁止保存病历或身份信息")
    return detail


@router.get("", response_model=WorkOrderPage)
def list_work_orders(
    ticket_type: WorkOrderType | None = None,
    work_order_status: str | None = Query(default=None, alias="status"),
    buyer_nickname: str | None = None,
    order_no: str | None = None,
    conversation_id: str | None = None,
    assignee: str | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> WorkOrderPage:
    query = select(WorkOrder)
    if ticket_type:
        query = query.where(WorkOrder.ticket_type == ticket_type)
    if work_order_status:
        query = query.where(WorkOrder.status == work_order_status)
    if buyer_nickname:
        query = query.where(WorkOrder.buyer_nickname.contains(buyer_nickname))
    if order_no:
        query = query.where(WorkOrder.order_external_id == order_no)
    if conversation_id:
        query = query.where(WorkOrder.conversation_id == conversation_id)
    if assignee:
        query = query.where(WorkOrder.assignee == assignee)
    if q:
        query = query.where(
            or_(
                WorkOrder.external_id.contains(q),
                WorkOrder.order_external_id.contains(q),
                WorkOrder.buyer_nickname.contains(q),
                WorkOrder.description.contains(q),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = list(
        db.scalars(
            query.order_by(WorkOrder.updated_at.desc(), WorkOrder.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return WorkOrderPage(
        items=[work_order_detail(db, item) for item in records],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{external_id}", response_model=WorkOrderDetailOut)
def get_work_order(external_id: str, db: Session = Depends(get_db)) -> WorkOrderDetailOut:
    record = db.scalar(select(WorkOrder).where(WorkOrder.external_id == external_id))
    if record is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    return work_order_detail(db, record)


@router.post("", response_model=WorkOrderDetailOut, status_code=status.HTTP_201_CREATED)
def create_work_order(
    payload: WorkOrderCreate, db: Session = Depends(get_db)
) -> WorkOrderDetailOut:
    if payload.conversation_id and db.get(Conversation, payload.conversation_id) is None:
        raise HTTPException(status_code=422, detail="关联会话不存在")
    if payload.order_external_id:
        order = db.scalar(select(Order).where(Order.external_id == payload.order_external_id))
        if order is None:
            raise HTTPException(status_code=422, detail="关联订单不存在")
    detail = _validated_detail(payload.ticket_type, payload.detail)
    values = payload.model_dump(exclude={"detail"})
    record = WorkOrder(**values)
    db.add(record)
    try:
        db.flush()
        db.add(DETAIL_MODELS[payload.ticket_type](work_order_id=record.id, **detail))
        db.add(
            WorkOrderStatusLog(
                work_order_id=record.id,
                from_status=None,
                to_status=record.status,
                note="创建工单",
                actor="customer_service",
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="工单号已存在，或该会话已有工单") from exc
    db.refresh(record)
    return work_order_detail(db, record)


@router.patch("/{external_id}/status", response_model=WorkOrderDetailOut)
def update_work_order_status(
    external_id: str,
    payload: WorkOrderStatusUpdate,
    db: Session = Depends(get_db),
) -> WorkOrderDetailOut:
    record = db.scalar(select(WorkOrder).where(WorkOrder.external_id == external_id))
    if record is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    if payload.status == record.status:
        raise HTTPException(status_code=409, detail="工单已经处于该状态")
    if payload.status not in ALLOWED_TRANSITIONS.get(record.status, set()):
        raise HTTPException(
            status_code=409, detail=f"不允许从 {record.status} 变为 {payload.status}"
        )
    previous = record.status
    record.status = payload.status
    record.updated_at = utc_now()
    record.closed_at = utc_now() if payload.status == "completed" else None
    db.add(
        WorkOrderStatusLog(
            work_order_id=record.id,
            from_status=previous,
            to_status=payload.status,
            note=payload.note,
            actor="customer_service",
        )
    )
    db.commit()
    db.refresh(record)
    return work_order_detail(db, record)
