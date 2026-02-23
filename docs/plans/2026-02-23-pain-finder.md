# pain_finder Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Reddit pain point scraper controlled via Telegram that extracts complaints, unsolved problems, and feature wishes from any subreddit, analyzes them with an LLM, and stores results in SQLite.

**Architecture:** Single Python asyncio process. Telegram bot handles on-demand `/analyze` commands and passive `/monitor` scheduling. PRAW fetches Reddit posts (falls back to public JSON API if credentials missing). Rule-based filter + OpenRouter LLM classifies pain points. Results stored in SQLite and sent to Telegram.

**Tech Stack:** Python 3.11+, python-telegram-bot v20+, PRAW, httpx, aiosqlite, APScheduler, python-dotenv

---

## Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `config.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create requirements.txt**

```
python-telegram-bot>=20.7
praw>=7.7
httpx>=0.27
aiosqlite>=0.20
apscheduler>=3.10
python-dotenv>=1.0
pytest>=8.0
pytest-asyncio>=0.23
```

**Step 2: Create .env.example**

```
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Reddit (optional — falls back to public JSON API if not set)
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=pain_finder/1.0

OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct:free
```

**Step 3: Create config.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "pain_finder/1.0")

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")

DB_PATH = os.getenv("DB_PATH", "pain_finder.db")
REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")
```

**Step 4: Create tests/conftest.py**

```python
import pytest
import pytest_asyncio

pytest_asyncio_mode = "auto"
```

**Step 5: Create pytest.ini**

```ini
[pytest]
asyncio_mode = auto
```

**Step 6: Install dependencies**

```bash
pip install -r requirements.txt
```

**Step 7: Commit**

```bash
git add requirements.txt .env.example config.py tests/__init__.py tests/conftest.py pytest.ini
git commit -m "feat: project setup — config, deps, test scaffold"
```

---

## Task 2: Database Layer

**Files:**
- Create: `db.py`
- Create: `tests/test_db.py`

**Step 1: Write failing tests**

```python
# tests/test_db.py
import pytest
import aiosqlite
from db import Database

@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.init()
    yield d
    await d.close()

async def test_insert_and_fetch_pain_point(db):
    await db.insert_pain_point(
        subreddit="python",
        post_id="abc123",
        url="https://reddit.com/r/python/abc123",
        title="Why is X so broken",
        body="I can't get X to work",
        category="complaint",
        summary="User frustrated with X",
        severity="medium",
    )
    results = await db.get_pain_points(subreddit="python")
    assert len(results) == 1
    assert results[0]["post_id"] == "abc123"
    assert results[0]["category"] == "complaint"

async def test_duplicate_post_id_ignored(db):
    for _ in range(2):
        await db.insert_pain_point(
            subreddit="python", post_id="dup1", url="", title="T", body="",
            category="complaint", summary="s", severity="low",
        )
    results = await db.get_pain_points(subreddit="python")
    assert len(results) == 1

async def test_monitor_subreddit_crud(db):
    await db.add_monitored_subreddit("webdev", interval_hours=6)
    subs = await db.get_monitored_subreddits()
    assert any(s["name"] == "webdev" for s in subs)

    await db.remove_monitored_subreddit("webdev")
    subs = await db.get_monitored_subreddits()
    assert not any(s["name"] == "webdev" for s in subs)

async def test_update_last_checked(db):
    await db.add_monitored_subreddit("python", interval_hours=12)
    await db.update_last_checked("python")
    subs = await db.get_monitored_subreddits()
    sub = next(s for s in subs if s["name"] == "python")
    assert sub["last_checked"] is not None

async def test_save_report(db):
    report_id = await db.save_report(
        subreddit="python", post_count=50, pain_count=12, json_path="reports/r.json"
    )
    assert report_id > 0
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_db.py -v
```

Expected: `ModuleNotFoundError: No module named 'db'`

**Step 3: Implement db.py**

```python
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
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_db.py -v
```

Expected: all 5 tests PASS

**Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: database layer with SQLite schema and CRUD"
```

---

## Task 3: Reddit Scraper

**Files:**
- Create: `scraper.py`
- Create: `tests/test_scraper.py`

**Step 1: Write failing tests**

```python
# tests/test_scraper.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from scraper import RedditScraper, Post

async def test_fetch_posts_returns_list_of_posts():
    scraper = RedditScraper(client_id="", client_secret="", user_agent="test")
    posts = await scraper.fetch_posts("python", limit=5)
    # With no credentials, falls back to public JSON — mock httpx
    assert isinstance(posts, list)

async def test_post_has_required_fields():
    p = Post(
        post_id="t3_abc",
        subreddit="python",
        title="Why can't I do X",
        body="I've been trying for hours",
        url="https://reddit.com/r/python/t3_abc",
        score=42,
    )
    assert p.post_id == "t3_abc"
    assert p.title == "Why can't I do X"

async def test_fallback_to_public_json(respx_mock):
    import httpx
    respx_mock.get("https://www.reddit.com/r/python/top.json").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "children": [
                    {"data": {
                        "id": "abc1",
                        "title": "Test post",
                        "selftext": "body text",
                        "url": "https://reddit.com/abc1",
                        "score": 10,
                        "subreddit": "python",
                    }}
                ]
            }
        })
    )
    scraper = RedditScraper(client_id="", client_secret="", user_agent="test")
    posts = await scraper._fetch_public_json("python", limit=10)
    assert len(posts) == 1
    assert posts[0].post_id == "abc1"
    assert posts[0].title == "Test post"
```

**Step 2: Install respx for httpx mocking**

Add `respx>=0.21` to requirements.txt then:
```bash
pip install respx
```

**Step 3: Run tests to verify they fail**

```bash
pytest tests/test_scraper.py -v
```

Expected: `ModuleNotFoundError: No module named 'scraper'`

**Step 4: Implement scraper.py**

```python
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

@dataclass
class Post:
    post_id: str
    subreddit: str
    title: str
    body: str
    url: str
    score: int


class RedditScraper:
    def __init__(self, client_id: str, client_secret: str, user_agent: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self._use_praw = bool(client_id and client_secret)

    async def fetch_posts(self, subreddit: str, limit: int = 100, timeframe: str = "day") -> list[Post]:
        if self._use_praw:
            try:
                return await self._fetch_praw(subreddit, limit, timeframe)
            except Exception as e:
                logger.warning(f"PRAW failed ({e}), falling back to public JSON")
        return await self._fetch_public_json(subreddit, limit, timeframe)

    async def _fetch_praw(self, subreddit: str, limit: int, timeframe: str) -> list[Post]:
        import praw
        reddit = praw.Reddit(
            client_id=self.client_id,
            client_secret=self.client_secret,
            user_agent=self.user_agent,
        )
        posts = []
        sub = reddit.subreddit(subreddit)
        for submission in sub.top(time_filter=timeframe, limit=limit):
            posts.append(Post(
                post_id=submission.id,
                subreddit=subreddit,
                title=submission.title,
                body=submission.selftext or "",
                url=f"https://reddit.com{submission.permalink}",
                score=submission.score,
            ))
        return posts

    async def _fetch_public_json(self, subreddit: str, limit: int, timeframe: str = "day") -> list[Post]:
        url = f"https://www.reddit.com/r/{subreddit}/top.json"
        params = {"limit": min(limit, 100), "t": timeframe}
        headers = {"User-Agent": self.user_agent}
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        posts = []
        for child in data.get("data", {}).get("children", []):
            d = child["data"]
            posts.append(Post(
                post_id=d["id"],
                subreddit=subreddit,
                title=d.get("title", ""),
                body=d.get("selftext", ""),
                url=d.get("url", ""),
                score=d.get("score", 0),
            ))
        return posts
```

**Step 5: Run tests to verify they pass**

```bash
pytest tests/test_scraper.py -v
```

Expected: all tests PASS

**Step 6: Commit**

```bash
git add scraper.py tests/test_scraper.py requirements.txt
git commit -m "feat: reddit scraper with PRAW + public JSON fallback"
```

---

## Task 4: OpenRouter Client

**Files:**
- Create: `openrouter.py`
- Create: `tests/test_openrouter.py`

**Step 1: Write failing tests**

```python
# tests/test_openrouter.py
import pytest
import httpx
import respx
from openrouter import OpenRouterClient, AnalysisResult

async def test_analyze_returns_structured_result(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{
                "message": {
                    "content": '{"category": "complaint", "summary": "User frustrated with billing", "severity": "high"}'
                }
            }]
        })
    )
    client = OpenRouterClient(api_key="test-key", model="test-model")
    result = await client.analyze_post(
        title="AWS billing is insane",
        body="I got a $500 bill and have no idea why",
    )
    assert result.category == "complaint"
    assert result.severity == "high"
    assert "billing" in result.summary

async def test_analyze_handles_malformed_json(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "not valid json"}}]
        })
    )
    client = OpenRouterClient(api_key="test-key", model="test-model")
    result = await client.analyze_post(title="Test", body="Test body")
    assert result is None

async def test_analyze_handles_api_error(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(500)
    )
    client = OpenRouterClient(api_key="test-key", model="test-model")
    result = await client.analyze_post(title="Test", body="Test body")
    assert result is None
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_openrouter.py -v
```

Expected: `ModuleNotFoundError: No module named 'openrouter'`

**Step 3: Implement openrouter.py**

```python
import json
import logging
from dataclasses import dataclass
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """Analyze this Reddit post and extract the pain point.

Title: {title}
Body: {body}

Respond with ONLY valid JSON in this exact format:
{{"category": "complaint|unsolved|wish", "summary": "one sentence summary of the pain point", "severity": "low|medium|high"}}

Rules:
- category "complaint": expressing frustration or dissatisfaction
- category "unsolved": asking for help with something they can't figure out
- category "wish": requesting a feature or expressing something they wish existed
- severity based on emotional intensity and upvote potential"""


@dataclass
class AnalysisResult:
    category: str  # complaint | unsolved | wish
    summary: str
    severity: str  # low | medium | high


class OpenRouterClient:
    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def analyze_post(self, title: str, body: str) -> Optional[AnalysisResult]:
        prompt = PROMPT_TEMPLATE.format(title=title, body=body[:1000])
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self.BASE_URL, json=payload, headers=headers)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                return AnalysisResult(
                    category=data["category"],
                    summary=data["summary"],
                    severity=data["severity"],
                )
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
            logger.warning(f"OpenRouter analysis failed: {e}")
            return None
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_openrouter.py -v
```

Expected: all 3 tests PASS

**Step 5: Commit**

```bash
git add openrouter.py tests/test_openrouter.py
git commit -m "feat: openrouter client with structured pain point extraction"
```

---

## Task 5: Classifier

**Files:**
- Create: `classifier.py`
- Create: `tests/test_classifier.py`

**Step 1: Write failing tests**

```python
# tests/test_classifier.py
import pytest
from unittest.mock import AsyncMock
from classifier import Classifier, PainSignal
from scraper import Post
from openrouter import AnalysisResult

def make_post(title="", body="", post_id="p1"):
    return Post(post_id=post_id, subreddit="test", title=title, body=body,
                url="", score=10)

def test_keyword_score_high_for_clear_complaint():
    clf = Classifier(openrouter=None)
    score = clf.keyword_score(make_post(title="I can't get this to work, so frustrated"))
    assert score >= 2

def test_keyword_score_zero_for_neutral():
    clf = Classifier(openrouter=None)
    score = clf.keyword_score(make_post(title="Cool new project announcement"))
    assert score == 0

def test_keyword_score_wish_detected():
    clf = Classifier(openrouter=None)
    score = clf.keyword_score(make_post(title="I wish this had dark mode"))
    assert score >= 1

async def test_classify_skips_llm_for_zero_score():
    mock_llm = AsyncMock()
    clf = Classifier(openrouter=mock_llm)
    result = await clf.classify(make_post(title="Random announcement post"))
    mock_llm.analyze_post.assert_not_called()
    assert result is None

async def test_classify_calls_llm_for_pain_posts():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = AnalysisResult(
        category="complaint", summary="User can't do X", severity="high"
    )
    clf = Classifier(openrouter=mock_llm)
    result = await clf.classify(make_post(title="I can't believe how broken this is"))
    assert result is not None
    assert result.category == "complaint"
    mock_llm.analyze_post.assert_called_once()

async def test_classify_falls_back_to_keyword_category_if_llm_fails():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = None  # LLM failed
    clf = Classifier(openrouter=mock_llm)
    post = make_post(title="I wish this tool had export feature")
    result = await clf.classify(post)
    assert result is not None
    assert result.category in ("complaint", "unsolved", "wish")
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_classifier.py -v
```

Expected: `ModuleNotFoundError: No module named 'classifier'`

**Step 3: Implement classifier.py**

```python
import logging
from dataclasses import dataclass
from typing import Optional
from scraper import Post
from openrouter import OpenRouterClient, AnalysisResult

logger = logging.getLogger(__name__)

COMPLAINT_WORDS = ["can't", "cannot", "broken", "frustrated", "frustrating",
                    "annoying", "hate", "terrible", "awful", "useless", "fail",
                    "failing", "doesn't work", "won't work", "keeps crashing",
                    "impossible", "so bad", "worst"]

UNSOLVED_WORDS = ["how do i", "how can i", "help me", "stuck on", "can't figure",
                   "anyone know", "is there a way", "not sure how", "struggling with"]

WISH_WORDS = ["wish", "would be nice", "feature request", "please add", "why doesn't",
               "why can't", "should have", "needs to have", "lacks", "missing"]


@dataclass
class PainSignal:
    post: Post
    category: str
    summary: str
    severity: str


class Classifier:
    def __init__(self, openrouter: Optional[OpenRouterClient]):
        self.openrouter = openrouter

    def keyword_score(self, post: Post) -> int:
        text = f"{post.title} {post.body}".lower()
        score = 0
        for word in COMPLAINT_WORDS:
            if word in text:
                score += 2
                break
        for word in UNSOLVED_WORDS:
            if word in text:
                score += 1
                break
        for word in WISH_WORDS:
            if word in text:
                score += 1
                break
        return min(score, 3)

    def _keyword_category(self, post: Post) -> str:
        text = f"{post.title} {post.body}".lower()
        if any(w in text for w in WISH_WORDS):
            return "wish"
        if any(w in text for w in UNSOLVED_WORDS):
            return "unsolved"
        return "complaint"

    async def classify(self, post: Post) -> Optional[PainSignal]:
        score = self.keyword_score(post)
        if score == 0:
            return None

        if self.openrouter:
            result: Optional[AnalysisResult] = await self.openrouter.analyze_post(
                title=post.title, body=post.body
            )
            if result:
                return PainSignal(
                    post=post,
                    category=result.category,
                    summary=result.summary,
                    severity=result.severity,
                )

        # Fallback: rule-based
        return PainSignal(
            post=post,
            category=self._keyword_category(post),
            summary=post.title[:120],
            severity="medium" if score >= 2 else "low",
        )

    async def classify_batch(self, posts: list[Post]) -> list[PainSignal]:
        results = []
        for post in posts:
            signal = await self.classify(post)
            if signal:
                results.append(signal)
        return results
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_classifier.py -v
```

Expected: all 6 tests PASS

**Step 5: Commit**

```bash
git add classifier.py tests/test_classifier.py
git commit -m "feat: classifier with keyword scoring and LLM analysis"
```

---

## Task 6: Telegram Bot

**Files:**
- Create: `bot.py`
- Create: `tests/test_bot.py`

**Step 1: Write failing tests**

```python
# tests/test_bot.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot import format_report, parse_analyze_args, parse_monitor_args

def test_parse_analyze_args_subreddit_only():
    subreddit, limit = parse_analyze_args("r/python")
    assert subreddit == "python"
    assert limit == 100

def test_parse_analyze_args_with_limit():
    subreddit, limit = parse_analyze_args("r/startups 50")
    assert subreddit == "startups"
    assert limit == 50

def test_parse_analyze_args_without_r_prefix():
    subreddit, limit = parse_analyze_args("python")
    assert subreddit == "python"

def test_parse_monitor_args():
    subreddit, hours = parse_monitor_args("r/webdev 6h")
    assert subreddit == "webdev"
    assert hours == 6

def test_parse_monitor_args_default_interval():
    subreddit, hours = parse_monitor_args("r/python")
    assert subreddit == "python"
    assert hours == 24

def test_format_report_empty():
    text = format_report("python", [])
    assert "python" in text
    assert "0" in text

def test_format_report_with_results():
    from classifier import PainSignal
    from scraper import Post
    signals = [
        PainSignal(
            post=Post("p1", "python", "Can't import module", "", "", 10),
            category="complaint",
            summary="User can't import module",
            severity="high",
        ),
        PainSignal(
            post=Post("p2", "python", "Wish there was a linter", "", "", 5),
            category="wish",
            summary="User wants a linter",
            severity="low",
        ),
    ]
    text = format_report("python", signals)
    assert "python" in text
    assert "2" in text
    assert "complaint" in text.lower() or "🔴" in text
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_bot.py -v
```

Expected: `ModuleNotFoundError: No module named 'bot'`

**Step 3: Implement bot.py**

```python
import logging
import os
from typing import Optional
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from classifier import Classifier, PainSignal
from scraper import RedditScraper
from db import Database
import config

logger = logging.getLogger(__name__)


def parse_analyze_args(text: str) -> tuple[str, int]:
    parts = text.strip().split()
    subreddit = parts[0].lstrip("r/") if parts else "all"
    limit = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 100
    return subreddit, limit


def parse_monitor_args(text: str) -> tuple[str, int]:
    parts = text.strip().split()
    subreddit = parts[0].lstrip("r/") if parts else "all"
    hours = 24
    if len(parts) > 1:
        raw = parts[1].lower().rstrip("h")
        if raw.isdigit():
            hours = int(raw)
    return subreddit, hours


def format_report(subreddit: str, signals: list[PainSignal]) -> str:
    if not signals:
        return f"📊 r/{subreddit} — 0 pain points found"

    complaints = [s for s in signals if s.category == "complaint"]
    unsolved = [s for s in signals if s.category == "unsolved"]
    wishes = [s for s in signals if s.category == "wish"]

    lines = [f"📊 r/{subreddit} — {len(signals)} pain points found\n"]
    if complaints:
        sample = complaints[0].summary[:80]
        lines.append(f'🔴 Complaints ({len(complaints)}): "{sample}..."')
    if unsolved:
        sample = unsolved[0].summary[:80]
        lines.append(f'🟡 Unsolved ({len(unsolved)}): "{sample}..."')
    if wishes:
        sample = wishes[0].summary[:80]
        lines.append(f'🟢 Wishes ({len(wishes)}): "{sample}..."')
    lines.append("\nFull report saved. Use /export to get the file.")
    return "\n".join(lines)


class PainFinderBot:
    def __init__(self, scraper: RedditScraper, classifier: Classifier, db: Database):
        self.scraper = scraper
        self.classifier = classifier
        self.db = db
        self.app: Optional[Application] = None

    def _is_authorized(self, update: Update) -> bool:
        return update.effective_chat.id == config.TELEGRAM_CHAT_ID

    async def cmd_analyze(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        args = " ".join(ctx.args) if ctx.args else ""
        subreddit, limit = parse_analyze_args(args)
        await update.message.reply_text(f"⏳ Analyzing r/{subreddit} (up to {limit} posts)...")
        try:
            posts = await self.scraper.fetch_posts(subreddit, limit=limit)
            signals = await self.classifier.classify_batch(posts)
            for s in signals:
                await self.db.insert_pain_point(
                    subreddit=subreddit, post_id=s.post.post_id, url=s.post.url,
                    title=s.post.title, body=s.post.body, category=s.category,
                    summary=s.summary, severity=s.severity,
                )
            report = format_report(subreddit, signals)
            await update.message.reply_text(report)
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def cmd_monitor(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        args = " ".join(ctx.args) if ctx.args else ""
        subreddit, hours = parse_monitor_args(args)
        await self.db.add_monitored_subreddit(subreddit, interval_hours=hours)
        await update.message.reply_text(
            f"✅ Now monitoring r/{subreddit} every {hours}h"
        )

    async def cmd_unmonitor(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        args = " ".join(ctx.args) if ctx.args else ""
        subreddit = args.strip().lstrip("r/")
        await self.db.remove_monitored_subreddit(subreddit)
        await update.message.reply_text(f"🗑 Stopped monitoring r/{subreddit}")

    async def cmd_list(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        subs = await self.db.get_monitored_subreddits()
        if not subs:
            await update.message.reply_text("No subreddits being monitored.")
            return
        lines = ["📋 Monitored subreddits:"]
        for s in subs:
            last = s["last_checked"] or "never"
            lines.append(f"  • r/{s['name']} every {s['interval_hours']}h (last: {last})")
        await update.message.reply_text("\n".join(lines))

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        subs = await self.db.get_monitored_subreddits()
        await update.message.reply_text(
            f"🤖 pain_finder running\n{len(subs)} subreddits monitored"
        )

    def build_app(self) -> Application:
        self.app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        self.app.add_handler(CommandHandler("analyze", self.cmd_analyze))
        self.app.add_handler(CommandHandler("monitor", self.cmd_monitor))
        self.app.add_handler(CommandHandler("unmonitor", self.cmd_unmonitor))
        self.app.add_handler(CommandHandler("list", self.cmd_list))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        return self.app
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_bot.py -v
```

Expected: all 8 tests PASS

**Step 5: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat: telegram bot commands and report formatting"
```

---

## Task 7: Scheduler (Passive Monitoring)

**Files:**
- Create: `scheduler.py`
- Create: `tests/test_scheduler.py`

**Step 1: Write failing tests**

```python
# tests/test_scheduler.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from scheduler import MonitoringScheduler

async def test_scheduler_starts_without_error():
    mock_db = AsyncMock()
    mock_db.get_monitored_subreddits.return_value = []
    mock_analyze = AsyncMock()
    sched = MonitoringScheduler(db=mock_db, analyze_fn=mock_analyze)
    sched.start()
    sched.stop()

async def test_load_jobs_creates_job_per_subreddit():
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
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_scheduler.py -v
```

Expected: `ModuleNotFoundError: No module named 'scheduler'`

**Step 3: Implement scheduler.py**

```python
import logging
from typing import Callable, Awaitable
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import Database

logger = logging.getLogger(__name__)


class MonitoringScheduler:
    def __init__(self, db: Database, analyze_fn: Callable[[str], Awaitable[None]]):
        self.db = db
        self.analyze_fn = analyze_fn
        self.scheduler = AsyncIOScheduler()

    def start(self):
        self.scheduler.start()
        logger.info("Scheduler started")

    def stop(self):
        self.scheduler.shutdown(wait=False)

    async def reload_jobs(self):
        # Remove all existing monitoring jobs
        for job in self.scheduler.get_jobs():
            if job.id.startswith("monitor_"):
                job.remove()

        # Re-add from DB
        subs = await self.db.get_monitored_subreddits()
        for sub in subs:
            self.scheduler.add_job(
                self._run_analysis,
                trigger="interval",
                hours=sub["interval_hours"],
                id=f"monitor_{sub['name']}",
                args=[sub["name"]],
                replace_existing=True,
            )
            logger.info(f"Scheduled r/{sub['name']} every {sub['interval_hours']}h")

    async def _run_analysis(self, subreddit: str):
        logger.info(f"Running scheduled analysis for r/{subreddit}")
        try:
            await self.analyze_fn(subreddit)
            await self.db.update_last_checked(subreddit)
        except Exception as e:
            logger.error(f"Scheduled analysis failed for r/{subreddit}: {e}")
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_scheduler.py -v
```

Expected: all 2 tests PASS

**Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: APScheduler passive monitoring for subreddits"
```

---

## Task 8: Main Entrypoint

**Files:**
- Create: `main.py`

> No unit tests for main.py — it's the wiring layer. Verification is the smoke test below.

**Step 1: Implement main.py**

```python
import asyncio
import json
import logging
import os
from datetime import datetime
import config
from db import Database
from scraper import RedditScraper
from openrouter import OpenRouterClient
from classifier import Classifier
from scheduler import MonitoringScheduler
from bot import PainFinderBot, format_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

os.makedirs(config.REPORTS_DIR, exist_ok=True)


async def run():
    # Init components
    db = Database(config.DB_PATH)
    await db.init()

    scraper = RedditScraper(
        client_id=config.REDDIT_CLIENT_ID,
        client_secret=config.REDDIT_CLIENT_SECRET,
        user_agent=config.REDDIT_USER_AGENT,
    )

    openrouter = OpenRouterClient(
        api_key=config.OPENROUTER_API_KEY,
        model=config.OPENROUTER_MODEL,
    )

    classifier = Classifier(openrouter=openrouter)
    bot = PainFinderBot(scraper=scraper, classifier=classifier, db=db)

    async def analyze_and_notify(subreddit: str, limit: int = 100):
        posts = await scraper.fetch_posts(subreddit, limit=limit)
        signals = await classifier.classify_batch(posts)
        for s in signals:
            await db.insert_pain_point(
                subreddit=subreddit, post_id=s.post.post_id, url=s.post.url,
                title=s.post.title, body=s.post.body, category=s.category,
                summary=s.summary, severity=s.severity,
            )
        # Save JSON report
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        json_path = os.path.join(config.REPORTS_DIR, f"{subreddit}_{timestamp}.json")
        with open(json_path, "w") as f:
            json.dump([
                {"post_id": s.post.post_id, "title": s.post.title, "url": s.post.url,
                 "category": s.category, "summary": s.summary, "severity": s.severity}
                for s in signals
            ], f, indent=2)
        await db.save_report(
            subreddit=subreddit, post_count=len(posts),
            pain_count=len(signals), json_path=json_path,
        )
        # Send to Telegram
        app = bot.app
        if app:
            report = format_report(subreddit, signals)
            await app.bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=report)

    scheduler = MonitoringScheduler(db=db, analyze_fn=analyze_and_notify)
    scheduler.start()
    await scheduler.reload_jobs()

    tg_app = bot.build_app()
    logger.info("pain_finder starting...")
    async with tg_app:
        await tg_app.start()
        await tg_app.updater.start_polling()
        logger.info("Bot is running. Send /status in Telegram to verify.")
        # Keep running
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run())
```

**Step 2: Run full test suite**

```bash
pytest -v
```

Expected: all tests PASS

**Step 3: Commit**

```bash
git add main.py
git commit -m "feat: main entrypoint — wires all components and starts bot"
```

---

## Task 9: Design Doc & Final Commit

**Step 1: Verify docs/plans directory exists**

```bash
ls docs/plans/
```

**Step 2: Commit design doc**

```bash
git add docs/plans/2026-02-23-pain-finder.md
git commit -m "docs: add pain_finder design document"
```

---

## Smoke Test (Manual Verification)

1. Copy `.env.example` to `.env`, fill in `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OPENROUTER_API_KEY`
2. Run: `python main.py`
3. In Telegram, send: `/analyze r/python 10`
4. Verify: Telegram reply with pain point summary
5. Verify: `reports/` contains a JSON file
6. Verify: `pain_finder.db` contains rows in `pain_points` table: `sqlite3 pain_finder.db "SELECT category, summary FROM pain_points LIMIT 5;"`
7. Test fallback: clear `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`, re-run `/analyze r/python 5` — should still work
8. Test monitoring: send `/monitor r/python 1h`, then `/list` — verify subreddit appears
9. Test error path: send `/analyze r/thisdoesnotexist12345` — verify graceful error message
