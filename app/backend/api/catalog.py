from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.db import get_db
from app.backend.models import Conversation, Order, Product
from app.backend.schemas import (
    ImportOrdersRequest,
    ImportProductsRequest,
    ImportResult,
    OrderInput,
    OrderOut,
    ProductInput,
    ProductOut,
)

router = APIRouter(prefix="/api/v1", tags=["catalog"])


def _product_values(payload: ProductInput) -> dict:
    return payload.model_dump()


def _order_values(payload: OrderInput) -> dict:
    return payload.model_dump()


def _validate_order_references(payload: OrderInput, db: Session) -> None:
    if payload.product_external_id:
        product = db.scalar(
            select(Product).where(Product.external_id == payload.product_external_id)
        )
        if product is None:
            raise HTTPException(
                status_code=422,
                detail=f"商品不存在: {payload.product_external_id}",
            )
    if payload.conversation_id and db.get(Conversation, payload.conversation_id) is None:
        raise HTTPException(status_code=422, detail=f"会话不存在: {payload.conversation_id}")


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductInput, db: Session = Depends(get_db)) -> Product:
    product = Product(**_product_values(payload))
    db.add(product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="商品 external_id 已存在") from exc
    db.refresh(product)
    return product


@router.get("/products", response_model=list[ProductOut])
def list_products(
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[Product]:
    query = select(Product)
    if q:
        query = query.where(Product.name.contains(q) | Product.external_id.contains(q))
    return list(db.scalars(query.order_by(Product.id).limit(limit)))


@router.post("/products/import", response_model=ImportResult)
def import_products(payload: ImportProductsRequest, db: Session = Depends(get_db)) -> ImportResult:
    created = 0
    updated = 0
    for item in payload.items:
        product = db.scalar(select(Product).where(Product.external_id == item.external_id))
        if product is None:
            db.add(Product(**_product_values(item)))
            created += 1
        else:
            for key, value in _product_values(item).items():
                setattr(product, key, value)
            product.updated_at = datetime.now(UTC)
            updated += 1
    db.commit()
    return ImportResult(created=created, updated=updated)


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderInput, db: Session = Depends(get_db)) -> Order:
    _validate_order_references(payload, db)
    order = Order(**_order_values(payload))
    db.add(order)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="订单 external_id 已存在") from exc
    db.refresh(order)
    return order


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    customer_id: str | None = None,
    order_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[Order]:
    query = select(Order)
    if customer_id:
        query = query.where(Order.customer_id == customer_id)
    if order_status:
        query = query.where(Order.status == order_status)
    return list(db.scalars(query.order_by(Order.id.desc()).limit(limit)))


@router.post("/orders/import", response_model=ImportResult)
def import_orders(payload: ImportOrdersRequest, db: Session = Depends(get_db)) -> ImportResult:
    for item in payload.items:
        _validate_order_references(item, db)

    created = 0
    updated = 0
    for item in payload.items:
        order = db.scalar(select(Order).where(Order.external_id == item.external_id))
        if order is None:
            db.add(Order(**_order_values(item)))
            created += 1
        else:
            for key, value in _order_values(item).items():
                setattr(order, key, value)
            order.updated_at = datetime.now(UTC)
            updated += 1
    db.commit()
    return ImportResult(created=created, updated=updated)
