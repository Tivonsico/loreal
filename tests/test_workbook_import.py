from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.backend.db import upgrade_database
from app.backend.imports.workbook import commit_preview, create_preview
from app.backend.models import Conversation, Message, Order, RealtimeEvent, WorkOrder


def _official_workbook() -> Path:
    matches = [
        path
        for path in (Path.home() / "Desktop").glob("*/*1*.xlsx")
        if not path.name.startswith("~$")
    ]
    if not matches:
        pytest.skip("正式比赛工作簿不在当前环境")
    return matches[0]


def test_official_workbook_preview_commit_and_reimport_are_exact(tmp_path) -> None:
    source = _official_workbook()
    engine = create_engine(f"sqlite:///{tmp_path / 'workbook.db'}")
    upgrade_database(engine)

    with Session(engine) as db:
        batch = create_preview(db, source.name, source.read_bytes())
        assert batch.status == "ready"
        assert batch.summary["public"]["sheets"] == {"聊天记录": 998, "订单": 113}
        assert batch.summary["public"]["work_order_types"] == {
            "replacement_exchange": 24,
            "offline_payment": 13,
            "logistics": 15,
            "adverse_reaction": 10,
            "after_sale_return": 18,
        }

        result = commit_preview(db, batch)
        assert result["created"] == {
            "conversations": 138,
            "messages": 998,
            "orders": 113,
            "work_orders": 80,
            "products": 20,
        }
        assert db.scalar(select(func.count()).select_from(RealtimeEvent)) == 0
        assert (
            db.scalar(
                select(func.count()).select_from(Order).where(Order.payment_stage == "deposit")
            )
            == 3
        )

        repeat = create_preview(db, source.name, source.read_bytes())
        assert commit_preview(db, repeat)["created"] == {
            "conversations": 0,
            "messages": 0,
            "orders": 0,
            "work_orders": 0,
            "products": 0,
        }
        assert db.scalar(select(func.count()).select_from(Conversation)) == 138
        assert db.scalar(select(func.count()).select_from(Message)) == 998
        assert db.scalar(select(func.count()).select_from(Order)) == 113
        assert db.scalar(select(func.count()).select_from(WorkOrder)) == 80

    engine.dispose()


def _incomplete_workbook() -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "聊天记录"
    worksheet.append(["会话ID"])
    worksheet.append(["CONV-BAD"])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_invalid_preview_cannot_commit_and_writes_no_business_rows(app_pair) -> None:
    _, service_app = app_pair
    with TestClient(service_app) as client:
        preview = client.post(
            "/api/v1/imports/workbook/preview",
            files={
                "file": (
                    "bad.xlsx",
                    _incomplete_workbook(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert preview.status_code == 201
        body = preview.json()
        assert body["status"] == "invalid"
        assert body["can_commit"] is False
        assert body["error_count"] >= 7

        commit = client.post(f"/api/v1/imports/workbook/{body['batch_id']}/commit")
        assert commit.status_code == 409

    with Session(service_app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        assert db.scalar(select(func.count()).select_from(WorkOrder)) == 0


def test_customer_port_cannot_use_workbook_import(app_pair) -> None:
    customer_app, _ = app_pair
    with TestClient(customer_app) as client:
        response = client.post(
            "/api/v1/imports/workbook/preview",
            files={
                "file": (
                    "bad.xlsx",
                    _incomplete_workbook(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

    assert response.status_code == 403
