import importlib


def test_config_loads_required_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "legacy-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.3-spark")
    monkeypatch.setenv("LLM_DEEP_DIVE_MODEL", "gpt-5.3-spark-deep")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "high")
    monkeypatch.setenv("EMBED_PROVIDER", "codex")
    monkeypatch.setenv("EMBED_MODEL", "text-embedding-3-small")
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
    monkeypatch.setenv("OPENAI_API_KEY", "dspy-key")
    monkeypatch.setenv("APP_MODE", "hermes")
    monkeypatch.setenv("DIGEST_DELIVERY_ENABLED", "1")
    monkeypatch.setenv("DIGEST_HOURS", "48")
    monkeypatch.setenv("DIGEST_GROUP_BY", "niche")
    monkeypatch.setenv("DIGEST_HOUR_UTC", "6")
    monkeypatch.setenv("DIGEST_MINUTE_UTC", "15")
    monkeypatch.setenv("DIGEST_MIN_WTP", "6")
    monkeypatch.setenv("DIGEST_MAX_ITEMS_PER_GROUP", "12")

    config_module = importlib.import_module("config")
    config_module = importlib.reload(config_module)

    assert config_module.TELEGRAM_BOT_TOKEN == "test-token"
    assert config_module.TELEGRAM_CHAT_ID == 123
    assert config_module.LLM_API_KEY == "test-key"
    assert config_module.LLM_PROVIDER == "codex"
    assert config_module.LLM_MODEL == "gpt-5.3-spark"
    assert config_module.LLM_DEEP_DIVE_MODEL == "gpt-5.3-spark-deep"
    assert config_module.LLM_REASONING_EFFORT == "high"
    assert config_module.EMBED_PROVIDER == "codex"
    assert config_module.EMBED_API_KEY == "test-key"
    assert config_module.EMBED_MODEL == "text-embedding-3-small"
    assert config_module.OPENROUTER_API_KEY == "test-key"
    assert config_module.OPENROUTER_MODEL == "gpt-5.3-spark"
    assert config_module.OPENROUTER_DEEP_DIVE_MODEL == "gpt-5.3-spark-deep"
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
    assert config_module.APP_MODE == "hermes"
    assert config_module.DIGEST_DELIVERY_ENABLED is True
    assert config_module.DIGEST_HOURS == 48
    assert config_module.DIGEST_GROUP_BY == "niche"
    assert config_module.DIGEST_HOUR_UTC == 6
    assert config_module.DIGEST_MINUTE_UTC == 15
    assert config_module.DIGEST_MIN_WTP == 6
    assert config_module.DIGEST_MAX_ITEMS_PER_GROUP == 12
    assert config_module.DSPY_REDDIT_PARSER_ENABLED is True
    assert config_module.DSPY_PROVIDER == "codex"
    assert config_module.DSPY_MODEL == "gpt-5.3-spark"
    assert config_module.DSPY_REASONING_EFFORT == "high"
    assert config_module.DSPY_API_KEY == "test-key"

