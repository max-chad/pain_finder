# Grouped Notifications Design

**Date:** 2026-02-28
**Status:** Approved
**Feature:** Telegram grouped / paginated notifications

## Problem

Every analysis run (scheduled subreddits, HN, reviews, manual `/analyze`) produces either a plain-text dump or a flood of up to 6 separate messages. With multiple monitored subreddits and background jobs, the Telegram chat fills with noise and actionable items get lost.

## Solution

Replace all notification paths with a single grouped message per run. The message shows 5 condensed results with numbered selection buttons. Tapping a number edits the message in-place to show the full pain-point card with existing action buttons (Favorite, Discard, Deep Dive, GTM). A "Load more" button reveals the next 5 results. A "Back to list" button returns to the list view.

## Approach Chosen

**Approach A — Grouped list with item selection and Load More** (recommended and approved).

Rejected alternatives:
- B — Compact summary only: loses inline triage convenience
- C — Single-message carousel: shows less information per screen

---

## Architecture

All changes are confined to `bot.py` and `main.py`. No new files needed.

### `bot.py` changes

1. **`PainFinderBot.__init__`** adds `self._sessions: dict[str, dict]`.

2. **New public method** `send_grouped_notification(chat_id, signals, label)`:
   - Filters out discarded signals upfront.
   - If 0 signals: sends plain text "No pain points found."
   - If 1 signal: sends card view directly (skips list).
   - If ≥ 2 signals: creates session token, stores session, sends grouped list message.

3. **New private method** `_send_grouped_notification_reply(update, signals, label)`:
   - Same logic as above but uses `update.message.reply_text` instead of `bot.send_message`.
   - Used by `cmd_analyze`.

4. **`on_callback_query` grows 3 new branches** (before the existing `triage:` branch):
   - `sel:TOKEN:IDX` — edit message to card view for item at index IDX.
   - `loadmore:TOKEN` — increment `shown_count` by 5, edit message to updated list.
   - `back:TOKEN` — edit message back to list view.

5. **`cmd_analyze`** replaces `format_report + _send_top_signal_cards` with `_send_grouped_notification_reply`.

6. `format_report` and `_send_top_signal_cards` are **kept but no longer called** from analysis flows. Cleanup deferred.

### `main.py` changes

| Job | Old | New |
|-----|-----|-----|
| `analyze_and_notify` | `send_message(format_report(signals))` | `bot.send_grouped_notification(chat_id, signals, f"r/{subreddit}")` |
| `run_hn_job` | `send_message("HN ingestion: N posts…")` | `bot.send_grouped_notification(chat_id, run_result.signals, "HN")` |
| `run_reviews_job` | `send_message("Review ingestion: N posts…")` | `bot.send_grouped_notification(chat_id, run_result.signals, "Reviews")` |

---

## State Management

### Session object

```python
{
    "signals":     list[PainSignal],  # sorted by (WTP desc, pain_level desc), discarded filtered out
    "label":       str,               # e.g. "r/python", "HN", "Reviews"
    "created_at":  float,             # time.time()
    "shown_count": int,               # how many items currently visible in list
}
```

### Token

8-char hex from `uuid.uuid4().hex[:8]`. Fits callback data comfortably:
- `sel:12345678:99` = 16 bytes (limit: 64 bytes)
- `loadmore:12345678` = 18 bytes
- `back:12345678` = 13 bytes

### Eviction

Lazy — called once per new session creation. Removes sessions older than 24 hours.

### Restart behavior

Sessions are lost on restart. Unknown tokens receive a toast: `"Session expired — re-run the command."` No crash.

### Memory estimate

100 posts × ~500 bytes × 50 concurrent sessions ≈ 2.5 MB. Negligible.

---

## Message Format

### List view

```
📊 r/python — 12 pain points (7 monetizable)
──────────────────────────────────────────
1. 💰 WTP:9 | Stripe webhooks unreliable
2. 🔴 WTP:7 | No good ETL tooling for SMBs
3. 🔴 WTP:6 | Auth library chaos
4. 🟡 WTP:5 | API rate limits docs outdated
5. ⬜ WTP:3 | Better test coverage needed
──────────────────────────────────────────
Tap a number to see full details.
```

Keyboard:
- Row 1: `[1]  [2]  [3]  [4]  [5]`
- Row 2: `[Load more ↓  (7 remaining)]` — only if more items exist

### Card view

```
📊 r/python → Item 2 of 12
──────────────────────────────────────────
🔴 [hn] No good ETL tooling for SMBs
WTP: 7/10 | Pain: 7/10
Niche: DevOps | Competitors: Airbyte, Fivetran
Internal teams building ETL are frustrated by the lack of...
https://news.ycombinator.com/item?id=123
```

Keyboard:
- Row 1: `[⭐ Favorite]  [✗ Discard]`
- Row 2: `[💎 Deep Dive]  [📦 GTM]`
- Row 3: `[← Back to list]`

After a triage action the card re-renders with status shown (e.g. `✅ Favorited`).

### WTP icon mapping

| Icon | Condition |
|------|-----------|
| 💰 | `is_monetizable` and `WTP >= 8` |
| 🔴 | `WTP` 6–7 |
| 🟡 | `WTP` 4–5 |
| ⬜ | `WTP` < 4 |

---

## Callback Data Protocol

New branches (parsed before existing branches in `on_callback_query`):

| Action | Format | Max length |
|--------|--------|------------|
| Select item | `sel:TOKEN:IDX` | 16 bytes |
| Load more | `loadmore:TOKEN` | 18 bytes |
| Back to list | `back:TOKEN` | 13 bytes |

Existing callbacks (`triage:`, `deepdive:`, `gtm:`) are unchanged.

---

## Error Handling

| Scenario | Handling |
|----------|----------|
| Unknown / expired session token | `query.answer("Session expired — re-run the command.", show_alert=True)` |
| Zero signals | Plain text message, no session created |
| Single signal | Card view directly, no list step |
| `edit_message_text` API error | `try/except`, fallback to `query.answer("Action failed — try again.", show_alert=True)` |
| Item already discarded | Triage action answers with toast; existing handler unchanged |

---

## Testing

All tests in `tests/test_bot.py`:

| Test | Verifies |
|------|----------|
| `test_send_grouped_notification_creates_session` | Session created in `bot._sessions` |
| `test_grouped_list_view_format` | Correct item count, WTP scores, label in rendered text |
| `test_sel_callback_edits_to_card_view` | `sel:TOKEN:0` triggers `edit_message_text` with card content |
| `test_loadmore_callback_increments_shown` | `loadmore:TOKEN` increases `shown_count` by 5, re-renders list |
| `test_back_callback_returns_to_list` | `back:TOKEN` edits message back to list view |
| `test_unknown_token_shows_expired_toast` | Unknown token → `query.answer` with expiry text |
| `test_empty_signals_sends_plain_text` | 0 signals → plain text, no session |
| `test_session_eviction` | Sessions > 24h evicted on new session creation |
| `test_single_item_shows_card_directly` | 1-signal run skips list, shows card |
| `test_analyze_cmd_uses_grouped_notification` | `cmd_analyze` uses grouped path, not old `format_report` path |
