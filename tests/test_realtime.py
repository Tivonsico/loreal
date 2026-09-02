from fastapi.testclient import TestClient

from app.backend.realtime import RealtimeManager


class RecordingWebSocket:
    def __init__(self):
        self.accepted = False
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent.append(payload)


def test_message_crosses_process_boundary_via_shared_event_table(app_pair):
    customer_app, customer_service_app = app_pair
    with TestClient(customer_app) as customer, TestClient(customer_service_app) as customer_service:
        conversation_id = customer.post(
            "/api/v1/conversations", json={"customer_id": "C-WS"}
        ).json()["id"]
        with customer_service.websocket_connect(f"/ws/conversations/{conversation_id}") as socket:
            ready = socket.receive_json()
            assert ready["event"] == "connection.ready"
            assert ready["data"]["role"] == "customer_service"

            sent = customer.post(
                f"/api/v1/conversations/{conversation_id}/messages/text",
                json={"content": "跨端实时消息"},
            )
            assert sent.status_code == 201
            event = socket.receive_json()
            assert event["event"] == "message.created"
            assert event["data"]["id"] == sent.json()["id"]
            assert event["data"]["content"] == "跨端实时消息"


async def test_event_dispatcher_reads_messages_written_by_other_engine(app_pair):
    customer_app, customer_service_app = app_pair
    with TestClient(customer_app) as customer:
        conversation_id = customer.post(
            "/api/v1/conversations", json={"customer_id": "C-DISPATCH"}
        ).json()["id"]
        sent = customer.post(
            f"/api/v1/conversations/{conversation_id}/messages/text",
            json={"content": "共享数据库事件"},
        ).json()

        manager = RealtimeManager(
            customer_service_app.state.session_factory,
            poll_interval=0.02,
        )
        socket = RecordingWebSocket()
        await manager.connect(conversation_id, socket)
        await manager._dispatch_new_events()

        assert socket.accepted is True
        assert [item["data"]["id"] for item in socket.sent] == [sent["id"]]
