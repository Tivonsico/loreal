from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.db import get_db
from app.backend.models import Conversation
from app.backend.schemas import ConversationCreate, ConversationOut

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db)) -> Conversation:
    conversation = Conversation(customer_id=payload.customer_id, title=payload.title)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    customer_id: str | None = None,
    conversation_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[Conversation]:
    query = select(Conversation)
    if customer_id:
        query = query.where(Conversation.customer_id == customer_id)
    if conversation_status:
        query = query.where(Conversation.status == conversation_status)
    query = query.order_by(Conversation.updated_at.desc()).limit(limit)
    return list(db.scalars(query))


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: str, db: Session = Depends(get_db)) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation
