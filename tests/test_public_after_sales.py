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


def test_customer_after_sales_projection_is_strict_allowlist(app_pair) -> None:
    customer_app, service_app = app_pair
    workbook = _official_workbook()
    with TestClient(service_app) as service:
        with workbook.open("rb") as source:
            preview = service.post(
                "/api/v1/imports/workbook/preview",
                files={
                    "file": (
                        workbook.name,
                        source,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
        service.post(f"/api/v1/imports/workbook/{preview.json()['batch_id']}/commit")
        adverse = service.get(
            "/api/v1/work-orders",
            params={"ticket_type": "adverse_reaction", "page_size": 1},
        ).json()["items"][0]

    with TestClient(customer_app) as customer:
        response = customer.get(f"/api/v1/public/customers/{adverse['customer_id']}/after-sales")

    assert response.status_code == 200
    assert response.json()
    allowed = {
        "external_id",
        "ticket_type",
        "status",
        "updated_at",
        "replacement_tracking_no",
        "confirmed_payment_amount",
        "confirmed_payment_status",
    }
    assert all(set(item) == allowed for item in response.json())
    serialized = response.text
    for forbidden in (
        "assignee",
        "description",
        "resolution",
        "source_extra",
        "masked_account",
        "symptoms",
        "sought_medical_care",
        "is_abnormal",
    ):
        assert forbidden not in serialized
