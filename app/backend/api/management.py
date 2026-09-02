from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.backend.agent import ASSISTANCE_AGENT_NAME
from app.backend.agent.context import assemble_context
from app.backend.api.dependencies import require_customer_service
from app.backend.api.work_orders import work_order_detail
from app.backend.db import get_db
from app.backend.models import Conversation, Message, Order, Product, WorkOrder, utc_now
from app.backend.schemas import (
    AssistanceAnalysisOut,
    ConversationContextOut,
    ConversationManagementOut,
    ConversationManagementPage,
    ConversationOut,
    ManagementOrderOut,
    ManagementOrderPage,
    ManagementProductPage,
    ManagementSummaryOut,
    MessageSearchItem,
    MessageSearchPage,
    OrderOut,
    OrderUpdate,
    ProductOut,
    ProductUpdate,
)

router = APIRouter(
    prefix="/api/v1/management",
    tags=["management"],
    dependencies=[Depends(require_customer_service)],
)


@router.post(
    "/conversations/{conversation_id}/assistance",
    response_model=AssistanceAnalysisOut,
)
def conversation_assistance(
    conversation_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> AssistanceAnalysisOut:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    context = assemble_context(db, conversation)
    try:
        agent = request.app.state.agent_registry.get(ASSISTANCE_AGENT_NAME)
        return agent.run(context)
    except (LookupError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="接待辅助暂时不可用") from exc


def _order_out(db: Session, order: Order) -> ManagementOrderOut:
    work_order_id = db.scalar(
        select(WorkOrder.external_id).where(WorkOrder.order_external_id == order.external_id)
    )
    return ManagementOrderOut(
        **OrderOut.model_validate(order).model_dump(),
        work_order_external_id=work_order_id,
    )


@router.get("/summary", response_model=ManagementSummaryOut)
def management_summary(db: Session = Depends(get_db)) -> ManagementSummaryOut:
    type_counts = dict(
        db.execute(
            select(WorkOrder.ticket_type, func.count()).group_by(WorkOrder.ticket_type)
        ).all()
    )
    return ManagementSummaryOut(
        conversations=db.scalar(select(func.count()).select_from(Conversation)) or 0,
        orders=db.scalar(select(func.count()).select_from(Order)) or 0,
        products=db.scalar(select(func.count()).select_from(Product)) or 0,
        work_orders=db.scalar(select(func.count()).select_from(WorkOrder)) or 0,
        pending_work_orders=db.scalar(
            select(func.count()).select_from(WorkOrder).where(WorkOrder.status != "completed")
        )
        or 0,
        work_orders_by_type=type_counts,
    )


@router.get("/conversations", response_model=ConversationManagementPage)
def management_conversations(
    q: str | None = None,
    conversation_status: str | None = Query(default=None, alias="status"),
    ticket_type: str | None = None,
    has_work_order: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ConversationManagementPage:
    query = select(Conversation)
    if conversation_status:
        query = query.where(Conversation.status == conversation_status)
    if q:
        matching_order_conversations = select(Order.conversation_id).where(
            Order.external_id.contains(q)
        )
        matching_work_order_conversations = select(WorkOrder.conversation_id).where(
            WorkOrder.external_id.contains(q)
        )
        query = query.where(
            or_(
                Conversation.id.contains(q),
                Conversation.source_external_id.contains(q),
                Conversation.buyer_nickname.contains(q),
                Conversation.id.in_(matching_order_conversations),
                Conversation.id.in_(matching_work_order_conversations),
            )
        )
    if ticket_type:
        query = query.where(
            Conversation.id.in_(
                select(WorkOrder.conversation_id).where(WorkOrder.ticket_type == ticket_type)
            )
        )
    if has_work_order is True:
        query = query.where(Conversation.id.in_(select(WorkOrder.conversation_id)))
    elif has_work_order is False:
        query = query.where(Conversation.id.not_in(select(WorkOrder.conversation_id)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = list(
        db.scalars(
            query.order_by(Conversation.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    items = []
    for record in records:
        order = db.scalar(select(Order).where(Order.conversation_id == record.id))
        work_order = db.scalar(select(WorkOrder).where(WorkOrder.conversation_id == record.id))
        items.append(
            ConversationManagementOut(
                **ConversationOut.model_validate(record).model_dump(),
                order_external_id=order.external_id if order else None,
                work_order_external_id=work_order.external_id if work_order else None,
                work_order_type=work_order.ticket_type if work_order else None,
                work_order_status=work_order.status if work_order else None,
            )
        )
    return ConversationManagementPage(items=items, page=page, page_size=page_size, total=total)


@router.get("/conversations/{conversation_id}/context", response_model=ConversationContextOut)
def conversation_context(
    conversation_id: str, db: Session = Depends(get_db)
) -> ConversationContextOut:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    order = db.scalar(select(Order).where(Order.conversation_id == conversation.id))
    work_order = db.scalar(select(WorkOrder).where(WorkOrder.conversation_id == conversation.id))
    product = None
    if order and order.product_external_id:
        product = db.scalar(select(Product).where(Product.external_id == order.product_external_id))
    return ConversationContextOut(
        conversation=ConversationOut.model_validate(conversation),
        order=_order_out(db, order) if order else None,
        product=ProductOut.model_validate(product) if product else None,
        work_order=work_order_detail(db, work_order) if work_order else None,
    )


@router.get("/messages/search", response_model=MessageSearchPage)
def search_messages(
    q: str = Query(min_length=1, max_length=200),
    conversation_id: str | None = None,
    buyer_nickname: str | None = None,
    sender_role: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> MessageSearchPage:
    query = select(Message).join(Conversation).where(Message.content.contains(q))
    if conversation_id:
        query = query.where(Message.conversation_id == conversation_id)
    if buyer_nickname:
        query = query.where(Conversation.buyer_nickname.contains(buyer_nickname))
    if sender_role:
        query = query.where(Message.sender_role == sender_role)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = list(
        db.scalars(
            query.order_by(Message.created_at.desc(), Message.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    conversations = {
        item.id: item
        for item in db.scalars(
            select(Conversation).where(
                Conversation.id.in_({record.conversation_id for record in records})
            )
        )
    }
    return MessageSearchPage(
        items=[
            MessageSearchItem.model_validate(
                {
                    **{
                        column.name: getattr(record, column.name)
                        for column in record.__table__.columns
                    },
                    "buyer_nickname": conversations[record.conversation_id].buyer_nickname,
                    "conversation_source_external_id": conversations[
                        record.conversation_id
                    ].source_external_id,
                }
            )
            for record in records
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/orders", response_model=ManagementOrderPage)
def management_orders(
    q: str | None = None,
    order_status: str | None = Query(default=None, alias="status"),
    buyer_nickname: str | None = None,
    conversation_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ManagementOrderPage:
    query = select(Order)
    if q:
        query = query.where(
            or_(
                Order.external_id.contains(q),
                Order.product_name.contains(q),
                Order.logistics_no.contains(q),
            )
        )
    if order_status:
        query = query.where(Order.status == order_status)
    if buyer_nickname:
        query = query.where(Order.buyer_nickname.contains(buyer_nickname))
    if conversation_id:
        query = query.where(Order.conversation_id == conversation_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = list(
        db.scalars(
            query.order_by(Order.updated_at.desc(), Order.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return ManagementOrderPage(
        items=[_order_out(db, item) for item in records],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/orders/{external_id}", response_model=ManagementOrderOut)
def management_order(external_id: str, db: Session = Depends(get_db)) -> ManagementOrderOut:
    record = db.scalar(select(Order).where(Order.external_id == external_id))
    if record is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return _order_out(db, record)


@router.patch("/orders/{external_id}", response_model=ManagementOrderOut)
def update_order(
    external_id: str, payload: OrderUpdate, db: Session = Depends(get_db)
) -> ManagementOrderOut:
    record = db.scalar(select(Order).where(Order.external_id == external_id))
    if record is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(record, key, value)
    record.updated_at = utc_now()
    db.commit()
    db.refresh(record)
    return _order_out(db, record)


@router.get("/products", response_model=ManagementProductPage)
def management_products(
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ManagementProductPage:
    query = select(Product)
    if q:
        query = query.where(
            or_(Product.external_id.contains(q), Product.name.contains(q), Product.sku.contains(q))
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = list(
        db.scalars(
            query.order_by(Product.updated_at.desc(), Product.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return ManagementProductPage(
        items=[ProductOut.model_validate(item) for item in records],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/products/{external_id}", response_model=ProductOut)
def management_product(external_id: str, db: Session = Depends(get_db)) -> Product:
    record = db.scalar(select(Product).where(Product.external_id == external_id))
    if record is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    return record


@router.patch("/products/{external_id}", response_model=ProductOut)
def update_product(
    external_id: str, payload: ProductUpdate, db: Session = Depends(get_db)
) -> Product:
    record = db.scalar(select(Product).where(Product.external_id == external_id))
    if record is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(record, key, value)
    record.updated_at = utc_now()
    db.commit()
    db.refresh(record)
    return record
