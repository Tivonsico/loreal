from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.backend.models import Message, RealtimeEvent
from app.backend.schemas import MessageOut


class RealtimeManager:
    def __init__(self, session_factory: sessionmaker[Session], poll_interval: float) -> None:
        self._session_factory = session_factory
        self._poll_interval = poll_interval
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._cursor = 0
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        with self._session_factory() as db:
            self._cursor = db.scalar(select(func.max(RealtimeEvent.id))) or 0
        self._stopping = False
        self._task = asyncio.create_task(self._poll(), name="realtime-event-poller")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def connect(self, conversation_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[conversation_id].add(websocket)

    def disconnect(self, conversation_id: str, websocket: WebSocket) -> None:
        sockets = self._connections.get(conversation_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._connections.pop(conversation_id, None)

    async def _poll(self) -> None:
        while not self._stopping:
            await self._dispatch_new_events()
            await asyncio.sleep(self._poll_interval)

    async def _dispatch_new_events(self) -> None:
        with self._session_factory() as db:
            events = list(
                db.scalars(
                    select(RealtimeEvent)
                    .where(RealtimeEvent.id > self._cursor)
                    .order_by(RealtimeEvent.id)
                    .limit(500)
                )
            )
            payloads: list[tuple[int, str, dict]] = []
            for event in events:
                message = db.get(Message, event.message_id)
                if message is not None:
                    payloads.append(
                        (
                            event.id,
                            event.conversation_id,
                            {
                                "event": "message.created",
                                "data": MessageOut.model_validate(message).model_dump(mode="json"),
                            },
                        )
                    )

        for event_id, conversation_id, payload in payloads:
            await self._broadcast(conversation_id, payload)
            self._cursor = max(self._cursor, event_id)

    async def _broadcast(self, conversation_id: str, payload: dict) -> None:
        dead: list[WebSocket] = []
        for websocket in tuple(self._connections.get(conversation_id, ())):
            try:
                await websocket.send_json(payload)
            except Exception:  # client disconnects are cleaned up on the next event
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(conversation_id, websocket)
