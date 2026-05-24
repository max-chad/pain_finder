from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any


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


async def run_healthcheck() -> dict[str, Any]:
    import config
    from db import Database

    _assert_writable_dir(config.REPORTS_DIR)

    db_parent = Path(config.DB_PATH).expanduser().resolve().parent
    _assert_writable_dir(str(db_parent))

    db = Database(config.DB_PATH)
    await db.init()
    try:
        flags = await db.get_runtime_flags()
        summary = await db.get_monitoring_summary()
    finally:
        await db.close()

    return {
        "ok": True,
        "db_path": config.DB_PATH,
        "reports_dir": config.REPORTS_DIR,
        "llm_paused": bool(flags.get("llm_paused", 0)),
        "monitored": int(summary.get("monitored", 0)),
    }


def main() -> int:
    try:
        result = asyncio.run(run_healthcheck())
    except Exception as exc:
        print(f"healthcheck failed: {exc}")
        return 1
    print(
        "healthcheck ok "
        f"db_path={result['db_path']} "
        f"reports_dir={result['reports_dir']} "
        f"llm_paused={int(result['llm_paused'])} "
        f"monitored={result['monitored']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
