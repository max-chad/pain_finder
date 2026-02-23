# tests/test_config.py
import importlib


def test_config_loads_required_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "test-model")
    monkeypatch.setenv("DB_PATH", "custom.db")
    monkeypatch.setenv("REPORTS_DIR", "custom-reports")

    config_module = importlib.import_module("config")
    config_module = importlib.reload(config_module)

    assert config_module.TELEGRAM_BOT_TOKEN == "test-token"
    assert config_module.TELEGRAM_CHAT_ID == 123
    assert config_module.OPENROUTER_API_KEY == "test-key"
    assert config_module.OPENROUTER_MODEL == "test-model"
    assert config_module.DB_PATH == "custom.db"
    assert config_module.REPORTS_DIR == "custom-reports"
