from fastapi.testclient import TestClient
from sqlalchemy import text


def _create_conversation(client: TestClient) -> str:
    response = client.post("/api/v1/conversations", json={"customer_id": "C-001"})
    assert response.status_code == 201
    return response.json()["id"]


def test_text_messages_are_shared_and_role_is_derived_from_entry(app_pair):
    customer_app, customer_service_app = app_pair
    with TestClient(customer_app) as customer, TestClient(customer_service_app) as customer_service:
        conversation_id = _create_conversation(customer)
        first = customer.post(
            f"/api/v1/conversations/{conversation_id}/messages/text",
            json={"content": "  客户消息  "},
        )
        second = customer_service.post(
            f"/api/v1/conversations/{conversation_id}/messages/text",
            json={"content": "客服回复"},
        )
        assert first.json()["sender_role"] == "customer"
        assert first.json()["content"] == "客户消息"
        assert second.json()["sender_role"] == "customer_service"

        history = customer.get(f"/api/v1/conversations/{conversation_id}/messages").json()["items"]
        assert [(item["sender_role"], item["content"]) for item in history] == [
            ("customer", "客户消息"),
            ("customer_service", "客服回复"),
        ]


def test_text_message_validation(app_pair):
    customer_app, _ = app_pair
    with TestClient(customer_app) as client:
        conversation_id = _create_conversation(client)
        empty = client.post(
            f"/api/v1/conversations/{conversation_id}/messages/text",
            json={"content": "   "},
        )
        missing = client.post(
            "/api/v1/conversations/not-found/messages/text",
            json={"content": "hello"},
        )
        assert empty.status_code == 422
        assert missing.status_code == 404


def test_legacy_customer_service_role_is_migrated_on_startup(app_pair):
    customer_app, customer_service_app = app_pair
    with TestClient(customer_app) as customer:
        conversation_id = _create_conversation(customer)
        message_id = customer.post(
            f"/api/v1/conversations/{conversation_id}/messages/text",
            json={"content": "历史客服消息"},
        ).json()["id"]

    with customer_app.state.engine.begin() as connection:
        connection.execute(
            text("UPDATE messages SET sender_role = 'agent' WHERE id = :message_id"),
            {"message_id": message_id},
        )

    with TestClient(customer_service_app) as customer_service:
        history = customer_service.get(f"/api/v1/conversations/{conversation_id}/messages").json()[
            "items"
        ]
        assert history[0]["sender_role"] == "customer_service"
