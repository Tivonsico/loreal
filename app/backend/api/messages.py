from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.db import get_db
from app.backend.media import store_upload
from app.backend.models import Conversation, Message, RealtimeEvent, utc_now
from app.backend.schemas import MessageOut, MessagePage, TextMessageCreate

router = APIRouter(prefix="/api/v1/conversations/{conversation_id}/messages", tags=["messages"])
MEDIA_TYPES = {"image", "audio", "video", "file"}


def _require_conversation(conversation_id: str, db: Session) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


def _save_message(db: Session, conversation: Conversation, **values) -> Message:
    message = Message(conversation_id=conversation.id, **values)
    db.add(message)
    db.flush()
    db.add(RealtimeEvent(conversation_id=conversation.id, message_id=message.id))
    conversation.updated_at = utc_now()
    db.commit()
    db.refresh(message)
    return message


@router.get("", response_model=MessagePage)
def list_messages(
    conversation_id: str,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> MessagePage:
    _require_conversation(conversation_id, db)
    query = select(Message).where(Message.conversation_id == conversation_id)
    if before_id is not None:
        query = query.where(Message.id < before_id)
    newest_first = list(db.scalars(query.order_by(Message.id.desc()).limit(limit + 1)))
    has_more = len(newest_first) > limit
    selected = newest_first[:limit]
    selected.reverse()
    return MessagePage(
        items=[MessageOut.model_validate(item) for item in selected],
        next_before_id=selected[0].id if has_more and selected else None,
    )


@router.post("/text", response_model=MessageOut, status_code=201)
def send_text(
    conversation_id: str,
    payload: TextMessageCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> Message:
    conversation = _require_conversation(conversation_id, db)
    return _save_message(
        db,
        conversation,
        sender_role=request.app.state.settings.role,
        message_type="text",
        content=payload.content,
    )


@router.post("/media", response_model=MessageOut, status_code=201)
async def send_media(
    conversation_id: str,
    request: Request,
    message_type: str = Form(...),
    caption: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Message:
    conversation = _require_conversation(conversation_id, db)
    if message_type not in MEDIA_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"message_type 必须是 {sorted(MEDIA_TYPES)} 之一",
        )
    settings = request.app.state.settings
    stored = await store_upload(
        file,
        declared_type=message_type,
        media_dir=settings.media_dir,
        max_bytes=settings.max_upload_bytes,
    )
    try:
        return _save_message(
            db,
            conversation,
            sender_role=settings.role,
            message_type=message_type,
            content=caption.strip() if caption and caption.strip() else None,
            media_url=stored.url,
            original_filename=stored.original_filename,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
        )
    except Exception:
        stored.path.unlink(missing_ok=True)
        raise
