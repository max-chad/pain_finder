# tests/test_scheduler.py
from unittest.mock import AsyncMock

from scheduler import MonitoringScheduler


async def test_scheduler_starts_and_stops_without_error():
    mock_db = AsyncMock()
    mock_db.get_monitored_subreddits.return_value = []
    mock_db.is_llm_paused.return_value = False
    mock_analyze = AsyncMock()
    sched = MonitoringScheduler(db=mock_db, analyze_fn=mock_analyze)
    sched.start()
    sched.stop()


async def test_reload_jobs_creates_job_per_subreddit():
    mock_db = AsyncMock()
    mock_db.get_monitored_subreddits.return_value = [
        {"name": "python", "interval_hours": 6},
        {"name": "webdev", "interval_hours": 12},
    ]
    mock_db.is_llm_paused.return_value = False
    mock_analyze = AsyncMock()
    sched = MonitoringScheduler(db=mock_db, analyze_fn=mock_analyze)
    sched.start()
    await sched.reload_jobs()
    job_ids = {job.id for job in sched.scheduler.get_jobs()}
    assert "monitor_python" in job_ids
    assert "monitor_webdev" in job_ids
    sched.stop()


async def test_reload_jobs_removes_old_jobs_before_adding():
    mock_db = AsyncMock()
    mock_db.get_monitored_subreddits.return_value = [
        {"name": "python", "interval_hours": 6},
    ]
    mock_db.is_llm_paused.return_value = False
    mock_analyze = AsyncMock()
    sched = MonitoringScheduler(db=mock_db, analyze_fn=mock_analyze)
    sched.start()
    await sched.reload_jobs()
    # Change the list and reload - old job should be gone
    mock_db.get_monitored_subreddits.return_value = [
        {"name": "rust", "interval_hours": 3},
    ]
    await sched.reload_jobs()
    job_ids = {job.id for job in sched.scheduler.get_jobs()}
    assert "monitor_python" not in job_ids
    assert "monitor_rust" in job_ids
    sched.stop()


async def test_get_job_count_returns_correct_number():
    mock_db = AsyncMock()
    mock_db.get_monitored_subreddits.return_value = [
        {"name": "python", "interval_hours": 6},
        {"name": "rust", "interval_hours": 3},
        {"name": "webdev", "interval_hours": 12},
    ]
    mock_db.is_llm_paused.return_value = False
    mock_analyze = AsyncMock()
    sched = MonitoringScheduler(db=mock_db, analyze_fn=mock_analyze)
    sched.start()
    await sched.reload_jobs()
    assert sched.job_count() == 3
    sched.stop()


async def test_run_analysis_updates_last_checked_on_success():
    mock_db = AsyncMock()
    mock_db.is_llm_paused.return_value = False
    mock_analyze = AsyncMock()
    sched = MonitoringScheduler(db=mock_db, analyze_fn=mock_analyze)

    await sched._run_analysis("python")

    mock_analyze.assert_awaited_once_with("python")
    mock_db.update_last_checked.assert_awaited_once_with("python")


async def test_run_analysis_skips_last_checked_on_failure():
    mock_db = AsyncMock()
    mock_db.is_llm_paused.return_value = False
    mock_analyze = AsyncMock(side_effect=RuntimeError("boom"))
    sched = MonitoringScheduler(db=mock_db, analyze_fn=mock_analyze)

    await sched._run_analysis("python")

    mock_analyze.assert_awaited_once_with("python")
    mock_db.update_last_checked.assert_not_awaited()


async def test_reload_jobs_skips_when_paused():
    mock_db = AsyncMock()
    mock_db.is_llm_paused.return_value = True
    mock_db.get_monitored_subreddits.return_value = [{"name": "python", "interval_hours": 1}]
    sched = MonitoringScheduler(db=mock_db, analyze_fn=AsyncMock())
    sched.start()
    await sched.reload_jobs()
    assert sched.job_count() == 0
    sched.stop()


async def test_reload_jobs_adds_macro_hn_reviews_jobs():
    mock_db = AsyncMock()
    mock_db.is_llm_paused.return_value = False
    mock_db.get_monitored_subreddits.return_value = [{"name": "python", "interval_hours": 6}]
    sched = MonitoringScheduler(
        db=mock_db,
        analyze_fn=AsyncMock(),
        macro_fn=AsyncMock(),
        hn_fn=AsyncMock(),
        reviews_fn=AsyncMock(),
        macro_enabled=True,
        hn_enabled=True,
        reviews_enabled=True,
        hn_interval_hours=4,
        reviews_interval_hours=8,
    )
    sched.start()
    await sched.reload_jobs()
    job_ids = {job.id for job in sched.scheduler.get_jobs()}
    assert "monitor_python" in job_ids
    assert "macro_weekly" in job_ids
    assert "hn_ingest" in job_ids
    assert "reviews_ingest" in job_ids
    sched.stop()


async def test_run_macro_hn_reviews_execute_callbacks():
    mock_db = AsyncMock()
    mock_db.is_llm_paused.return_value = False
    macro_fn = AsyncMock()
    hn_fn = AsyncMock()
    reviews_fn = AsyncMock()
    sched = MonitoringScheduler(
        db=mock_db,
        analyze_fn=AsyncMock(),
        macro_fn=macro_fn,
        hn_fn=hn_fn,
        reviews_fn=reviews_fn,
    )
    await sched._run_macro()
    await sched._run_hn()
    await sched._run_reviews()
    macro_fn.assert_awaited_once()
    hn_fn.assert_awaited_once()
    reviews_fn.assert_awaited_once()
