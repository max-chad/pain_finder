from __future__ import annotations

import asyncio
import argparse
import os
import tempfile
from pathlib import Path
from collections.abc import Sequence
from typing import Any

import aiosqlite


def _assert_writable_dir(path: str) -> None:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".healthcheck_", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("ok")
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass


async def run_healthcheck(*, fail_on_job_errors: bool = False) -> dict[str, Any]:
    import config

    _assert_writable_dir(config.REPORTS_DIR)

    db_parent = Path(config.DB_PATH).expanduser().resolve().parent
    _assert_writable_dir(str(db_parent))

    db = await _open_readonly_db(config.DB_PATH)
    try:
        await _assert_initialized(db)
        flags = await _get_runtime_flags(db)
        summary = await _get_monitoring_summary(db)
    finally:
        await db.close()

    scheduled_job_errors = int(summary.get("scheduled_job_errors", 0))
    if fail_on_job_errors and scheduled_job_errors:
        raise RuntimeError(f"scheduled job errors present: {scheduled_job_errors}")

    return {
        "ok": True,
        "db_path": config.DB_PATH,
        "reports_dir": config.REPORTS_DIR,
        "llm_paused": bool(flags.get("llm_paused", 0)),
        "monitored": int(summary.get("monitored", 0)),
        "scheduled_job_errors": scheduled_job_errors,
    }


async def _open_readonly_db(path: str) -> aiosqlite.Connection:
    db_path = Path(path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"database does not exist: {db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = await aiosqlite.connect(uri, uri=True)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA query_only=ON;")
    await conn.execute("PRAGMA busy_timeout=5000;")
    return conn


async def _assert_initialized(db: aiosqlite.Connection) -> None:
    required_tables = {"runtime_flags", "monitored_subreddits", "pain_points"}
    placeholders = ",".join("?" for _ in required_tables)
    async with db.execute(
        f"SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({placeholders})",
        tuple(required_tables),
    ) as cursor:
        rows = await cursor.fetchall()
    existing = {row["name"] for row in rows}
    missing = sorted(required_tables - existing)
    if missing:
        raise RuntimeError(f"database is not initialized; missing tables: {', '.join(missing)}")


async def _get_runtime_flags(db: aiosqlite.Connection) -> dict[str, Any]:
    async with db.execute("SELECT * FROM runtime_flags WHERE id = 1") as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else {}


async def _get_monitoring_summary(db: aiosqlite.Connection) -> dict[str, int]:
    async with db.execute("SELECT COUNT(*) AS total FROM monitored_subreddits WHERE active = 1") as cursor:
        monitored = await cursor.fetchone()
    async with db.execute("SELECT COUNT(*) AS total FROM pain_points WHERE triage_status = 'favorite'") as cursor:
        favorites = await cursor.fetchone()
    monitor_error_count = 0
    if await _column_exists(db, "monitored_subreddits", "last_error"):
        async with db.execute(
            "SELECT COUNT(*) AS total FROM monitored_subreddits WHERE active = 1 AND last_error IS NOT NULL"
        ) as cursor:
            monitor_errors = await cursor.fetchone()
        monitor_error_count = int(monitor_errors["total"] if monitor_errors else 0)
    scheduled_job_errors = 0
    if await _table_exists(db, "scheduled_job_status"):
        async with db.execute(
            "SELECT COUNT(*) AS total FROM scheduled_job_status WHERE last_error IS NOT NULL"
        ) as cursor:
            failed_jobs = await cursor.fetchone()
        scheduled_job_errors = int(failed_jobs["total"] if failed_jobs else 0)
    scheduled_job_errors += monitor_error_count
    return {
        "monitored": int(monitored["total"] if monitored else 0),
        "favorites": int(favorites["total"] if favorites else 0),
        "scheduled_job_errors": scheduled_job_errors,
    }


async def _table_exists(db: aiosqlite.Connection, table_name: str) -> bool:
    async with db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ) as cursor:
        row = await cursor.fetchone()
    return row is not None


async def _column_exists(db: aiosqlite.Connection, table_name: str, column_name: str) -> bool:
    async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
        rows = await cursor.fetchall()
    return any(row["name"] == column_name for row in rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local liveness/readiness checks for pain_finder.")
    parser.add_argument(
        "--fail-on-job-errors",
        action="store_true",
        help="Fail when scheduled_job_status contains active errors; use for readiness gates, not Docker liveness.",
    )
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(run_healthcheck(fail_on_job_errors=args.fail_on_job_errors))
    except Exception as exc:
        print(f"healthcheck failed: {exc}")
        return 1
    print(
        "healthcheck ok "
        f"db_path={result['db_path']} "
        f"reports_dir={result['reports_dir']} "
        f"llm_paused={int(result['llm_paused'])} "
        f"monitored={result['monitored']} "
        f"scheduled_job_errors={result['scheduled_job_errors']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
