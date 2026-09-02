from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

VALID_ROLES = {"customer", "customer_service"}
DEFAULT_PORTS = {"customer": 8000, "customer_service": 8001}


def load_local_env() -> None:
    """Load simple KEY=VALUE pairs without overwriting process environment variables."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True, slots=True)
class Settings:
    role: str
    database_url: str
    media_dir: Path
    max_upload_bytes: int = 50 * 1024 * 1024
    poll_interval: float = 0.2
    llm_api_key: str | None = field(default=None, repr=False)
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen3.7-flash"
    llm_timeout_seconds: float = 30.0
    llm_json_mode: bool = True

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise ValueError(f"role 必须是 {sorted(VALID_ROLES)} 之一")
        if self.max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes 必须大于 0")
        if self.poll_interval <= 0:
            raise ValueError("poll_interval 必须大于 0")
        if self.llm_timeout_seconds <= 0:
            raise ValueError("llm_timeout_seconds 必须大于 0")

    @classmethod
    def from_env(cls, role: str | None = None) -> Settings:
        load_local_env()
        return cls(
            role=role or os.getenv("APP_ROLE", "customer"),
            database_url=os.getenv("APP_DATABASE_URL", "sqlite:///./data/app.db"),
            media_dir=Path(os.getenv("APP_MEDIA_DIR", "./data/media")).resolve(),
            max_upload_bytes=int(os.getenv("APP_MAX_UPLOAD_BYTES", 50 * 1024 * 1024)),
            poll_interval=float(os.getenv("APP_POLL_INTERVAL", "0.2")),
            llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or None,
            llm_base_url=os.getenv(
                "LLM_BASE_URL",
                os.getenv(
                    "DASHSCOPE_BASE_URL",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                ),
            ),
            llm_model=os.getenv("LLM_MODEL", os.getenv("DASHSCOPE_MODEL", "qwen3.7-flash")),
            llm_timeout_seconds=float(
                os.getenv("LLM_TIMEOUT_SECONDS", os.getenv("DASHSCOPE_TIMEOUT_SECONDS", "30"))
            ),
            llm_json_mode=os.getenv("LLM_JSON_MODE", "true").strip().lower()
            not in {"0", "false", "no", "off"},
        )
