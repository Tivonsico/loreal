from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.backend.api import risks
from app.backend.models import (
    AdverseReactionDetail,
    Conversation,
    Message,
    Order,
    ReturnDetail,
    WorkOrder,
    WorkOrderStatusLog,
)


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


def _dt(day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


def _seed_panorama(service_app) -> str:
    with service_app.state.session_factory() as db:
        selected = Conversation(
            id="panorama-selected",
            customer_id="customer-exact",
            buyer_nickname="林小满",
            title="敏感肌咨询",
            created_at=_dt(18),
            updated_at=_dt(19),
        )
        history = Conversation(
            id="panorama-history",
            customer_id="customer-exact",
            buyer_nickname="林小满",
            title="历史咨询",
            created_at=_dt(1),
            updated_at=_dt(1),
        )
        lookalike = Conversation(
            id="panorama-lookalike",
            customer_id="customer-other",
            buyer_nickname="林小满",
            title="同名不同人",
            created_at=_dt(19),
            updated_at=_dt(19),
        )
        db.add_all([selected, history, lookalike])
        db.add_all(
            [
                Message(
                    conversation_id=history.id,
                    sender_role="customer",
                    message_type="text",
                    content="想了解产品",
                    created_at=_dt(1, 1),
                ),
                Message(
                    conversation_id=selected.id,
                    sender_role="customer",
                    message_type="text",
                    content="使用后有点刺痛",
                    created_at=_dt(19, 1),
                ),
                Message(
                    conversation_id=lookalike.id,
                    sender_role="customer",
                    message_type="text",
                    content="不应被聚合",
                    created_at=_dt(19, 2),
                ),
            ]
        )
        db.add_all(
            [
                Order(
                    external_id="ORDER-P1",
                    customer_id="customer-exact",
                    buyer_nickname="林小满",
                    conversation_id=history.id,
                    status="paid",
                    total_amount=Decimal("480.00"),
                    product_name="修护面霜",
                    ordered_at=_dt(1),
                    extra={"province": "浙江省", "city": "杭州市", "street": "不得返回"},
                    created_at=_dt(1),
                    updated_at=_dt(1),
                ),
                Order(
                    external_id="ORDER-P2",
                    customer_id="customer-exact",
                    buyer_nickname="林小满",
                    conversation_id=selected.id,
                    status="paid",
                    total_amount=Decimal("800.00"),
                    product_name="精华液",
                    ordered_at=_dt(18),
                    extra={"province": "上海市", "city": "上海市", "phone": "不得返回"},
                    created_at=_dt(18),
                    updated_at=_dt(18),
                ),
                Order(
                    external_id="ORDER-OTHER",
                    customer_id="customer-other",
                    buyer_nickname="林小满",
                    conversation_id=lookalike.id,
                    status="paid",
                    total_amount=Decimal("9999.00"),
                    ordered_at=_dt(19),
                    extra={"province": "北京市", "city": "北京市"},
                    created_at=_dt(19),
                    updated_at=_dt(19),
                ),
            ]
        )
        work_order = WorkOrder(
            external_id="WO-P1",
            ticket_type="adverse_reaction",
            conversation_id=selected.id,
            order_external_id="ORDER-P2",
            customer_id="customer-exact",
            buyer_nickname="林小满",
            status="processing",
            assignee="客服-苏晴",
            opened_at=_dt(19, 2),
            created_at=_dt(19, 2),
            updated_at=_dt(19, 3),
        )
        db.add(work_order)
        db.flush()
        db.add(AdverseReactionDetail(work_order_id=work_order.id, skin_type="敏感肌"))
        db.add(
            WorkOrderStatusLog(
                work_order_id=work_order.id,
                from_status="pending",
                to_status="processing",
                note="已联系客户",
                actor="客服-苏晴",
                created_at=_dt(19, 3),
            )
        )
        db.commit()
    return selected.id


def test_customer_panorama_uses_exact_customer_and_auditable_bounded_facts(app_pair) -> None:
    _, service_app = app_pair
    with TestClient(service_app) as client:
        conversation_id = _seed_panorama(service_app)
        response = client.get(
            f"/api/v1/management/conversations/{conversation_id}/panorama"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["identity"] == {
            "customer_id": "customer-exact",
            "buyer_nickname": "林小满",
            "identity_basis": "exact_customer_id",
        }
        assert body["metrics"]["recorded_paid_amount"] == "1280.00"
        assert body["metrics"]["order_count"] == 2
        assert body["metrics"]["consultation_count_30d"] == 2
        assert body["metrics"]["after_sales_count"] == 1
        assert {(item["province"], item["city"]) for item in body["addresses"]} == {
            ("浙江省", "杭州市"),
            ("上海市", "上海市"),
        }
        assert "street" not in response.text and "phone" not in response.text
        assert "9999" not in response.text and "北京市" not in response.text
        assert {item["code"] for item in body["tags"]} >= {
            "repeat_buyer",
            "multi_region",
            "skin_type:敏感肌",
            "high_recorded_value",
        }
        assert all(
            item["derived"] and item["basis"] and item["source_refs"]
            for item in body["tags"]
        )
        assert body["service_trail_total"] == len(body["service_trail"])
        assert len(body["service_trail"]) <= 4
        assert "after_sale_return" not in response.text
        assert all(item["title"] and item["detail"] for item in body["service_trail"])
        trail_keys = [
            (
                item["occurred_at"],
                item["source_ref"]["source_type"],
                item["source_ref"]["source_id"],
            )
            for item in body["service_trail"]
        ]
        assert trail_keys == sorted(trail_keys)
        assert len(trail_keys) == len(set(trail_keys))
        assert response.json() == client.get(
            f"/api/v1/management/conversations/{conversation_id}/panorama"
        ).json() | {"snapshot": response.json()["snapshot"]}

        insight_response = client.post(
            f"/api/v1/management/conversations/{conversation_id}/panorama/analysis"
        )
        assert insight_response.status_code == 200
        insight = insight_response.json()
        assert insight["mode"] in {"offline", "online"}
        assert insight["intent"] == insight["assistance"]["intent"]
        assert insight["summary"] == insight["assistance"]["summary"]
        assert insight["sentiment"] in {"calm", "concerned"}
        assert insight["emotion_label"]
        assert 0 <= insight["sentiment_confidence"] <= 1
        assert insight["sentiment_reason"]
        assert insight["risk_level"] in {"low", "medium", "high"}
        assert insight["evidence_message_ids"]
        assert len(insight["journey_insights"]) == len(body["service_trail"])
        assert all(item["summary"] for item in insight["journey_insights"])


def _seed_risks(service_app) -> None:
    with service_app.state.session_factory() as db:
        first = Conversation(
            id="risk-first",
            customer_id="risk-customer",
            buyer_nickname="周雨彤",
            created_at=_dt(1),
            updated_at=_dt(1),
        )
        current = Conversation(
            id="risk-current",
            customer_id="risk-customer",
            buyer_nickname="周雨彤",
            created_at=_dt(18, 16, 30),
            updated_at=_dt(18, 22),
        )
        db.add_all([first, current])
        db.add_all(
            [
                Message(
                    conversation_id=first.id,
                    sender_role="customer",
                    message_type="text",
                    content="上次咨询",
                    created_at=_dt(1),
                ),
                Message(
                    conversation_id=current.id,
                    sender_role="customer",
                    message_type="text",
                    content="请帮我看一下",
                    created_at=_dt(18, 16, 30),
                ),
                Message(
                    conversation_id=current.id,
                    sender_role="customer",
                    message_type="text",
                    content="越来越刺痛，我要去平台投诉并公开曝光",
                    created_at=_dt(18, 17, 30),
                ),
                Message(
                    conversation_id=current.id,
                    sender_role="customer_service",
                    message_type="text",
                    content="已经为您升级处理",
                    created_at=_dt(18, 20, 30),
                ),
            ]
        )
        first_refund = WorkOrder(
            external_id="WO-R1",
            ticket_type="after_sale_return",
            conversation_id=first.id,
            customer_id="risk-customer",
            buyer_nickname="周雨彤",
            status="completed",
            opened_at=_dt(1),
            closed_at=_dt(2),
            created_at=_dt(1),
            updated_at=_dt(2),
        )
        second_refund = WorkOrder(
            external_id="WO-R2",
            ticket_type="after_sale_return",
            conversation_id=current.id,
            customer_id="risk-customer",
            buyer_nickname="周雨彤",
            status="processing",
            assignee="客服-苏晴",
            opened_at=_dt(18, 18, 30),
            created_at=_dt(18, 18, 30),
            updated_at=_dt(18, 22),
        )
        db.add_all([first_refund, second_refund])
        db.flush()
        db.add(ReturnDetail(work_order_id=second_refund.id, is_abnormal=True))
        db.add(
            WorkOrderStatusLog(
                work_order_id=second_refund.id,
                from_status="pending",
                to_status="processing",
                actor="客服-苏晴",
                created_at=_dt(18, 22),
            )
        )
        db.commit()


def test_risk_contracts_share_one_warning_collection_and_stable_evidence(app_pair) -> None:
    _, service_app = app_pair
    with TestClient(service_app) as client:
        _seed_risks(service_app)
        before = {}
        with service_app.state.session_factory() as db:
            for model in (Conversation, Message, Order, WorkOrder, WorkOrderStatusLog):
                before[model.__tablename__] = db.scalar(select(func.count()).select_from(model))

        overview = client.get(
            "/api/v1/management/risks/overview", params={"as_of_date": "2026-08-19"}
        )
        listing = client.get(
            "/api/v1/management/risks",
            params={"as_of_date": "2026-08-19", "page_size": 100},
        )
        assert overview.status_code == listing.status_code == 200
        overview_body = overview.json()
        list_body = listing.json()
        assert overview_body["rule_version"] == list_body["rule_version"] == "risk-v1"
        assert overview_body["timezone"] == "Asia/Shanghai"
        assert overview_body["as_of_date"] == list_body["as_of_date"] == "2026-08-19"
        assert overview_body["warning_count"] == list_body["total"] == len(list_body["items"])
        assert len(overview_body["trend"]) == 7
        assert [item["date"] for item in overview_body["trend"]] == [
            f"2026-08-{day:02d}" for day in range(13, 20)
        ]
        kinds = {item["kind"] for item in list_body["items"]}
        assert kinds == {
            "emotion_escalation",
            "repeat_contact",
            "repeat_refund",
            "public_complaint",
            "service_timeout",
        }
        assert all(
            item["derived"] and item["source_refs"] and item["evidence"]
            for item in list_body["items"]
        )
        abnormal_refund = next(
            item for item in list_body["items"] if item["kind"] == "repeat_refund"
        )
        assert abnormal_refund["severity"] == "high"
        assert abnormal_refund["status"] == "processing"
        assert abnormal_refund["assignee"] == "客服-苏晴"

        filtered = client.get(
            "/api/v1/management/risks",
            params={"as_of_date": "2026-08-19", "kind": "public_complaint"},
        ).json()
        assert filtered["total"] == 1
        warning_id = filtered["items"][0]["id"]
        detail = client.get(f"/api/v1/management/risks/{warning_id}")
        assert detail.status_code == 200
        assert detail.json() == filtered["items"][0]
        assert client.get(
            "/api/v1/management/risks",
            params={"as_of_date": "2026-08-19", "kind": "public_complaint"},
        ).json()["items"][0]["id"] == warning_id
        assert client.get("/api/v1/management/risks/rw_missing").status_code == 404

        with service_app.state.session_factory() as db:
            after = {
                model.__tablename__: db.scalar(select(func.count()).select_from(model))
                for model in (Conversation, Message, Order, WorkOrder, WorkOrderStatusLog)
            }
        assert after == before


def test_risk_empty_day_has_zero_denominators_and_default_uses_latest_shanghai_day(
    app_pair,
) -> None:
    _, service_app = app_pair
    with TestClient(service_app) as client:
        _seed_risks(service_app)
        default = client.get("/api/v1/management/risks/overview").json()
        assert default["as_of_date"] == "2026-08-19"
        empty = client.get(
            "/api/v1/management/risks/overview", params={"as_of_date": "2026-08-20"}
        ).json()
        assert empty["warning_count"] == 0
        assert empty["average_resolution_hours"] is None
        assert empty["average_resolution_sample_count"] == 0
        assert empty["closure_rate"] == 0.0
        assert empty["closure_rate_sample_count"] == 0


def test_risk_default_date_includes_empty_conversation_repeat_contact(app_pair) -> None:
    _, service_app = app_pair
    with TestClient(service_app) as client:
        with service_app.state.session_factory() as db:
            db.add_all(
                [
                    Conversation(
                        id="risk-empty-history",
                        customer_id="risk-empty-customer",
                        buyer_nickname="空消息客户",
                        created_at=_dt(18),
                        updated_at=_dt(18),
                    ),
                    Conversation(
                        id="risk-empty-current",
                        customer_id="risk-empty-customer",
                        buyer_nickname="空消息客户",
                        created_at=_dt(19),
                        updated_at=_dt(19),
                    ),
                ]
            )
            db.commit()
        overview = client.get("/api/v1/management/risks/overview").json()
        listing = client.get("/api/v1/management/risks").json()

    assert overview["as_of_date"] == listing["as_of_date"] == "2026-08-19"
    assert overview["warning_count"] == listing["total"] == 1
    assert listing["items"][0]["kind"] == "repeat_contact"
    assert listing["items"][0]["conversation_id"] == "risk-empty-current"


def test_risk_representative_work_order_is_stable_and_severity_checks_all_links() -> None:
    conversation = Conversation(
        id="risk-multi",
        customer_id="risk-customer",
        buyer_nickname="周雨彤",
        created_at=_dt(18),
        updated_at=_dt(19),
    )
    explicit = WorkOrder(
        id=1,
        external_id="WO-EXPLICIT",
        ticket_type="logistics",
        conversation_id=conversation.id,
        status="completed",
        assignee="客服-甲",
        closed_at=_dt(19, 1),
        created_at=_dt(18),
        updated_at=_dt(19, 1),
    )
    signaled = WorkOrder(
        id=2,
        external_id="WO-SIGNAL",
        ticket_type="after_sale_return",
        conversation_id=conversation.id,
        status="processing",
        assignee="客服-乙",
        opened_at=_dt(19),
        created_at=_dt(19),
        updated_at=_dt(19, 2),
    )
    signal_ids = (set(), {signaled.id}, set())

    def warning(candidates: list[WorkOrder]):
        representative = risks._representative_work_order(
            candidates,
            signal_ids,
            explicit.external_id,
        )
        return risks._build_warning(
            rule="public_complaint",
            occurred_at=_dt(19),
            customer_id=conversation.customer_id,
            buyer_nickname=conversation.buyer_nickname,
            primary_ref=risks._ref("message", 42),
            summary="稳定顺序测试",
            conversation=conversation,
            work_order=representative,
            evidence=[],
            evidence_message_ids=[42],
            logs_by_work_order={},
            elevated=risks._any_elevated(candidates, signal_ids),
        )

    forward = warning([explicit, signaled])
    reversed_order = warning([signaled, explicit])
    assert forward == reversed_order
    assert forward.work_order_external_id == explicit.external_id
    assert forward.status == "closed"
    assert forward.assignee == "客服-甲"
    assert forward.severity == "high"
    assert risks._representative_work_order([explicit, signaled], signal_ids) == signaled


def test_risk_timezone_missing_uses_modern_named_fallback_and_rejects_history(
    monkeypatch,
) -> None:
    def missing_zoneinfo(_name: str):
        raise ZoneInfoNotFoundError("forced missing tzdata")

    monkeypatch.setattr(risks, "ZoneInfo", missing_zoneinfo)
    modern = risks._shanghai(_dt(18, 16, 30))
    assert modern.tzname(None) == "Asia/Shanghai"
    assert modern.utcoffset(None) == timedelta(hours=8)
    assert risks._local_date(_dt(18, 16, 30), modern).isoformat() == "2026-08-19"
    with pytest.raises(HTTPException) as exc_info:
        risks._shanghai(datetime(1991, 12, 31, tzinfo=UTC))
    assert exc_info.value.status_code == 503


def test_customer_port_rejects_panorama_and_risk_routes(app_pair) -> None:
    customer_app, _ = app_pair
    with TestClient(customer_app) as client:
        assert (
            client.get("/api/v1/management/conversations/any/panorama").status_code == 403
        )
        assert client.get("/api/v1/management/risks/overview").status_code == 403
        assert client.get("/api/v1/management/risks").status_code == 403
        assert client.get("/api/v1/management/risks/rw_any").status_code == 403
