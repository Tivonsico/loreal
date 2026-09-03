from __future__ import annotations

from pathlib import Path

import pytest

from app.backend.config import Settings
from app.backend.main import create_app


@pytest.fixture
def shared_paths(tmp_path: Path) -> tuple[str, Path]:
    return f"sqlite:///{(tmp_path / 'test.db').as_posix()}", tmp_path / "media"


@pytest.fixture
def app_pair(shared_paths):
    database_url, media_dir = shared_paths
    customer = create_app(
        Settings(
            role="customer",
            database_url=database_url,
            media_dir=media_dir,
            assistant_dir=tmp_path / "assistant",
            max_upload_bytes=1024 * 1024,
            poll_interval=0.02,
        )
    )
    customer_service = create_app(
        Settings(
            role="customer_service",
            database_url=database_url,
            media_dir=media_dir,
            assistant_dir=tmp_path / "assistant",
            max_upload_bytes=1024 * 1024,
            poll_interval=0.02,
        )
    )
    return customer, customer_service
