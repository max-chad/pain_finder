# Grouped Notifications Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current per-message notification flood with a single grouped Telegram message per analysis run — showing 5 condensed pain points, numbered selection buttons, in-place card expansion, and Load More pagination.

**Architecture:** All logic lives in `bot.py` (session dict, renderers, new callback branches, updated `cmd_analyze`, new public `send_grouped_notification`). `main.py` is updated to call `bot.send_grouped_notification` instead of raw `send_message`. No new files needed.

**Tech Stack:** python-telegram-bot v20+, aiosqlite, pytest-asyncio

---

### Task 1: Session infrastructure

Add in-memory session storage and lifecycle helpers to `PainFinderBot`.

**Files:**
- Modify: `bot.py` — `__init__`, add `_evict_old_sessions`, `_create_session`
- Test: `tests/test_bot.py`

**Step 1: Write failing tests**

Add these tests to the bottom of `tests/test_bot.py`:

```python
import time as _time

def _make_bot() -> PainFinderBot:
    """Minimal PainFinderBot for unit tests (no Telegram app)."""
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=AsyncMock())
    bot._is_authorized = lambda update: True
    return bot


def test_sessions_dict_initialized_empty():
    bot = _make_bot()
    assert bot._sessions == {}


def test_create_session_returns_8char_token_and_stores_session():
    bot = _make_bot()
    signals = [_make_signal("p1", "complaint", "Something is broken")]
    token = bot._create_session(signals, "r/python")
    assert len(token) == 8
    assert token in bot._sessions
    session = bot._sessions[token]
    assert session["label"] == "r/python"
    assert len(session["signals"]) == 1
    assert session["shown_count"] == 1  # min(5, 1)


def test_create_session_sorts_signals_by_wtp_desc():
    bot = _make_bot()
    low = _make_signal("p_low", "complaint", "Low WTP")
    high = _make_signal("p_high", "complaint", "High WTP")
    low.willingness_to_pay = 3
    high.willingness_to_pay = 9
    token = bot._create_session([low, high], "r/python")
    assert bot._sessions[token]["signals"][0].post.post_id == "p_high"


def test_evict_old_sessions_removes_expired():
    bot = _make_bot()
    signals = [_make_signal("p1", "complaint", "x")]
    token = bot._create_session(signals, "r/python")
    # Backdate the session
    bot._sessions[token]["created_at"] = _time.time() - 86401
    # Trigger eviction by creating a new session
    bot._create_session(signals, "r/python")
    assert token not in bot._sessions


def test_evict_old_sessions_keeps_recent():
    bot = _make_bot()
    signals = [_make_signal("p1", "complaint", "x")]
    token = bot._create_session(signals, "r/python")
    bot._create_session(signals, "r/python")  # trigger eviction
    assert token in bot._sessions  # recent session kept
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_bot.py::test_sessions_dict_initialized_empty -v
```
Expected: `AttributeError: 'PainFinderBot' object has no attribute '_sessions'`

**Step 3: Implement in `bot.py`**

In `PainFinderBot.__init__`, after `self.app = None`, add:

```python
        self._sessions: dict[str, dict] = {}
```

After `__init__`, add two new methods:

```python
    def _evict_old_sessions(self) -> None:
        import time
        cutoff = time.time() - 86400  # 24 hours
        expired = [t for t, s in self._sessions.items() if s["created_at"] < cutoff]
        for t in expired:
            del self._sessions[t]

    def _create_session(self, signals: list["PainSignal"], label: str) -> str:
        import time
        import uuid
        self._evict_old_sessions()
        token = uuid.uuid4().hex[:8]
        sorted_signals = sorted(signals, key=lambda s: (s.willingness_to_pay, s.pain_level), reverse=True)
        self._sessions[token] = {
            "signals": sorted_signals,
            "label": label,
            "created_at": time.time(),
            "shown_count": min(5, len(sorted_signals)),
        }
        return token
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_bot.py::test_sessions_dict_initialized_empty tests/test_bot.py::test_create_session_returns_8char_token_and_stores_session tests/test_bot.py::test_create_session_sorts_signals_by_wtp_desc tests/test_bot.py::test_evict_old_sessions_removes_expired tests/test_bot.py::test_evict_old_sessions_keeps_recent -v
```
Expected: `5 passed`

**Step 5: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat(bot): add session storage infrastructure for grouped notifications"
```

---

### Task 2: List and card view renderers

Two private methods that build the Telegram message text and inline keyboard for each view.

**Files:**
- Modify: `bot.py` — add `_render_list_view`, `_render_card_view`
- Test: `tests/test_bot.py`

**Step 1: Write failing tests**

```python
def test_render_list_view_contains_label_and_items():
    bot = _make_bot()
    signals = [_make_signal(f"p{i}", "complaint", f"Issue number {i}") for i in range(7)]
    for i, s in enumerate(signals):
        s.willingness_to_pay = 9 - i
    token = bot._create_session(signals, "r/python")
    session = bot._sessions[token]
    text, keyboard = bot._render_list_view(token, session)
    assert "r/python" in text
    assert "7 pain points" in text
    assert "1." in text
    assert "5." in text
    assert "6." not in text  # only 5 shown initially
    # Load more button present
    buttons_flat = [btn.text for row in keyboard.inline_keyboard for btn in row]
    assert any("Load more" in b for b in buttons_flat)
    # 5 numbered buttons
    assert any(b == "1" for b in buttons_flat)
    assert any(b == "5" for b in buttons_flat)


def test_render_list_view_no_load_more_when_all_shown():
    bot = _make_bot()
    signals = [_make_signal(f"p{i}", "complaint", f"Issue {i}") for i in range(3)]
    token = bot._create_session(signals, "HN")
    session = bot._sessions[token]
    text, keyboard = bot._render_list_view(token, session)
    buttons_flat = [btn.text for row in keyboard.inline_keyboard for btn in row]
    assert not any("Load more" in b for b in buttons_flat)


def test_render_card_view_contains_post_details():
    bot = _make_bot()
    signal = _make_signal("post_abc", "complaint", "Really annoying bug")
    signal.willingness_to_pay = 8
    signal.pain_level = 9
    token = bot._create_session([signal], "r/python")
    session = bot._sessions[token]
    text, keyboard = bot._render_card_view(token, session, 0)
    assert "Really annoying bug" in text
    assert "WTP: 8/10" in text
    assert "Pain: 9/10" in text
    # Back button present
    buttons_flat = [btn.text for row in keyboard.inline_keyboard for btn in row]
    assert any("Back" in b for b in buttons_flat)
    # Favorite and Discard buttons present
    assert any("Favorite" in b for b in buttons_flat)
    assert any("Discard" in b for b in buttons_flat)


def test_sel_callback_data_format():
    """sel: callback_data stays within Telegram's 64-byte limit."""
    bot = _make_bot()
    signal = _make_signal("p1", "complaint", "x")
    token = bot._create_session([signal], "r/python")
    session = bot._sessions[token]
    _, keyboard = bot._render_list_view(token, session)
    cb = keyboard.inline_keyboard[0][0].callback_data
    assert cb.startswith("sel:")
    assert len(cb.encode()) <= 64
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_bot.py::test_render_list_view_contains_label_and_items -v
```
Expected: `AttributeError: 'PainFinderBot' object has no attribute '_render_list_view'`

**Step 3: Implement in `bot.py`**

Add after `_create_session`:

```python
    def _render_list_view(self, token: str, session: dict) -> tuple[str, "InlineKeyboardMarkup"]:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        signals: list[PainSignal] = session["signals"]
        shown: int = session["shown_count"]
        label: str = session["label"]
        total = len(signals)
        monetizable = sum(1 for s in signals if s.is_monetizable)
        divider = "\u2500" * 42

        lines = [
            f"\U0001f4ca {label} \u2014 {total} pain point{'s' if total != 1 else ''} ({monetizable} monetizable)",
            divider,
        ]
        for i, signal in enumerate(signals[:shown], start=1):
            icon = _signal_icon(signal)
            summary = signal.summary[:55] + "\u2026" if len(signal.summary) > 55 else signal.summary
            lines.append(f"{i}. {icon} WTP:{signal.willingness_to_pay} | {summary}")
        lines += [divider, "Tap a number to see full details."]

        num_buttons = [
            InlineKeyboardButton(str(i), callback_data=f"sel:{token}:{i - 1}")
            for i in range(1, shown + 1)
        ]
        keyboard_rows: list[list] = [num_buttons]
        remaining = total - shown
        if remaining > 0:
            keyboard_rows.append([
                InlineKeyboardButton(
                    f"Load more \u2193  ({remaining} remaining)",
                    callback_data=f"loadmore:{token}",
                )
            ])
        return "\n".join(lines), InlineKeyboardMarkup(keyboard_rows)

    def _render_card_view(self, token: str, session: dict, idx: int) -> tuple[str, "InlineKeyboardMarkup"]:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        signals: list[PainSignal] = session["signals"]
        label: str = session["label"]
        signal = signals[idx]
        total = len(signals)
        icon = _signal_icon(signal)
        competitors = ", ".join(signal.competitor_tags[:3]) if signal.competitor_tags else "none"
        divider = "\u2500" * 42

        lines = [
            f"\U0001f4ca {label} \u2192 Item {idx + 1} of {total}",
            divider,
            f"{icon} [{signal.post.source}] {signal.post.title}",
            f"WTP: {signal.willingness_to_pay}/10 | Pain: {signal.pain_level}/10",
            f"Niche: {signal.niche_category or 'Uncategorized'} | Competitors: {competitors}",
            signal.summary,
            signal.post.url,
        ]
        keyboard_rows = [
            [
                InlineKeyboardButton("\u2b50 Favorite", callback_data=f"triage:favorite:{signal.post.post_id}"),
                InlineKeyboardButton("\u2717 Discard", callback_data=f"triage:discard:{signal.post.post_id}"),
            ],
            [
                InlineKeyboardButton(
                    "\U0001f48e Deep Dive",
                    callback_data=f"deepdive:{signal.post.post_id}:{signal.post.subreddit}",
                ),
                InlineKeyboardButton(
                    "\U0001f4e6 GTM",
                    callback_data=f"gtm:{signal.post.post_id}:{signal.post.source}",
                ),
            ],
            [InlineKeyboardButton("\u2190 Back to list", callback_data=f"back:{token}")],
        ]
        return "\n".join(lines), InlineKeyboardMarkup(keyboard_rows)
```

Note: `_signal_icon` is the existing module-level function — no change needed.

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_bot.py::test_render_list_view_contains_label_and_items tests/test_bot.py::test_render_list_view_no_load_more_when_all_shown tests/test_bot.py::test_render_card_view_contains_post_details tests/test_bot.py::test_sel_callback_data_format -v
```
Expected: `4 passed`

**Step 5: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat(bot): add list-view and card-view renderers for grouped notifications"
```

---

### Task 3: Public `send_grouped_notification` and private `_send_grouped_notification_reply`

These methods create a session and send the initial message — one for chat_id sends (scheduled jobs), one for replies (manual /analyze).

**Files:**
- Modify: `bot.py` — add two new methods
- Test: `tests/test_bot.py`

**Step 1: Write failing tests**

```python
async def test_send_grouped_notification_creates_session_and_sends_message():
    bot = _make_bot()
    bot.app = SimpleNamespace(bot=AsyncMock())
    signals = [_make_signal(f"p{i}", "complaint", f"Issue {i}") for i in range(6)]
    await bot.send_grouped_notification(chat_id=42, signals=signals, label="r/python")
    assert len(bot._sessions) == 1
    bot.app.bot.send_message.assert_awaited_once()
    call_kwargs = bot.app.bot.send_message.call_args
    assert call_kwargs.kwargs["chat_id"] == 42
    assert "r/python" in call_kwargs.kwargs["text"]


async def test_send_grouped_notification_empty_signals_sends_plain_text():
    bot = _make_bot()
    bot.app = SimpleNamespace(bot=AsyncMock())
    await bot.send_grouped_notification(chat_id=42, signals=[], label="HN")
    assert len(bot._sessions) == 0
    bot.app.bot.send_message.assert_awaited_once()
    text = bot.app.bot.send_message.call_args.kwargs["text"]
    assert "No pain points" in text


async def test_send_grouped_notification_single_signal_sends_card_directly():
    bot = _make_bot()
    bot.app = SimpleNamespace(bot=AsyncMock())
    signals = [_make_signal("p1", "complaint", "Only one issue")]
    await bot.send_grouped_notification(chat_id=42, signals=signals, label="r/rust")
    # Card view has "Item 1 of 1"
    text = bot.app.bot.send_message.call_args.kwargs["text"]
    assert "Item 1 of 1" in text


async def test_send_grouped_notification_reply_sends_list_view():
    bot = _make_bot()
    signals = [_make_signal(f"p{i}", "complaint", f"Issue {i}") for i in range(6)]
    update = _make_update()
    await bot._send_grouped_notification_reply(update, signals, "r/python")
    assert len(bot._sessions) == 1
    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args.args[0]
    assert "r/python" in text
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_bot.py::test_send_grouped_notification_creates_session_and_sends_message -v
```
Expected: `AttributeError: 'PainFinderBot' object has no attribute 'send_grouped_notification'`

**Step 3: Implement in `bot.py`**

Add after `_render_card_view`:

```python
    async def send_grouped_notification(
        self, *, chat_id: int, signals: list["PainSignal"], label: str
    ) -> None:
        if not self.app:
            return
        if not signals:
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=f"\U0001f4ca {label} \u2014 No pain points found.",
            )
            return
        token = self._create_session(signals, label)
        session = self._sessions[token]
        if len(session["signals"]) == 1:
            text, keyboard = self._render_card_view(token, session, 0)
        else:
            text, keyboard = self._render_list_view(token, session)
        await self.app.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)

    async def _send_grouped_notification_reply(
        self, update, signals: list["PainSignal"], label: str
    ) -> None:
        if update.message is None:
            return
        if not signals:
            await update.message.reply_text(f"\U0001f4ca {label} \u2014 No pain points found.")
            return
        token = self._create_session(signals, label)
        session = self._sessions[token]
        if len(session["signals"]) == 1:
            text, keyboard = self._render_card_view(token, session, 0)
        else:
            text, keyboard = self._render_list_view(token, session)
        await update.message.reply_text(text, reply_markup=keyboard)
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_bot.py::test_send_grouped_notification_creates_session_and_sends_message tests/test_bot.py::test_send_grouped_notification_empty_signals_sends_plain_text tests/test_bot.py::test_send_grouped_notification_single_signal_sends_card_directly tests/test_bot.py::test_send_grouped_notification_reply_sends_list_view -v
```
Expected: `4 passed`

**Step 5: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat(bot): add send_grouped_notification and reply variant"
```

---

### Task 4: New callback branches in `on_callback_query`

Handle `sel:TOKEN:IDX`, `loadmore:TOKEN`, and `back:TOKEN` by editing the existing message in-place. Unknown tokens produce a toast.

**Files:**
- Modify: `bot.py` — `on_callback_query`
- Test: `tests/test_bot.py`

**Step 1: Write failing tests**

```python
def _make_callback_update(data: str):
    msg = AsyncMock()
    query = AsyncMock()
    query.data = data
    query.message = msg
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        message=None,
        callback_query=query,
    )


async def test_sel_callback_edits_message_to_card_view():
    bot = _make_bot()
    signals = [_make_signal(f"p{i}", "complaint", f"Issue {i}") for i in range(5)]
    token = bot._create_session(signals, "r/python")

    update = _make_callback_update(f"sel:{token}:0")
    await bot.on_callback_query(update, None)

    update.callback_query.edit_message_text.assert_awaited_once()
    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "Item 1 of 5" in text


async def test_loadmore_callback_shows_more_items():
    bot = _make_bot()
    signals = [_make_signal(f"p{i}", "complaint", f"Issue {i}") for i in range(8)]
    token = bot._create_session(signals, "r/python")
    assert bot._sessions[token]["shown_count"] == 5

    update = _make_callback_update(f"loadmore:{token}")
    await bot.on_callback_query(update, None)

    assert bot._sessions[token]["shown_count"] == 8  # min(5+5, 8)
    update.callback_query.edit_message_text.assert_awaited_once()


async def test_back_callback_returns_to_list_view():
    bot = _make_bot()
    signals = [_make_signal(f"p{i}", "complaint", f"Issue {i}") for i in range(5)]
    token = bot._create_session(signals, "r/python")

    update = _make_callback_update(f"back:{token}")
    await bot.on_callback_query(update, None)

    update.callback_query.edit_message_text.assert_awaited_once()
    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "r/python" in text
    assert "Tap a number" in text


async def test_unknown_token_shows_expired_toast():
    bot = _make_bot()
    update = _make_callback_update("sel:deadbeef:0")
    await bot.on_callback_query(update, None)

    update.callback_query.answer.assert_awaited_once()
    call = update.callback_query.answer.call_args
    assert "expired" in (call.args[0] if call.args else call.kwargs.get("text", "")).lower()
    assert call.kwargs.get("show_alert") is True
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_bot.py::test_sel_callback_edits_message_to_card_view -v
```
Expected: `AssertionError` — `edit_message_text` not called (unknown callback prefix hits the `"Unsupported action"` branch).

**Step 3: Implement in `bot.py`**

In `on_callback_query`, insert these three blocks **before** the existing `if data.startswith("triage:")` check:

```python
            if data.startswith("sel:"):
                parts = data.split(":", 2)
                if len(parts) != 3:
                    await query.answer("Malformed callback", show_alert=False)
                    return
                _, token, idx_str = parts
                session = self._sessions.get(token)
                if session is None:
                    await query.answer("Session expired \u2014 re-run the command.", show_alert=True)
                    return
                try:
                    idx = int(idx_str)
                except ValueError:
                    await query.answer("Malformed callback", show_alert=False)
                    return
                if not (0 <= idx < len(session["signals"])):
                    await query.answer("Item out of range", show_alert=False)
                    return
                text, keyboard = self._render_card_view(token, session, idx)
                try:
                    await query.edit_message_text(text, reply_markup=keyboard)
                except Exception:
                    await query.answer("Could not update message \u2014 try again.", show_alert=True)
                    return
                await query.answer()
                return

            if data.startswith("loadmore:"):
                token = data[len("loadmore:"):]
                session = self._sessions.get(token)
                if session is None:
                    await query.answer("Session expired \u2014 re-run the command.", show_alert=True)
                    return
                total = len(session["signals"])
                session["shown_count"] = min(session["shown_count"] + 5, total)
                text, keyboard = self._render_list_view(token, session)
                try:
                    await query.edit_message_text(text, reply_markup=keyboard)
                except Exception:
                    await query.answer("Could not update message \u2014 try again.", show_alert=True)
                    return
                await query.answer()
                return

            if data.startswith("back:"):
                token = data[len("back:"):]
                session = self._sessions.get(token)
                if session is None:
                    await query.answer("Session expired \u2014 re-run the command.", show_alert=True)
                    return
                text, keyboard = self._render_list_view(token, session)
                try:
                    await query.edit_message_text(text, reply_markup=keyboard)
                except Exception:
                    await query.answer("Could not update message \u2014 try again.", show_alert=True)
                    return
                await query.answer()
                return
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_bot.py::test_sel_callback_edits_message_to_card_view tests/test_bot.py::test_loadmore_callback_shows_more_items tests/test_bot.py::test_back_callback_returns_to_list_view tests/test_bot.py::test_unknown_token_shows_expired_toast -v
```
Expected: `4 passed`

**Step 5: Run the full bot test suite to check for regressions**

```bash
pytest tests/test_bot.py -q
```
Expected: all existing tests still pass.

**Step 6: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat(bot): add sel/loadmore/back callback handlers for grouped notification"
```

---

### Task 5: Migrate `cmd_analyze` to grouped notification

Replace the two-call `format_report + _send_top_signal_cards` pattern with `_send_grouped_notification_reply`.

**Files:**
- Modify: `bot.py` — `cmd_analyze`
- Test: `tests/test_bot.py` — update existing `test_cmd_analyze_uses_injected_pipeline_and_sends_cards`

**Step 1: Update the existing test**

The existing test `test_cmd_analyze_uses_injected_pipeline_and_sends_cards` checks that `_send_top_signal_cards` is called and `reply_text` is called twice (once for "Analyzing…" and once for `format_report`). After migration, it should check for `_send_grouped_notification_reply` instead.

Replace the existing test:

```python
async def test_cmd_analyze_uses_grouped_notification(monkeypatch):
    run = SimpleNamespace(signals=[_make_signal("p1", "complaint", "Broken install")])
    analyze_fn = AsyncMock(return_value=run)
    bot = PainFinderBot(
        scraper=AsyncMock(),
        classifier=AsyncMock(),
        db=AsyncMock(),
        analyze_fn=analyze_fn,
    )
    bot._is_authorized = lambda update: True

    grouped = AsyncMock()
    monkeypatch.setattr(bot, "_send_grouped_notification_reply", grouped)

    update = _make_update()
    ctx = _make_ctx(["r/python", "10"])
    await bot.cmd_analyze(update, ctx)

    analyze_fn.assert_awaited_once_with("python", 10)
    grouped.assert_awaited_once()
    call_kwargs = grouped.call_args
    assert call_kwargs.args[0] is update or call_kwargs.kwargs.get("update") is update
```

**Step 2: Run the old test to verify it still passes (not yet broken)**

```bash
pytest tests/test_bot.py::test_cmd_analyze_uses_injected_pipeline_and_sends_cards -v
```

**Step 3: Migrate `cmd_analyze` in `bot.py`**

Find these two lines in `cmd_analyze` (currently lines 235–236):

```python
            await update.message.reply_text(format_report(subreddit, signals))
            await self._send_top_signal_cards(update, signals)
```

Replace with:

```python
            await self._send_grouped_notification_reply(update, signals, f"r/{subreddit}")
```

**Step 4: Run the updated test**

```bash
pytest tests/test_bot.py::test_cmd_analyze_uses_grouped_notification -v
```
Expected: `PASSED`

**Step 5: Run full bot test suite**

```bash
pytest tests/test_bot.py -q
```
Expected: all pass (the old `test_cmd_analyze_uses_injected_pipeline_and_sends_cards` will be gone, replaced by `test_cmd_analyze_uses_grouped_notification`).

**Step 6: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat(bot): migrate cmd_analyze to grouped notification"
```

---

### Task 6: Wire `main.py` to use `bot.send_grouped_notification`

Replace all three raw `send_message` calls in scheduled jobs with the new method.

**Files:**
- Modify: `main.py` — `analyze_and_notify`, `run_hn_job`, `run_reviews_job`
- Also remove: `from bot import format_report` import in `main.py` if present
- Test: `tests/test_main.py`

**Step 1: Check existing test_main.py for tests to update**

```bash
grep -n "format_report\|send_message\|analyze_and_notify\|run_hn_job\|run_reviews_job" tests/test_main.py | head -20
```

Note which tests cover these functions — they will need to be updated.

**Step 2: Write new/updated tests in `tests/test_main.py`**

Find and update any test that asserts `send_message` is called with `format_report` output. The assertion should now check that `bot.send_grouped_notification` is called:

```python
# Typical pattern — adjust based on what test_main.py currently looks like:
async def test_analyze_and_notify_calls_grouped_notification(monkeypatch):
    # Find the analyze_and_notify closure by inspecting test_main.py structure
    # and update it to assert send_grouped_notification is called, not send_message
    pass  # fill in after reading the existing test
```

**Concrete guidance:** In `tests/test_main.py`, find tests that call `analyze_and_notify` or check `bot.app.bot.send_message`. Update them to check `bot.send_grouped_notification` is awaited with the right `label` argument.

**Step 3: Implement in `main.py`**

Find `analyze_and_notify` (around line 143) and replace:

```python
    async def analyze_and_notify(subreddit: str) -> None:
        run_result = await pipeline.analyze_subreddit(subreddit=subreddit, limit=100)
        if bot.app:
            await bot.app.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=format_report(subreddit, run_result.signals),
            )
```

with:

```python
    async def analyze_and_notify(subreddit: str) -> None:
        run_result = await pipeline.analyze_subreddit(subreddit=subreddit, limit=100)
        await bot.send_grouped_notification(
            chat_id=config.TELEGRAM_CHAT_ID,
            signals=run_result.signals,
            label=f"r/{subreddit}",
        )
```

Find `run_hn_job` and replace:

```python
        if bot.app and run_result.pain_count:
            await bot.app.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=f"HN ingestion: {run_result.post_count} posts scanned, {run_result.pain_count} pain points found.",
            )
```

with:

```python
        if run_result.pain_count:
            await bot.send_grouped_notification(
                chat_id=config.TELEGRAM_CHAT_ID,
                signals=run_result.signals,
                label="HN",
            )
```

Find `run_reviews_job` and replace:

```python
        if bot.app and run_result.pain_count:
            await bot.app.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=f"Review ingestion: {run_result.post_count} reviews scanned, {run_result.pain_count} pain points found.",
            )
```

with:

```python
        if run_result.pain_count:
            await bot.send_grouped_notification(
                chat_id=config.TELEGRAM_CHAT_ID,
                signals=run_result.signals,
                label="Reviews",
            )
```

Also check whether `main.py` imports `format_report` from `bot`:

```bash
grep "from bot import\|import format_report" main.py
```

If `format_report` is imported there, remove it from the import line (it is no longer used in `main.py`).

**Step 4: Run test_main.py**

```bash
pytest tests/test_main.py -q
```
Expected: all pass.

**Step 5: Run all tests**

```bash
pytest -q
```
Expected: all pass.

**Step 6: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat(main): wire scheduled jobs to bot.send_grouped_notification"
```

---

### Task 7: Quality gates

**Step 1: Lint**

```bash
python -m ruff check .
```
Expected: `All checks passed!`

If any F401 unused-import errors appear (e.g. `format_report` still imported somewhere): remove them.

**Step 2: Type check**

```bash
python -m mypy .
```
Expected: `Success: no issues found in 17 source files`

If mypy complains about the new methods (e.g. missing return type annotation on `_render_list_view`):

Add return type to the two renderer methods:
```python
    def _render_list_view(self, token: str, session: dict) -> "tuple[str, InlineKeyboardMarkup]":
```
(You may need `from telegram import InlineKeyboardMarkup` inside the `TYPE_CHECKING` guard or as a local import.)

**Step 3: Full test suite with coverage**

```bash
pytest --cov=. --cov-fail-under=80 -q
```
Expected: all pass, coverage ≥ 80%.

**Step 4: Commit lint/type fixes if any**

```bash
git add -p  # stage only what changed
git commit -m "fix: ruff/mypy cleanup for grouped notifications"
```
