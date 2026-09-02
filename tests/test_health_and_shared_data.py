from fastapi.testclient import TestClient


def test_two_entries_have_fixed_roles_and_share_catalog(app_pair):
    customer_app, customer_service_app = app_pair
    with TestClient(customer_app) as customer, TestClient(customer_service_app) as customer_service:
        assert customer.get("/health").json()["role"] == "customer"
        assert customer_service.get("/health").json()["role"] == "customer_service"

        conversation = customer.post(
            "/api/v1/conversations",
            json={"customer_id": "C-001", "title": "咨询"},
        )
        assert conversation.status_code == 201
        conversation_id = conversation.json()["id"]
        assert customer_service.get(f"/api/v1/conversations/{conversation_id}").status_code == 200

        product = customer.post(
            "/api/v1/products",
            json={"external_id": "P-001", "name": "初始名称", "price": "99.00"},
        )
        assert product.status_code == 201
        imported = customer_service.post(
            "/api/v1/products/import",
            json={"items": [{"external_id": "P-001", "name": "更新名称"}]},
        )
        assert imported.json() == {"created": 0, "updated": 1}
        products = customer.get("/api/v1/products").json()
        assert len(products) == 1
        assert products[0]["name"] == "更新名称"

        order = customer_service.post(
            "/api/v1/orders",
            json={
                "external_id": "O-001",
                "customer_id": "C-001",
                "product_external_id": "P-001",
                "conversation_id": conversation_id,
                "status": "paid",
            },
        )
        assert order.status_code == 201
        order_import = customer.post(
            "/api/v1/orders/import",
            json={
                "items": [
                    {
                        "external_id": "O-001",
                        "customer_id": "C-001",
                        "product_external_id": "P-001",
                        "conversation_id": conversation_id,
                        "status": "shipped",
                    }
                ]
            },
        )
        assert order_import.json() == {"created": 0, "updated": 1}
        orders = customer.get("/api/v1/orders?customer_id=C-001").json()
        assert len(orders) == 1
        assert orders[0]["external_id"] == "O-001"
        assert orders[0]["status"] == "shipped"


def test_order_rejects_unknown_product(app_pair):
    customer_app, _ = app_pair
    with TestClient(customer_app) as client:
        response = client.post(
            "/api/v1/orders",
            json={
                "external_id": "O-BAD",
                "customer_id": "C-001",
                "product_external_id": "missing",
            },
        )
        assert response.status_code == 422
        assert "商品不存在" in response.json()["detail"]
