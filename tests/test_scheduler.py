# tests/test_scheduler.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from scheduler import MonitoringScheduler


async def test_scheduler_starts_and_stops_without_error():
    mock_db = AsyncMock()
    mock_db.get_monitored_subreddits.return_value = []
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
    mock_analyze = AsyncMock()
    sched = MonitoringScheduler(db=mock_db, analyze_fn=mock_analyze)
    sched.start()
    await sched.reload_jobs()
    # Change the list and reload — old job should be gone
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
    mock_analyze = AsyncMock()
    sched = MonitoringScheduler(db=mock_db, analyze_fn=mock_analyze)
    sched.start()
    await sched.reload_jobs()
    assert sched.job_count() == 3
    sched.stop()


async def test_run_analysis_updates_last_checked_on_success():
    mock_db = AsyncMock()
    mock_analyze = AsyncMock()
    sched = MonitoringScheduler(db=mock_db, analyze_fn=mock_analyze)

    await sched._run_analysis("python")

    mock_analyze.assert_awaited_once_with("python")
    mock_db.update_last_checked.assert_awaited_once_with("python")


async def test_run_analysis_skips_last_checked_on_failure():
    mock_db = AsyncMock()
    mock_analyze = AsyncMock(side_effect=RuntimeError("boom"))
    sched = MonitoringScheduler(db=mock_db, analyze_fn=mock_analyze)

    await sched._run_analysis("python")

    mock_analyze.assert_awaited_once_with("python")
    mock_db.update_last_checked.assert_not_awaited()
