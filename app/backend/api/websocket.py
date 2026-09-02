from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.backend.models import Conversation

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_events(websocket: WebSocket, conversation_id: str) -> None:
    app = websocket.app
    with app.state.session_factory() as db:
        exists = db.get(Conversation, conversation_id) is not None
    if not exists:
        await websocket.close(code=4404, reason="会话不存在")
        return

    manager = app.state.realtime
    await manager.connect(conversation_id, websocket)
    await websocket.send_json(
        {
            "event": "connection.ready",
            "data": {"conversation_id": conversation_id, "role": app.state.settings.role},
        }
    )
    try:
        while True:
            # The v0.1 socket is server-push. Incoming frames are accepted as heartbeats.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(conversation_id, websocket)
