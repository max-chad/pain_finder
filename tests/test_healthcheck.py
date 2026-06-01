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
