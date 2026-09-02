from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend.agent.context import assemble_context
from app.backend.agent.openai_compatible_provider import EmotionBatchAdvice
from app.backend.api.dependencies import require_customer_service
from app.backend.db import get_db
from app.backend.models import (
    Conversation,
    ConversationEmotionAnalysis,
    EmotionAnalysisRun,
    WorkOrder,
    utc_now,
)
from app.backend.schemas import (
    EmotionAnalysisListItemOut,
    EmotionAnalysisPageOut,
    EmotionAnalysisResultOut,
    EmotionAnalysisRunOut,
    EmotionDashboardOut,
    EmotionTrendPointOut,
)

ANALYSIS_KIND = "conversation-emotion-v1"
PROMPT_VERSION = "emotion-v1"
AGENT_VERSION = "emotion-batch-v1"

router = APIRouter(
    prefix="/api/v1/management/emotion-analysis",
    tags=["management-emotion-analysis"],
    dependencies=[Depends(require_customer_service)],
)


class EmotionAnalysisAuthenticationError(RuntimeError):
    pass


def _run_out(run: EmotionAnalysisRun) -> EmotionAnalysisRunOut:
    return EmotionAnalysisRunOut.model_validate(run, from_attributes=True)


def _classify_isolated(
    provider: Any, contexts: list[dict[str, Any]]
) -> tuple[list[Any], list[str]]:
    try:
        return provider.classify_emotions(contexts), []
    except Exception as exc:
        if "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
            raise EmotionAnalysisAuthenticationError(str(exc)) from exc
        if len(contexts) == 1:
            conversation_id = contexts[0]["conversation"]["id"]
            return [], [f"{conversation_id}:{exc}"]
        middle = len(contexts) // 2
        left, left_errors = _classify_isolated(provider, contexts[:middle])
        right, right_errors = _classify_isolated(provider, contexts[middle:])
        return left + right, left_errors + right_errors


def _persist_completed_batch(
    app: Any,
    run_id: str,
    chunk: list[tuple[dict[str, Any], str]],
    items: list[EmotionBatchAdvice],
    errors: list[str],
    provider: Any,
) -> None:
    """Commit one completed network batch and its progress in a short transaction."""
    success_by_id = {item.conversation_id: item for item in items}
    error_by_id = {
        error.split(":", 1)[0]: error.split(":", 1)[1]
        for error in errors
        if ":" in error
    }
    batch_succeeded = 0
    batch_failed = 0
    with app.state.session_factory() as db:
        for context, fingerprint in chunk:
            conversation_id = context["conversation"]["id"]
            item = success_by_id.get(conversation_id)
            cache = db.scalar(
                select(ConversationEmotionAnalysis).where(
                    ConversationEmotionAnalysis.conversation_id == conversation_id,
                    ConversationEmotionAnalysis.analysis_kind == ANALYSIS_KIND,
                )
            )
            if cache is None:
                cache = ConversationEmotionAnalysis(
                    conversation_id=conversation_id,
                    analysis_kind=ANALYSIS_KIND,
                    content_fingerprint=fingerprint,
                )
                db.add(cache)
            cache.attempts = (cache.attempts or 0) + 1
            cache.prompt_version = PROMPT_VERSION
            cache.agent_version = AGENT_VERSION
            cache.model_name = provider.model_name
            cache.updated_at = utc_now()
            if item is not None:
                conversation = db.get(Conversation, conversation_id)
                current = assemble_context(db, conversation) if conversation else None
                if current is None or current["snapshot"]["fingerprint"] != fingerprint:
                    cache.status = "stale"
                    cache.error = "分析期间会话已更新"
                    batch_failed += 1
                else:
                    cache.content_fingerprint = fingerprint
                    cache.status = "succeeded"
                    cache.result = item.model_dump()
                    cache.error = None
                    cache.analyzed_at = utc_now()
                    batch_succeeded += 1
            else:
                cache.status = "failed"
                cache.error = error_by_id.get(conversation_id, "模型未返回该会话结果")[:1000]
                batch_failed += 1
        run = db.get(EmotionAnalysisRun, run_id)
        if run is not None:
            run.succeeded_count += batch_succeeded
            run.failed_count += batch_failed
            run.processed_count += batch_succeeded + batch_failed
        db.commit()


def _execute_run(app: Any, run_id: str) -> None:
    session_factory = app.state.session_factory
    settings = app.state.settings
    provider = app.state.emotion_provider
    with session_factory() as db:
        run = db.get(EmotionAnalysisRun, run_id)
        if run is None:
            return
        run.status = "running"
        run.started_at = utc_now()
        conversations = list(db.scalars(select(Conversation).order_by(Conversation.updated_at)))
        pending: list[tuple[dict[str, Any], str]] = []
        for conversation in conversations:
            context = assemble_context(db, conversation)
            fingerprint = context["snapshot"]["fingerprint"]
            cached = db.scalar(
                select(ConversationEmotionAnalysis).where(
                    ConversationEmotionAnalysis.conversation_id == conversation.id,
                    ConversationEmotionAnalysis.analysis_kind == ANALYSIS_KIND,
                )
            )
            if (
                cached is not None
                and cached.status == "succeeded"
                and cached.content_fingerprint == fingerprint
                and cached.prompt_version == PROMPT_VERSION
                and cached.agent_version == AGENT_VERSION
                and cached.model_name == (provider.model_name if provider else None)
            ):
                continue
            if context["chat"]["messages"]:
                pending.append((context, fingerprint))
        run.total_count = len(pending)
        db.commit()

    if not pending:
        with session_factory() as db:
            run = db.get(EmotionAnalysisRun, run_id)
            if run:
                run.status = "completed"
                run.finished_at = utc_now()
                db.commit()
        return
    if provider is None:
        with session_factory() as db:
            run = db.get(EmotionAnalysisRun, run_id)
            if run:
                run.status = "failed"
                run.failed_count = run.total_count
                run.processed_count = run.total_count
                run.error = "未配置在线情绪分析模型"
                run.finished_at = utc_now()
                db.commit()
        return

    batch_size = settings.emotion_batch_size
    chunks = [pending[index : index + batch_size] for index in range(0, len(pending), batch_size)]
    authentication_error: str | None = None
    with ThreadPoolExecutor(max_workers=settings.emotion_batch_workers) as executor:
        futures = {
            executor.submit(_classify_isolated, provider, [item[0] for item in chunk]): chunk
            for chunk in chunks
        }
        for future in as_completed(futures):
            try:
                items, batch_errors = future.result()
            except EmotionAnalysisAuthenticationError as exc:
                authentication_error = str(exc)
                for pending_future in futures:
                    pending_future.cancel()
                break
            _persist_completed_batch(
                app,
                run_id,
                futures[future],
                items,
                batch_errors,
                provider,
            )

    if authentication_error:
        with session_factory() as db:
            run = db.get(EmotionAnalysisRun, run_id)
            if run:
                run.status = "failed"
                run.error = authentication_error[:1000]
                run.finished_at = utc_now()
                db.commit()
        return

    with session_factory() as db:
        run = db.get(EmotionAnalysisRun, run_id)
        if run:
            run.status = "partial_failed" if run.failed_count else "completed"
            run.error = f"{run.failed_count} 个会话分析失败" if run.failed_count else None
            run.finished_at = utc_now()
        db.commit()


@router.post("/runs", response_model=EmotionAnalysisRunOut, status_code=202)
def create_emotion_run(request: Request, db: Session = Depends(get_db)) -> EmotionAnalysisRunOut:
    active = db.scalar(
        select(EmotionAnalysisRun)
        .where(EmotionAnalysisRun.status.in_(("queued", "running")))
        .order_by(EmotionAnalysisRun.created_at.desc())
    )
    if active:
        return _run_out(active)
    provider = request.app.state.emotion_provider
    run = EmotionAnalysisRun(
        status="queued",
        analysis_kind=ANALYSIS_KIND,
        model_name=provider.model_name if provider else None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    thread = threading.Thread(target=_execute_run, args=(request.app, run.id), daemon=True)
    thread.start()
    return _run_out(run)


@router.get("/runs/current", response_model=EmotionAnalysisRunOut)
def current_emotion_run(db: Session = Depends(get_db)) -> EmotionAnalysisRunOut:
    run = db.scalar(select(EmotionAnalysisRun).order_by(EmotionAnalysisRun.created_at.desc()))
    if run is None:
        raise HTTPException(status_code=404, detail="尚未运行情绪分析")
    return _run_out(run)


@router.get("/overview", response_model=EmotionDashboardOut)
def emotion_overview(db: Session = Depends(get_db)) -> EmotionDashboardOut:
    caches = list(db.scalars(select(ConversationEmotionAnalysis)))
    results = [item.result for item in caches if item.result]
    warning_count = sum(item.get("risk_type") != "none" for item in results)
    high_count = sum(item.get("severity") == "high" for item in results)
    failure_count = sum(item.status == "failed" for item in caches)
    today = datetime.now(UTC).date()
    trend = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        count = sum(
            item.analyzed_at is not None
            and item.analyzed_at.date() == day
            and item.result.get("risk_type") != "none"
            for item in caches
        )
        trend.append(EmotionTrendPointOut(date=day.isoformat(), warning_count=count))
    total_work_orders = db.scalar(select(func.count()).select_from(WorkOrder)) or 0
    closed = (
        db.scalar(
            select(func.count()).select_from(WorkOrder).where(WorkOrder.status == "completed")
        )
        or 0
    )
    return EmotionDashboardOut(
        warning_count=warning_count,
        high_risk_count=high_count,
        analyzed_count=len(results),
        failure_count=failure_count,
        closure_rate=closed / total_work_orders if total_work_orders else 0,
        trend=trend,
    )


def _list_item(cache: ConversationEmotionAnalysis, conversation: Conversation, db: Session):
    result = EmotionAnalysisResultOut.model_validate(cache.result)
    assignee = db.scalar(
        select(WorkOrder.assignee).where(WorkOrder.conversation_id == conversation.id)
    )
    return EmotionAnalysisListItemOut(
        **result.model_dump(),
        buyer_nickname=conversation.buyer_nickname,
        updated_at=conversation.updated_at,
        analyzed_at=cache.analyzed_at,
        status=cache.status,
        assignee=assignee,
    )


@router.get("", response_model=EmotionAnalysisPageOut)
def emotion_list(
    risk_type: str | None = None,
    severity: str | None = None,
    emotion: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> EmotionAnalysisPageOut:
    caches = [item for item in db.scalars(select(ConversationEmotionAnalysis)) if item.result]
    if risk_type:
        caches = [item for item in caches if item.result.get("risk_type") == risk_type]
    if severity:
        caches = [item for item in caches if item.result.get("severity") == severity]
    if emotion:
        caches = [item for item in caches if item.result.get("emotion") == emotion]
    caches.sort(key=lambda item: item.analyzed_at or item.updated_at, reverse=True)
    total = len(caches)
    selected = caches[(page - 1) * page_size : page * page_size]
    items = []
    for cache in selected:
        conversation = db.get(Conversation, cache.conversation_id)
        if conversation:
            items.append(_list_item(cache, conversation, db))
    return EmotionAnalysisPageOut(items=items, page=page, page_size=page_size, total=total)


@router.get("/{conversation_id}", response_model=EmotionAnalysisListItemOut)
def emotion_detail(
    conversation_id: str, db: Session = Depends(get_db)
) -> EmotionAnalysisListItemOut:
    cache = db.scalar(
        select(ConversationEmotionAnalysis).where(
            ConversationEmotionAnalysis.conversation_id == conversation_id
        )
    )
    conversation = db.get(Conversation, conversation_id)
    if cache is None or not cache.result or conversation is None:
        raise HTTPException(status_code=404, detail="情绪分析结果不存在")
    return _list_item(cache, conversation, db)
