import aiosqlite
from datetime import datetime, timezone

CREATE_PAIN_POINTS = """
CREATE TABLE IF NOT EXISTS pain_points (
    id INTEGER PRIMARY KEY,
    subreddit TEXT NOT NULL,
    post_id TEXT UNIQUE NOT NULL,
    url TEXT,
    title TEXT,
    body TEXT,
    category TEXT,
    summary TEXT,
    severity TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_MONITORED = """
CREATE TABLE IF NOT EXISTS monitored_subreddits (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    interval_hours INTEGER NOT NULL,
    last_checked TEXT,
    active INTEGER DEFAULT 1
)"""

CREATE_REPORTS = """
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    subreddit TEXT NOT NULL,
    run_at TEXT DEFAULT (datetime('now')),
    post_count INTEGER,
    pain_count INTEGER,
    json_path TEXT
)"""


class Database:
    def __init__(self, path: str = "pain_finder.db"):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def init(self):
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(
            f"{CREATE_PAIN_POINTS}; {CREATE_MONITORED}; {CREATE_REPORTS};"
        )
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    async def insert_pain_point(self, *, subreddit, post_id, url, title, body,
                                 category, summary, severity):
        try:
            await self._conn.execute(
                "INSERT OR IGNORE INTO pain_points "
                "(subreddit, post_id, url, title, body, category, summary, severity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (subreddit, post_id, url, title, body, category, summary, severity),
            )
            await self._conn.commit()
        except Exception:
            pass  # log in production

    async def get_pain_points(self, subreddit: str) -> list[dict]:
        async with self._conn.execute(
            "SELECT * FROM pain_points WHERE subreddit = ? ORDER BY created_at DESC",
            (subreddit,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def add_monitored_subreddit(self, name: str, interval_hours: int):
        await self._conn.execute(
            "INSERT OR REPLACE INTO monitored_subreddits (name, interval_hours) VALUES (?, ?)",
            (name, interval_hours),
        )
        await self._conn.commit()

    async def remove_monitored_subreddit(self, name: str):
        await self._conn.execute(
            "DELETE FROM monitored_subreddits WHERE name = ?", (name,)
        )
        await self._conn.commit()

    async def get_monitored_subreddits(self) -> list[dict]:
        async with self._conn.execute(
            "SELECT * FROM monitored_subreddits WHERE active = 1"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def update_last_checked(self, name: str):
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE monitored_subreddits SET last_checked = ? WHERE name = ?",
            (now, name),
        )
        await self._conn.commit()

    async def save_report(self, *, subreddit, post_count, pain_count, json_path) -> int:
        async with self._conn.execute(
            "INSERT INTO reports (subreddit, post_count, pain_count, json_path) "
            "VALUES (?, ?, ?, ?)",
            (subreddit, post_count, pain_count, json_path),
        ) as cur:
            await self._conn.commit()
            return cur.lastrowid
