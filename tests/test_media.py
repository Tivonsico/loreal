import pytest
from fastapi.testclient import TestClient


def _conversation(client: TestClient) -> str:
    return client.post("/api/v1/conversations", json={"customer_id": "C-1"}).json()["id"]


@pytest.mark.parametrize(
    ("message_type", "filename", "mime_type"),
    [
        ("image", "photo.png", "image/png"),
        ("audio", "voice.mp3", "audio/mpeg"),
        ("video", "clip.mp4", "video/mp4"),
        ("file", "note.txt", "text/plain"),
    ],
)
def test_media_types_are_stored_and_readable(app_pair, message_type, filename, mime_type):
    customer_app, customer_service_app = app_pair
    with TestClient(customer_app) as customer, TestClient(customer_service_app) as customer_service:
        conversation_id = _conversation(customer)
        response = customer.post(
            f"/api/v1/conversations/{conversation_id}/messages/media",
            data={"message_type": message_type, "caption": "说明"},
            files={"file": (filename, b"sample-bytes", mime_type)},
        )
        assert response.status_code == 201
        message = response.json()
        assert message["message_type"] == message_type
        assert message["size_bytes"] == len(b"sample-bytes")
        assert customer_service.get(message["media_url"]).content == b"sample-bytes"


def test_media_rejects_empty_and_mismatched_file(app_pair):
    customer_app, _ = app_pair
    with TestClient(customer_app) as client:
        conversation_id = _conversation(client)
        mismatch = client.post(
            f"/api/v1/conversations/{conversation_id}/messages/media",
            data={"message_type": "image"},
            files={"file": ("fake.png", b"not-image", "text/plain")},
        )
        empty = client.post(
            f"/api/v1/conversations/{conversation_id}/messages/media",
            data={"message_type": "file"},
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert mismatch.status_code == 415
        assert empty.status_code == 422


def test_media_rejects_file_over_size_limit_and_removes_partial_file(app_pair):
    customer_app, _ = app_pair
    with TestClient(customer_app) as client:
        conversation_id = _conversation(client)
        response = client.post(
            f"/api/v1/conversations/{conversation_id}/messages/media",
            data={"message_type": "file"},
            files={"file": ("large.bin", b"x" * (1024 * 1024 + 1), "application/octet-stream")},
        )
        assert response.status_code == 413
        assert not any(customer_app.state.settings.media_dir.iterdir())
