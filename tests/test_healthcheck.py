import importlib


async def test_run_healthcheck_validates_storage_and_returns_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "health.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    import config
    import healthcheck

    importlib.reload(config)

    result = await healthcheck.run_healthcheck()

    assert result["ok"] is True
    assert result["db_path"] == str(tmp_path / "data" / "health.db")
    assert result["reports_dir"] == str(tmp_path / "reports")
    assert result["monitored"] == 0
    assert (tmp_path / "data" / "health.db").exists()
    assert (tmp_path / "reports").is_dir()


def test_main_returns_failure_when_healthcheck_raises(monkeypatch):
    import healthcheck

    async def fail_healthcheck():
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(healthcheck, "run_healthcheck", fail_healthcheck)

    assert healthcheck.main() == 1
