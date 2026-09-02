from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from app.backend.agent.openai_compatible_provider import EmotionBatchAdvice
from app.backend.models import Conversation, Message, Order, WorkOrder


def _official_workbook() -> Path:
    matches = [
        path
        for path in (Path.home() / "Desktop").glob("*/*1*.xlsx")
        if not path.name.startswith("~$")
    ]
    if not matches:
        pytest.skip("正式比赛工作簿不在当前环境")
    return matches[0]


def _import_official_workbook(client: TestClient) -> None:
    workbook = _official_workbook()
    with workbook.open("rb") as source:
        preview = client.post(
            "/api/v1/imports/workbook/preview",
            files={
                "file": (
                    workbook.name,
                    source,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert preview.status_code == 201
    assert preview.json()["can_commit"] is True
    commit = client.post(f"/api/v1/imports/workbook/{preview.json()['batch_id']}/commit")
    assert commit.status_code == 200


def test_management_views_share_exact_records_and_support_status_flow(app_pair) -> None:
    _, service_app = app_pair
    with TestClient(service_app) as client:
        _import_official_workbook(client)

        summary = client.get("/api/v1/management/summary")
        assert summary.status_code == 200
        summary_body = summary.json()
        assert summary_body["conversations"] == 138
        assert summary_body["orders"] == 113
        assert summary_body["products"] == 20
        assert summary_body["work_orders"] == 80

        conversations = client.get(
            "/api/v1/management/conversations", params={"page_size": 200}
        ).json()
        linked = next(
            item
            for item in conversations["items"]
            if item["order_external_id"] and item["work_order_external_id"]
        )
        context = client.get(f"/api/v1/management/conversations/{linked['id']}/context")
        assert context.status_code == 200
        assert context.json()["order"]["external_id"] == linked["order_external_id"]
        assert context.json()["work_order"]["external_id"] == linked["work_order_external_id"]

        order = client.get(f"/api/v1/management/orders/{linked['order_external_id']}")
        assert order.status_code == 200
        assert order.json()["work_order_external_id"] == linked["work_order_external_id"]
        filtered_orders = client.get(
            "/api/v1/management/orders", params={"q": linked["order_external_id"]}
        ).json()
        assert filtered_orders["total"] == 1

        pending = client.get("/api/v1/work-orders", params={"status": "pending"}).json()
        assert pending["total"] > 0
        ticket = pending["items"][0]
        changed = client.patch(
            f"/api/v1/work-orders/{ticket['external_id']}/status",
            json={"status": "processing", "note": "已联系仓库核查"},
        )
        assert changed.status_code == 200
        assert changed.json()["status"] == "processing"
        assert changed.json()["status_logs"][-1]["note"] == "已联系仓库核查"

        messages = client.get(
            f"/api/v1/conversations/{linked['id']}/messages", params={"limit": 200}
        ).json()["items"]
        search_term = next(item["content"] for item in messages if item["content"])[:20]
        search = client.get("/api/v1/management/messages/search", params={"q": search_term})
        assert search.status_code == 200
        assert any(item["conversation_id"] == linked["id"] for item in search.json()["items"])


def test_customer_port_rejects_internal_management_and_work_order_routes(app_pair) -> None:
    customer_app, _ = app_pair
    with TestClient(customer_app) as client:
        assert client.get("/api/v1/management/summary").status_code == 403
        assert client.get("/api/v1/work-orders").status_code == 403
        assert (
            client.post(
                "/api/v1/work-orders",
                json={
                    "external_id": "WO-FORBIDDEN",
                    "ticket_type": "logistics",
                    "status": "pending",
                    "detail": {},
                },
            ).status_code
            == 403
        )


def _wait_for_emotion_run(client: TestClient) -> dict:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        body = client.get("/api/v1/management/emotion-analysis/runs/current").json()
        if body["status"] not in {"queued", "running"}:
            return body
        sleep(0.02)
    raise AssertionError("情绪分析运行未在时限内完成")


def test_panorama_and_incremental_emotion_analysis_are_exact_and_isolated(app_pair) -> None:
    customer_app, service_app = app_pair
    with TestClient(service_app) as client:
        with service_app.state.session_factory() as db:
            db.add_all(
                [
                    Conversation(
                        id="emotion-good",
                        customer_id="exact-customer",
                        buyer_nickname="林小满",
                        title="退款咨询",
                    ),
                    Conversation(
                        id="emotion-bad",
                        customer_id="exact-customer",
                        buyer_nickname="林小满",
                        title="物流咨询",
                    ),
                    Conversation(
                        id="other-customer",
                        customer_id="other",
                        buyer_nickname="其他客户",
                    ),
                ]
            )
            db.flush()
            db.add_all(
                [
                    Message(
                        conversation_id="emotion-good",
                        sender_role="customer",
                        message_type="text",
                        content="退款怎么还没到，我很着急",
                    ),
                    Message(
                        conversation_id="emotion-bad",
                        sender_role="customer",
                        message_type="text",
                        content="物流什么时候到",
                    ),
                ]
            )
            db.add_all(
                [
                    Order(
                        external_id="ORDER-EMOTION-1",
                        customer_id="exact-customer",
                        conversation_id="emotion-good",
                        status="paid",
                        quantity=1,
                        total_amount=128,
                        extra={"province": "浙江", "city": "杭州", "address": "不得返回"},
                    ),
                    Order(
                        external_id="ORDER-EMOTION-2",
                        customer_id="exact-customer",
                        conversation_id="emotion-bad",
                        status="paid",
                        quantity=1,
                        total_amount=200,
                    ),
                    Order(
                        external_id="ORDER-OTHER",
                        customer_id="other",
                        conversation_id="other-customer",
                        status="paid",
                        quantity=1,
                        total_amount=999,
                    ),
                ]
            )
            db.add(
                WorkOrder(
                    external_id="WO-EMOTION",
                    ticket_type="offline_payment",
                    conversation_id="emotion-good",
                    customer_id="exact-customer",
                    status="processing",
                    assignee="客服-苏晴",
                    description="退款未到账",
                )
            )
            db.commit()

        panorama = client.get(
            "/api/v1/management/conversations/emotion-good/panorama"
        )
        assert panorama.status_code == 200
        panorama_body = panorama.json()
        assert panorama_body["recorded_paid_amount"] == "328.00"
        assert panorama_body["order_count"] == 2
        assert panorama_body["after_sales_count"] == 1
        assert panorama_body["region"] == "浙江 杭州"
        assert len(panorama_body["service_trail"]) <= 4
        assert "address" not in str(panorama_body)

        class PartlyBrokenProvider:
            model_name = "test-emotion-model"

            def __init__(self):
                self.calls: list[list[str]] = []

            def classify_emotions(self, contexts):
                ids = [item["conversation"]["id"] for item in contexts]
                self.calls.append(ids)
                if "emotion-bad" in ids:
                    raise RuntimeError("bad conversation")
                return [
                    EmotionBatchAdvice(
                        conversation_id=item["conversation"]["id"],
                        emotion="anxious",
                        confidence=0.93,
                        risk_type="emotion_escalation",
                        severity="high",
                        summary="客户担心退款迟迟未到账。",
                        evidence_message_ids=[item["chat"]["messages"][0]["id"]],
                    )
                    for item in contexts
                ]

        provider = PartlyBrokenProvider()
        service_app.state.emotion_provider = provider
        started = client.post("/api/v1/management/emotion-analysis/runs")
        assert started.status_code == 202
        assert started.json()["status"] in {"queued", "running"}
        finished = _wait_for_emotion_run(client)
        assert finished["status"] == "partial_failed"
        assert finished["succeeded_count"] == 1
        assert finished["failed_count"] == 1

        listing = client.get("/api/v1/management/emotion-analysis").json()
        assert listing["total"] == 1
        assert listing["items"][0]["conversation_id"] == "emotion-good"
        assert listing["items"][0]["assignee"] == "客服-苏晴"
        assert client.get(
            "/api/v1/management/emotion-analysis/emotion-good"
        ).status_code == 200
        overview = client.get("/api/v1/management/emotion-analysis/overview").json()
        assert overview["analyzed_count"] == 1
        assert overview["high_risk_count"] == 1
        assert overview["failure_count"] == 1

        provider.calls.clear()
        client.post("/api/v1/management/emotion-analysis/runs")
        _wait_for_emotion_run(client)
        assert provider.calls == [["emotion-bad"]]

    with TestClient(customer_app) as customer:
        assert customer.get(
            "/api/v1/management/conversations/emotion-good/panorama"
        ).status_code == 403
        assert customer.post(
            "/api/v1/management/emotion-analysis/runs"
        ).status_code == 403


def test_emotion_run_persists_progress_before_all_futures_finish(app_pair) -> None:
    _, service_app = app_pair
    release_slow_batch = Event()

    class ObservableProvider:
        model_name = "observable-model"

        def classify_emotions(self, contexts):
            conversation_id = contexts[0]["conversation"]["id"]
            if conversation_id == "progress-slow":
                release_slow_batch.wait(timeout=2)
            message_id = contexts[0]["chat"]["messages"][0]["id"]
            return [
                EmotionBatchAdvice(
                    conversation_id=conversation_id,
                    emotion="neutral",
                    confidence=0.8,
                    summary="客户正在进行普通咨询。",
                    evidence_message_ids=[message_id],
                )
            ]

    with TestClient(service_app) as client:
        with service_app.state.session_factory() as db:
            for conversation_id in ("progress-fast", "progress-slow"):
                db.add(Conversation(id=conversation_id, customer_id=conversation_id))
                db.flush()
                db.add(
                    Message(
                        conversation_id=conversation_id,
                        sender_role="customer",
                        message_type="text",
                        content="查询订单",
                    )
                )
            db.commit()
        service_app.state.settings = replace(
            service_app.state.settings,
            emotion_batch_size=1,
            emotion_batch_workers=2,
        )
        service_app.state.emotion_provider = ObservableProvider()
        client.post("/api/v1/management/emotion-analysis/runs")

        deadline = monotonic() + 2
        observed = None
        while monotonic() < deadline:
            current = client.get(
                "/api/v1/management/emotion-analysis/runs/current"
            ).json()
            if current["status"] == "running" and current["processed_count"] == 1:
                observed = current
                break
            sleep(0.02)
        assert observed is not None
        assert observed["succeeded_count"] == 1
        assert client.get("/api/v1/management/emotion-analysis").json()["total"] == 1

        release_slow_batch.set()
        finished = _wait_for_emotion_run(client)
        assert finished["status"] == "completed"
        assert finished["processed_count"] == 2
