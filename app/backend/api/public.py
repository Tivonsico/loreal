from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.db import get_db
from app.backend.models import Conversation, OfflinePaymentDetail, ReplacementDetail, WorkOrder
from app.backend.schemas import PublicAfterSalesOut

router = APIRouter(prefix="/api/v1/public", tags=["public-after-sales"])


def _public_record(db: Session, work_order: WorkOrder) -> PublicAfterSalesOut:
    replacement_tracking_no = None
    payment_amount = None
    payment_status = None
    if work_order.ticket_type == "replacement_exchange":
        detail = db.get(ReplacementDetail, work_order.id)
        replacement_tracking_no = detail.replacement_tracking_no if detail else None
    elif work_order.ticket_type == "offline_payment":
        detail = db.get(OfflinePaymentDetail, work_order.id)
        if detail:
            payment_status = detail.transfer_status
            if detail.transfer_status and "成功" in detail.transfer_status:
                payment_amount = detail.amount
    return PublicAfterSalesOut(
        external_id=work_order.external_id,
        ticket_type=work_order.ticket_type,
        status=work_order.status,
        updated_at=work_order.updated_at,
        replacement_tracking_no=replacement_tracking_no,
        confirmed_payment_amount=payment_amount,
        confirmed_payment_status=payment_status,
    )


@router.get("/customers/{customer_id}/after-sales", response_model=list[PublicAfterSalesOut])
def customer_after_sales(
    customer_id: str, db: Session = Depends(get_db)
) -> list[PublicAfterSalesOut]:
    records = list(
        db.scalars(
            select(WorkOrder)
            .where(WorkOrder.customer_id == customer_id)
            .order_by(WorkOrder.updated_at.desc())
        )
    )
    return [_public_record(db, item) for item in records]


@router.get(
    "/conversations/{conversation_id}/after-sales",
    response_model=PublicAfterSalesOut | None,
)
def conversation_after_sales(
    conversation_id: str, db: Session = Depends(get_db)
) -> PublicAfterSalesOut | None:
    if db.get(Conversation, conversation_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    record = db.scalar(select(WorkOrder).where(WorkOrder.conversation_id == conversation_id))
    return _public_record(db, record) if record else None
