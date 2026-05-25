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
    monkeypatch.setenv("SCREEN_MIN_RULE_SCORE", "3")
    monkeypatch.setenv("SCREEN_MAX_LLM_CANDIDATES_PER_RUN", "21")
    monkeypatch.setenv("LLM_MAX_CLASSIFICATIONS_PER_RUN", "33")
    monkeypatch.setenv("PRIMARY_MAX_OUTPUT_TOKENS", "777")
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
    monkeypatch.setenv("CURRENT_OPPORTUNITY_MAX_AGE_DAYS", "180")
    monkeypatch.setenv("EVERGREEN_MAX_AGE_DAYS", "365")

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
    assert config_module.SCREEN_MIN_RULE_SCORE == 3
    assert config_module.SCREEN_MAX_LLM_CANDIDATES_PER_RUN == 21
    assert config_module.LLM_MAX_CLASSIFICATIONS_PER_RUN == 33
    assert config_module.PRIMARY_MAX_OUTPUT_TOKENS == 777
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
    assert config_module.CURRENT_OPPORTUNITY_MAX_AGE_DAYS == 180
    assert config_module.EVERGREEN_MAX_AGE_DAYS == 365
    assert config_module.DSPY_REDDIT_PARSER_ENABLED is True
    assert config_module.DSPY_PROVIDER == "codex"
    assert config_module.DSPY_MODEL == "gpt-5.3-spark"
    assert config_module.DSPY_REASONING_EFFORT == "high"
    assert config_module.DSPY_API_KEY == "test-key"


def test_dspy_parser_is_disabled_by_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.delenv("DSPY_REDDIT_PARSER_ENABLED", raising=False)

    config_module = importlib.import_module("config")
    config_module = importlib.reload(config_module)

    assert config_module.DSPY_REDDIT_PARSER_ENABLED is False


def test_config_uses_legacy_llm_key_when_primary_key_is_blank(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", " ")
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    config_module = importlib.import_module("config")
    config_module = importlib.reload(config_module)

    assert config_module.LLM_API_KEY == "legacy-key"
    assert config_module.EMBED_API_KEY == "legacy-key"


def test_config_rejects_blank_required_credentials(monkeypatch):
    import pytest

    cases = [
        (
            {"TELEGRAM_BOT_TOKEN": " ", "TELEGRAM_CHAT_ID": "123", "LLM_API_KEY": "test-key"},
            "TELEGRAM_BOT_TOKEN",
        ),
        (
            {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "TELEGRAM_CHAT_ID": "123",
                "LLM_API_KEY": " ",
                "OPENAI_API_KEY": " ",
                "OPENROUTER_API_KEY": " ",
            },
            "LLM_API_KEY",
        ),
    ]
    config_module = importlib.import_module("config")

    for env_values, expected_key in cases:
        for env_name, env_value in env_values.items():
            monkeypatch.setenv(env_name, env_value)
        with pytest.raises(KeyError, match=expected_key):
            importlib.reload(config_module)
        for env_name in env_values:
            monkeypatch.delenv(env_name, raising=False)
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        config_module = importlib.reload(config_module)


def test_config_rejects_invalid_enum_environment(monkeypatch):
    import pytest

    cases = [
        ("APP_MODE", "telegrm", "APP_MODE must be one of: hermes, telegram"),
        ("CLASSIFIER_MODE", "strict", "CLASSIFIER_MODE must be one of: b2b, dual, legacy"),
        ("DIGEST_GROUP_BY", "team", "DIGEST_GROUP_BY must be one of: category, niche, source"),
        ("LLM_PROVIDER", "opena1", "LLM_PROVIDER must be one of: codex, openai, openai-codex, openrouter"),
        ("EMBED_PROVIDER", "opena1", "EMBED_PROVIDER must be one of: bow, codex, disabled, hash, none, openai, openrouter"),
        ("DSPY_PROVIDER", "opena1", "DSPY_PROVIDER must be one of: codex, openai, openrouter"),
    ]
    config_module = importlib.import_module("config")

    for env_name, env_value, expected_message in cases:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv(env_name, env_value)
        with pytest.raises(ValueError, match=expected_message):
            importlib.reload(config_module)
        monkeypatch.delenv(env_name)
        config_module = importlib.reload(config_module)


def test_openai_codex_llm_defaults_embedding_and_dspy_to_codex(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai-codex")
    monkeypatch.delenv("EMBED_PROVIDER", raising=False)
    monkeypatch.delenv("DSPY_PROVIDER", raising=False)

    config_module = importlib.import_module("config")
    config_module = importlib.reload(config_module)

    assert config_module.LLM_PROVIDER == "openai-codex"
    assert config_module.EMBED_PROVIDER == "codex"
    assert config_module.DSPY_PROVIDER == "codex"


def test_config_rejects_invalid_enabled_source_environment(monkeypatch):
    import pytest

    cases = [
        (
            {"SCRAPER_FEED_MIX_JSON": '["neww"]'},
            "SCRAPER_FEED_MIX_JSON must contain only supported feeds: new, rising, top",
        ),
        (
            {"HN_ENABLED": "1", "HN_KEYWORDS_JSON": "[]"},
            "HN_KEYWORDS_JSON must contain at least one non-empty keyword when HN_ENABLED=1",
        ),
        (
            {"REVIEWS_ENABLED": "1", "REVIEW_TARGETS_JSON": "[]"},
            "REVIEW_TARGETS_JSON must contain at least one enabled target with site, name, and url when REVIEWS_ENABLED=1",
        ),
        (
            {"REVIEWS_ENABLED": "1", "REVIEW_TARGETS_JSON": '[{"site":"g2","name":"A"}]'},
            "REVIEW_TARGETS_JSON must contain at least one enabled target with site, name, and url when REVIEWS_ENABLED=1",
        ),
        (
            {"REVIEWS_ENABLED": "1", "REVIEW_TARGETS_JSON": '[{"site":"g2","name":"A","url":"u1"}]'},
            "REVIEW_TARGETS_JSON enabled target URLs must be public http or https URLs",
        ),
        (
            {"REVIEWS_ENABLED": "1", "REVIEW_TARGETS_JSON": '[{"site":"g2","name":"A","url":"http://127.0.0.1/reviews"}]'},
            "REVIEW_TARGETS_JSON enabled target URLs must be public http or https URLs",
        ),
    ]
    config_module = importlib.import_module("config")

    for env_values, expected_message in cases:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        for env_name, env_value in env_values.items():
            monkeypatch.setenv(env_name, env_value)
        with pytest.raises(ValueError, match=expected_message):
            importlib.reload(config_module)
        for env_name in env_values:
            monkeypatch.delenv(env_name)
        config_module = importlib.reload(config_module)


def test_config_loads_valid_enabled_source_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("HN_ENABLED", "1")
    monkeypatch.setenv("HN_KEYWORDS_JSON", '["manual process"]')
    monkeypatch.setenv("REVIEWS_ENABLED", "1")
    monkeypatch.setenv(
        "REVIEW_TARGETS_JSON",
        '[{"site":"g2","name":"Example CRM","url":"https://example.com/reviews","enabled":true}]',
    )

    config_module = importlib.import_module("config")
    config_module = importlib.reload(config_module)

    assert config_module.HN_ENABLED is True
    assert config_module.HN_KEYWORDS == ["manual process"]
    assert config_module.REVIEWS_ENABLED is True
    assert config_module.REVIEW_TARGETS[0]["name"] == "Example CRM"


def test_config_rejects_invalid_scheduler_environment(monkeypatch):
    import pytest

    cases = [
        ("DIGEST_HOUR_UTC", "24", "DIGEST_HOUR_UTC must be between 0 and 23"),
        ("DIGEST_MINUTE_UTC", "60", "DIGEST_MINUTE_UTC must be between 0 and 59"),
        ("MACRO_TREND_WEEKDAY_UTC", "funday", "MACRO_TREND_WEEKDAY_UTC must be one of: fri, mon, sat, sun, thu, tue, wed"),
        ("MACRO_TREND_HOUR_UTC", "-1", "MACRO_TREND_HOUR_UTC must be between 0 and 23"),
        ("HN_INTERVAL_HOURS", "0", "HN_INTERVAL_HOURS must be at least 1"),
        ("REVIEWS_INTERVAL_HOURS", "0", "REVIEWS_INTERVAL_HOURS must be at least 1"),
    ]
    config_module = importlib.import_module("config")

    for env_name, env_value, expected_message in cases:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv(env_name, env_value)
        with pytest.raises(ValueError, match=expected_message):
            importlib.reload(config_module)
        monkeypatch.delenv(env_name)
        config_module = importlib.reload(config_module)


def test_config_rejects_invalid_numeric_runtime_environment(monkeypatch):
    import pytest

    cases = [
        ("LLM_MAX_TOKENS", "0", "LLM_MAX_TOKENS must be at least 1"),
        ("PRIMARY_MAX_OUTPUT_TOKENS", "0", "PRIMARY_MAX_OUTPUT_TOKENS must be at least 1"),
        ("CLASSIFIER_MAX_CONCURRENCY", "0", "CLASSIFIER_MAX_CONCURRENCY must be at least 1"),
        ("DEDUP_SIMILARITY_THRESHOLD", "1.5", "DEDUP_SIMILARITY_THRESHOLD must be between 0 and 1"),
        ("TREND_CLUSTER_SIMILARITY", "-0.1", "TREND_CLUSTER_SIMILARITY must be between 0 and 1"),
        ("DIGEST_HOURS", "169", "DIGEST_HOURS must be between 1 and 168"),
        ("REVIEWS_MAX_PER_TARGET", "0", "REVIEWS_MAX_PER_TARGET must be at least 1"),
        ("DAILY_BUDGET_USD", "-0.01", "DAILY_BUDGET_USD must be at least 0"),
    ]
    config_module = importlib.import_module("config")

    for env_name, env_value, expected_message in cases:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv(env_name, env_value)
        with pytest.raises(ValueError, match=expected_message):
            importlib.reload(config_module)
        monkeypatch.delenv(env_name)
        config_module = importlib.reload(config_module)


def test_config_rejects_invalid_model_pricing_environment(monkeypatch):
    import pytest

    cases = [
        ("{", "LLM_MODEL_PRICING_JSON must be a valid JSON object"),
        ("[]", "LLM_MODEL_PRICING_JSON must be a JSON object"),
        ('{"m1": 1}', "LLM_MODEL_PRICING_JSON must map model names to pricing objects"),
        ('{"m1": {"prompt_per_1k": "free"}}', "LLM_MODEL_PRICING_JSON price values must be numbers"),
        ('{"m1": {"completion_per_1k": -0.01}}', "LLM_MODEL_PRICING_JSON price values must be non-negative"),
    ]
    config_module = importlib.import_module("config")

    for env_value, expected_message in cases:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv("LLM_MODEL_PRICING_JSON", env_value)
        with pytest.raises(ValueError, match=expected_message):
            importlib.reload(config_module)
        monkeypatch.delenv("LLM_MODEL_PRICING_JSON")
        config_module = importlib.reload(config_module)


def test_config_normalizes_model_pricing_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv(
        "LLM_MODEL_PRICING_JSON",
        '{"m1": {"prompt_per_1k": "0.002", "completion_per_1k": 0.004}}',
    )

    config_module = importlib.import_module("config")
    config_module = importlib.reload(config_module)

    assert config_module.LLM_MODEL_PRICING == {"m1": {"prompt_per_1k": 0.002, "completion_per_1k": 0.004}}

