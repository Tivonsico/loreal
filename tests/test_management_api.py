from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


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
