from pathlib import Path

from app.backend.config import Settings


def test_generic_llm_environment_controls_provider(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-secret")
    monkeypatch.setenv("LLM_BASE_URL", "https://models.example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "replaceable-model")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("LLM_JSON_MODE", "false")
    monkeypatch.setenv("LLM_REASONING_MODE", "low")
    monkeypatch.setenv("EMOTION_ANALYSIS_BATCH_SIZE", "12")
    monkeypatch.setenv("EMOTION_ANALYSIS_WORKERS", "3")

    settings = Settings.from_env(role="customer_service")

    assert settings.llm_api_key == "test-secret"
    assert settings.llm_base_url == "https://models.example.test/v1"
    assert settings.llm_model == "replaceable-model"
    assert settings.llm_timeout_seconds == 12.5
    assert settings.llm_json_mode is False
    assert settings.llm_reasoning_mode == "low"
    assert settings.emotion_batch_size == 12
    assert settings.emotion_batch_workers == 3
    assert "test-secret" not in repr(settings)
    assert isinstance(settings.media_dir, Path)


def test_emotion_analysis_defaults_are_low_latency_and_bounded(monkeypatch) -> None:
    for key in (
        "LLM_REASONING_MODE",
        "EMOTION_ANALYSIS_BATCH_SIZE",
        "EMOTION_ANALYSIS_WORKERS",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings.from_env(role="customer_service")

    assert settings.llm_reasoning_mode == "low"
    assert settings.emotion_batch_size == 4
    assert settings.emotion_batch_workers == 2
