import importlib
import sqlite3


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
    assert result["scheduled_job_errors"] == 1
    assert (tmp_path / "data" / "health.db").exists()
    assert (tmp_path / "reports").is_dir()


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
    assert result["scheduled_job_errors"] == 0

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    finally:
        conn.close()
    assert "scheduled_job_status" not in tables


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

    async def fail_healthcheck():
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(healthcheck, "run_healthcheck", fail_healthcheck)

    assert healthcheck.main() == 1
