from pathlib import Path

from app.backend.config import Settings


def test_generic_llm_environment_controls_provider(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-secret")
    monkeypatch.setenv("LLM_BASE_URL", "https://models.example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "replaceable-model")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("LLM_JSON_MODE", "false")

    settings = Settings.from_env(role="customer_service")

    assert settings.llm_api_key == "test-secret"
    assert settings.llm_base_url == "https://models.example.test/v1"
    assert settings.llm_model == "replaceable-model"
    assert settings.llm_timeout_seconds == 12.5
    assert settings.llm_json_mode is False
    assert "test-secret" not in repr(settings)
    assert isinstance(settings.media_dir, Path)
