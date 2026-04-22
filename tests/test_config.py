import importlib


def test_config_loads_required_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "test-model")
    monkeypatch.setenv("OPENROUTER_DEEP_DIVE_MODEL", "deep-model")
    monkeypatch.setenv("DB_PATH", "custom.db")
    monkeypatch.setenv("REPORTS_DIR", "custom-reports")
    monkeypatch.setenv("CLASSIFIER_MODE", "dual")
    monkeypatch.setenv("CLASSIFIER_MAX_CONCURRENCY", "5")
    monkeypatch.setenv("LLM_MAX_CLASSIFICATIONS_PER_RUN", "33")
    monkeypatch.setenv("DEEP_DIVE_WTP_THRESHOLD", "9")
    monkeypatch.setenv("DEEP_DIVE_MAX_COMMENTS", "300")
    monkeypatch.setenv("SCRAPER_TOP_COMMENTS", "7")
    monkeypatch.setenv("SCRAPER_COMMENT_FETCH_CONCURRENCY", "3")
    monkeypatch.setenv("SCRAPER_RETRY_MAX_ATTEMPTS", "6")
    monkeypatch.setenv("SCRAPER_RETRY_BASE_DELAY", "1.5")
    monkeypatch.setenv("SCRAPER_FEED_MIX_JSON", '["new", "top"]')
    monkeypatch.setenv("SCRAPER_SEARCH_QUERIES_JSON", '["manual process", "spreadsheet workaround"]')
    monkeypatch.setenv("EXPORT_MIN_WTP", "7")
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "{}")
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", "sheet-id")
    monkeypatch.setenv("GOOGLE_SHEETS_WORKSHEET_PREFIX", "pf")
    monkeypatch.setenv("DSPY_REDDIT_PARSER_ENABLED", "1")
    monkeypatch.setenv("DSPY_PROVIDER", "codex")
    monkeypatch.setenv("DSPY_MODEL", "gpt-5.3-spark")
    monkeypatch.setenv("DSPY_REASONING_EFFORT", "high")
    monkeypatch.setenv("OPENAI_API_KEY", "dspy-key")

    config_module = importlib.import_module("config")
    config_module = importlib.reload(config_module)

    assert config_module.TELEGRAM_BOT_TOKEN == "test-token"
    assert config_module.TELEGRAM_CHAT_ID == 123
    assert config_module.OPENROUTER_API_KEY == "test-key"
    assert config_module.OPENROUTER_MODEL == "test-model"
    assert config_module.OPENROUTER_DEEP_DIVE_MODEL == "deep-model"
    assert config_module.DB_PATH == "custom.db"
    assert config_module.REPORTS_DIR == "custom-reports"
    assert config_module.CLASSIFIER_MODE == "dual"
    assert config_module.CLASSIFIER_MAX_CONCURRENCY == 5
    assert config_module.LLM_MAX_CLASSIFICATIONS_PER_RUN == 33
    assert config_module.DEEP_DIVE_WTP_THRESHOLD == 9
    assert config_module.DEEP_DIVE_MAX_COMMENTS == 300
    assert config_module.SCRAPER_TOP_COMMENTS == 7
    assert config_module.SCRAPER_COMMENT_FETCH_CONCURRENCY == 3
    assert config_module.SCRAPER_RETRY_MAX_ATTEMPTS == 6
    assert config_module.SCRAPER_RETRY_BASE_DELAY == 1.5
    assert config_module.SCRAPER_FEED_MIX == ["new", "top"]
    assert config_module.SCRAPER_SEARCH_QUERIES == ["manual process", "spreadsheet workaround"]
    assert config_module.EXPORT_MIN_WTP == 7
    assert config_module.GOOGLE_SHEETS_CREDENTIALS_JSON == "{}"
    assert config_module.GOOGLE_SHEETS_SPREADSHEET_ID == "sheet-id"
    assert config_module.GOOGLE_SHEETS_WORKSHEET_PREFIX == "pf"
    assert config_module.DSPY_REDDIT_PARSER_ENABLED is True
    assert config_module.DSPY_PROVIDER == "codex"
    assert config_module.DSPY_MODEL == "gpt-5.3-spark"
    assert config_module.DSPY_REASONING_EFFORT == "high"
    assert config_module.DSPY_API_KEY == "dspy-key"

