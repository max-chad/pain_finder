import importlib
import sqlite3


def test_build_parser_help_mentions_readiness_gate_and_examples():
    import healthcheck

    help_text = " ".join(healthcheck.build_parser().format_help().split())

    assert "Local liveness check for Docker and readiness gate for operators." in help_text
    assert "Use --fail-on-job-errors when readiness errors should fail closed." in help_text
    assert "python healthcheck.py --fail-on-job-errors" in help_text


async def test_run_healthcheck_validates_storage_and_returns_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "health.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    import config
    import healthcheck
    from db import Database

    importlib.reload(config)
    (tmp_path / "data").mkdir()
    db = Database(config.DB_PATH)
    await db.init()
    await db.mark_scheduled_job_failure("hn_ingest", "network down")
    await db.close()

    result = await healthcheck.run_healthcheck()

    assert result["ok"] is True
    assert result["db_path"] == str(tmp_path / "data" / "health.db")
    assert result["reports_dir"] == str(tmp_path / "reports")
    assert result["monitored"] == 0
    assert result["readiness_errors"] == 1
    assert result["scheduled_job_errors"] == 1
    assert result["monitor_errors"] == 0
    assert (tmp_path / "data" / "health.db").exists()
    assert (tmp_path / "reports").is_dir()


async def test_run_healthcheck_fail_on_job_errors_fails_on_scheduled_job_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "health.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    import config
    import healthcheck
    import pytest
    from db import Database

    importlib.reload(config)
    (tmp_path / "data").mkdir()
    db = Database(config.DB_PATH)
    await db.init()
    await db.mark_scheduled_job_failure("reviews_ingest", "rate limited")
    await db.close()

    with pytest.raises(RuntimeError, match="readiness errors present: 1"):
        await healthcheck.run_healthcheck(fail_on_job_errors=True)


async def test_run_healthcheck_fail_on_job_errors_fails_on_monitor_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "health.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    import config
    import healthcheck
    import pytest
    from db import Database

    importlib.reload(config)
    (tmp_path / "data").mkdir()
    db = Database(config.DB_PATH)
    await db.init()
    await db.add_monitored_subreddit("python", interval_hours=1)
    await db.mark_monitor_failed("python", "collector down")
    await db.close()

    with pytest.raises(RuntimeError, match="readiness errors present: 1"):
        await healthcheck.run_healthcheck(fail_on_job_errors=True)


async def test_run_healthcheck_does_not_initialize_database(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    db_path = tmp_path / "data" / "empty.db"
    db_path.parent.mkdir()
    sqlite3.connect(db_path).close()
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    import config
    import healthcheck
    import pytest

    importlib.reload(config)

    with pytest.raises(RuntimeError, match="database is not initialized"):
        await healthcheck.run_healthcheck()

    conn = sqlite3.connect(db_path)
    try:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    finally:
        conn.close()
    assert tables == []


async def test_run_healthcheck_tolerates_legacy_database_without_scheduled_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    db_path = tmp_path / "data" / "legacy.db"
    db_path.parent.mkdir()
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE runtime_flags (id INTEGER PRIMARY KEY CHECK (id = 1), llm_paused INTEGER DEFAULT 0)"
        )
        conn.execute(
            "CREATE TABLE monitored_subreddits (id INTEGER PRIMARY KEY, name TEXT, active INTEGER DEFAULT 1)"
        )
        conn.execute("CREATE TABLE pain_points (id INTEGER PRIMARY KEY, triage_status TEXT DEFAULT 'new')")
        conn.execute(
            """
            CREATE TABLE llm_usage_events (
                id INTEGER PRIMARY KEY,
                model TEXT NOT NULL,
                operation TEXT NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0,
                post_id TEXT,
                prompt_hash TEXT,
                fallback_reason TEXT,
                schema_version TEXT,
                provider TEXT,
                request_path TEXT,
                candidate_stage TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute("INSERT INTO runtime_flags (id, llm_paused) VALUES (1, 0)")
        conn.execute("INSERT INTO monitored_subreddits (name, active) VALUES ('python', 1)")
        conn.commit()
    finally:
        conn.close()

    import config
    import healthcheck

    importlib.reload(config)

    result = await healthcheck.run_healthcheck()

    assert result["ok"] is True
    assert result["monitored"] == 1
    assert result["readiness_errors"] == 0
    assert result["scheduled_job_errors"] == 0
    assert result["monitor_errors"] == 0

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    finally:
        conn.close()
    assert "scheduled_job_status" not in tables


async def test_run_healthcheck_fails_when_llm_usage_events_table_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    db_path = tmp_path / "data" / "legacy_missing_usage.db"
    db_path.parent.mkdir()
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE runtime_flags (id INTEGER PRIMARY KEY CHECK (id = 1), llm_paused INTEGER DEFAULT 0)"
        )
        conn.execute(
            "CREATE TABLE monitored_subreddits (id INTEGER PRIMARY KEY, name TEXT, active INTEGER DEFAULT 1)"
        )
        conn.execute("CREATE TABLE pain_points (id INTEGER PRIMARY KEY, triage_status TEXT DEFAULT 'new')")
        conn.execute("INSERT INTO runtime_flags (id, llm_paused) VALUES (1, 0)")
        conn.execute("INSERT INTO monitored_subreddits (name, active) VALUES ('python', 1)")
        conn.commit()
    finally:
        conn.close()

    import config
    import healthcheck
    import pytest

    importlib.reload(config)

    with pytest.raises(RuntimeError, match="missing tables: llm_usage_events"):
        await healthcheck.run_healthcheck()


async def test_run_healthcheck_fails_when_runtime_flags_row_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "health.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    import config
    import healthcheck
    from db import Database
    import pytest

    importlib.reload(config)
    (tmp_path / "data").mkdir()
    db = Database(config.DB_PATH)
    await db.init()
    await db._conn.execute("DELETE FROM runtime_flags WHERE id = 1")
    await db._conn.commit()
    await db.close()

    with pytest.raises(RuntimeError, match="runtime flags row integrity"):
        await healthcheck.run_healthcheck()


async def test_run_healthcheck_fails_when_usage_event_rows_are_invalid(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "health.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    import config
    import healthcheck
    from db import Database
    import pytest

    importlib.reload(config)
    (tmp_path / "data").mkdir()
    db = Database(config.DB_PATH)
    await db.init()
    await db._conn.execute(
        """
        INSERT INTO llm_usage_events (
            model, operation, prompt_tokens, completion_tokens, cost_usd, created_at
        ) VALUES (?, ?, ?, ?, ?, datetime('now'))
        """,
        ("", "classify_primary", 1, 1, 0.25),
    )
    await db._conn.commit()
    await db.close()

    with pytest.raises(RuntimeError, match="invalid llm_usage_events rows"):
        await healthcheck.run_healthcheck()


async def test_run_healthcheck_fails_when_whitespace_only_usage_event_rows_are_invalid(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "health.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    import config
    import healthcheck
    import pytest
    from db import Database

    importlib.reload(config)
    (tmp_path / "data").mkdir()
    db = Database(config.DB_PATH)
    await db.init()
    await db._conn.executemany(
        """
        INSERT INTO llm_usage_events (
            model, operation, prompt_tokens, completion_tokens, cost_usd, created_at
        ) VALUES (?, ?, ?, ?, ?, datetime('now'))
        """,
        [
            ("\n", "classify_primary", 1, 1, 0.25),
            ("gpt-4o-mini", "\t", 1, 1, 0.25),
        ],
    )
    await db._conn.commit()
    await db.close()

    with pytest.raises(RuntimeError, match="invalid llm_usage_events rows: 2"):
        await healthcheck.run_healthcheck()


async def test_run_healthcheck_fails_when_database_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "missing.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    import config
    import healthcheck
    import pytest

    importlib.reload(config)

    with pytest.raises(FileNotFoundError, match="database does not exist"):
        await healthcheck.run_healthcheck()


def test_main_returns_failure_when_healthcheck_raises(monkeypatch):
    import healthcheck

    async def fail_healthcheck(*, fail_on_job_errors=False):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(healthcheck, "run_healthcheck", fail_healthcheck)

    assert healthcheck.main([]) == 1


def test_main_passes_fail_on_job_errors_flag(monkeypatch, capsys):
    import healthcheck

    captured = {}

    async def fake_healthcheck(*, fail_on_job_errors=False):
        captured["fail_on_job_errors"] = fail_on_job_errors
        return {
            "db_path": "db.sqlite",
            "reports_dir": "reports",
            "llm_paused": False,
            "monitored": 0,
            "readiness_errors": 0,
            "scheduled_job_errors": 0,
            "monitor_errors": 0,
        }

    monkeypatch.setattr(healthcheck, "run_healthcheck", fake_healthcheck)

    assert healthcheck.main(["--fail-on-job-errors"]) == 0
    assert captured["fail_on_job_errors"] is True
    output = capsys.readouterr().out
    assert "readiness_errors=0" in output
    assert "scheduled_job_errors=0" in output
    assert "monitor_errors=0" in output
