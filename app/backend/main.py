from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.backend.agent import create_agent_registry
from app.backend.agent.openai_compatible_provider import OpenAICompatibleChatProvider
from app.backend.api import (
    catalog,
    conversations,
    customer_panorama,
    emotion_analysis,
    imports,
    management,
    messages,
    public,
    websocket,
    work_orders,
)
from app.backend.config import Settings
from app.backend.db import create_database, upgrade_database
from app.backend.realtime import RealtimeManager

SERVICE_UI_BUILD = "20260903-3"
HTML_NO_CACHE_HEADERS = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    engine, session_factory = create_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        upgrade_database(engine)
        # Preserve demo data created before the sender role was renamed.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE messages SET sender_role = 'customer_service' "
                    "WHERE sender_role = 'agent'"
                )
            )
        manager = RealtimeManager(session_factory, settings.poll_interval)
        app.state.realtime = manager
        await manager.start()
        try:
            yield
        finally:
            await manager.stop()
            engine.dispose()

    role_name = "Customer" if settings.role == "customer" else "Customer Service"
    app = FastAPI(
        title=f"美妆客服工作台 v0.2（{role_name} 入口）",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.agent_registry = create_agent_registry(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        json_mode=settings.llm_json_mode,
        reasoning_mode=settings.llm_reasoning_mode,
    )
    app.state.emotion_provider = (
        OpenAICompatibleChatProvider(
            settings.llm_api_key,
            settings.llm_base_url,
            settings.llm_model,
            settings.llm_timeout_seconds,
            settings.llm_json_mode,
            settings.llm_reasoning_mode,
        )
        if settings.llm_api_key
        else None
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory=frontend_dir / "static"), name="static")
    app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")
    app.include_router(conversations.router)
    app.include_router(catalog.router)
    app.include_router(messages.router)
    app.include_router(imports.router)
    app.include_router(management.router)
    app.include_router(customer_panorama.router)
    app.include_router(emotion_analysis.router)
    app.include_router(work_orders.router)
    app.include_router(public.router)
    app.include_router(websocket.router)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "role": settings.role, "version": "0.2.0"}

    @app.get("/", include_in_schema=False, response_class=FileResponse)
    def frontend() -> Response:
        if settings.role == "customer_service":
            return RedirectResponse(
                f"/workspace/chat?ui={SERVICE_UI_BUILD}",
                status_code=307,
                headers=HTML_NO_CACHE_HEADERS,
            )
        return FileResponse(
            frontend_dir / "customer.html",
            headers=HTML_NO_CACHE_HEADERS,
        )

    @app.get("/workspace/{section}", include_in_schema=False, response_class=FileResponse)
    def service_workspace(section: str, request: Request) -> Response:
        if settings.role != "customer_service" or section not in {
            "chat",
            "orders",
            "after-sales",
            "products",
            "risk",
        }:
            raise HTTPException(status_code=404, detail="页面不存在")
        if request.query_params.get("ui") != SERVICE_UI_BUILD:
            query = dict(request.query_params)
            query["ui"] = SERVICE_UI_BUILD
            return RedirectResponse(
                f"/workspace/{section}?{urlencode(query)}",
                status_code=307,
                headers=HTML_NO_CACHE_HEADERS,
            )
        return FileResponse(
            frontend_dir / "customer_service.html",
            headers=HTML_NO_CACHE_HEADERS,
        )

    return app


app = create_app()
