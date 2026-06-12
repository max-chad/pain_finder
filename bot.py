import logging
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Literal, TypedDict

from classifier import PainSignal
from export_sheets import ExportResult

if TYPE_CHECKING:
    from budget import BudgetStatus
    from clusterer import MacroTrendRunResult
    from generator_gtm import GTMResult
    from pipeline import AnalysisRun, DeepDiveRun
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import Application


class DigestItem(TypedDict, total=False):
    post_id: str
    weighted_score: int
    willingness_to_pay: int
    summary: str


class DigestPayload(TypedDict, total=False):
    hours: int
    subreddit: str | None
    total: int
    top_items: list[DigestItem]
    top_clusters: list[dict[str, object]]
    niche_counts: dict[str, int]
    source_counts: dict[str, int]
    recurring_blockers: list[str]


class SessionState(TypedDict):
    signals: list[PainSignal]
    label: str
    created_at: float
    shown_count: int


TriageStatus = Literal["favorite", "discarded"]

logger = logging.getLogger(__name__)
SESSION_TOKEN_RE = re.compile(r"^[0-9a-f]{8}$")
TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_TRUNCATION_SUFFIX = "\n...[truncated]"

SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")
POST_ID_RE = re.compile(r"^[A-Za-z0-9_:-]+$")

ANALYZE_USAGE = "Usage: /analyze r/<subreddit> [limit: 1-100]"
MONITOR_USAGE = "Usage: /monitor r/<subreddit> [Nh where N=1..168]"
UNMONITOR_USAGE = "Usage: /unmonitor r/<subreddit>"
EXPORT_USAGE = "Usage: /export [r/<subreddit>]"
DEEPDIVE_USAGE = "Usage: /deepdive <post_id>"
DIGEST_USAGE = "Usage: /digest [r/<subreddit>] [hours: 1-168]"
MACRO_USAGE = "Usage: /macro [days: 1-90]"
GTM_USAGE = "Usage: /gtm <post_id>"


def normalize_subreddit(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("Subreddit is required.")
    if value.lower().startswith("r/"):
        value = value[2:]
    if not SUBREDDIT_RE.fullmatch(value):
        raise ValueError("Invalid subreddit. Use letters, numbers, and underscores only.")
    return value.lower()


def parse_analyze_args(text: str) -> tuple[str, int]:
    parts = text.strip().split()
    if not parts:
        raise ValueError(ANALYZE_USAGE)
    if len(parts) > 2:
        raise ValueError(ANALYZE_USAGE)
    subreddit = normalize_subreddit(parts[0])
    limit = 100
    if len(parts) == 2:
        if not parts[1].isdigit():
            raise ValueError(ANALYZE_USAGE)
        limit = int(parts[1])
        if not (1 <= limit <= 100):
            raise ValueError(ANALYZE_USAGE)
    return subreddit, limit


def parse_monitor_args(text: str) -> tuple[str, int]:
    parts = text.strip().split()
    if not parts:
        raise ValueError(MONITOR_USAGE)
    if len(parts) > 2:
        raise ValueError(MONITOR_USAGE)
    subreddit = normalize_subreddit(parts[0])
    hours = 24
    if len(parts) == 2:
        raw = parts[1].lower()
        if not (raw.endswith("h") and raw[:-1].isdigit()):
            raise ValueError(MONITOR_USAGE)
        hours = int(raw[:-1])
        if not (1 <= hours <= 168):
            raise ValueError(MONITOR_USAGE)
    return subreddit, hours


def parse_deepdive_args(text: str) -> str:
    parts = text.strip().split()
    if len(parts) != 1 or not POST_ID_RE.fullmatch(parts[0]):
        raise ValueError(DEEPDIVE_USAGE)
    return parts[0]


def parse_gtm_args(text: str) -> str:
    parts = text.strip().split()
    if len(parts) != 1 or not POST_ID_RE.fullmatch(parts[0]):
        raise ValueError(GTM_USAGE)
    return parts[0]


def parse_digest_args(text: str) -> tuple[str | None, int]:
    parts = text.strip().split()
    if not parts:
        return None, 24
    if len(parts) > 2:
        raise ValueError(DIGEST_USAGE)

    subreddit: str | None = None
    hours = 24
    first = parts[0]
    if first.isdigit():
        hours = int(first)
        if len(parts) == 2:
            raise ValueError(DIGEST_USAGE)
    elif first.lower().startswith("r/") or SUBREDDIT_RE.fullmatch(first):
        subreddit = normalize_subreddit(first)
        if len(parts) == 2:
            if not parts[1].isdigit():
                raise ValueError(DIGEST_USAGE)
            hours = int(parts[1])
    else:
        raise ValueError(DIGEST_USAGE)

    if not (1 <= hours <= 168):
        raise ValueError(DIGEST_USAGE)
    return subreddit, hours


def parse_macro_args(text: str) -> int:
    value = text.strip()
    if not value:
        return 30
    if not value.isdigit():
        raise ValueError(MACRO_USAGE)
    days = int(value)
    if not (1 <= days <= 90):
        raise ValueError(MACRO_USAGE)
    return days


def parse_sel_callback_data(data: str) -> tuple[str, int]:
    parts = data.split(":", 2)
    if len(parts) != 3:
        raise ValueError("Malformed callback data")
    _, token, idx_str = parts
    return token, int(idx_str)


def parse_scoped_callback_data(data: str, prefix: str) -> tuple[str, str]:
    payload = data[len(prefix) :]
    parts = payload.rsplit(":", 1)
    if len(parts) != 2:
        raise ValueError("Malformed callback data")
    return parts[0], parts[1]


def limit_telegram_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    if limit <= len(TELEGRAM_TRUNCATION_SUFFIX):
        return text[:limit]
    return text[: limit - len(TELEGRAM_TRUNCATION_SUFFIX)].rstrip() + TELEGRAM_TRUNCATION_SUFFIX


def _is_path_inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _signal_icon(signal: PainSignal) -> str:
    if signal.is_monetizable and signal.willingness_to_pay >= 8:
        return "[money]"
    if signal.category == "complaint":
        return "[complaint]"
    if signal.category == "unsolved":
        return "[unsolved]"
    return "[wish]"


def format_report(subreddit: str, signals: list[PainSignal]) -> str:
    if not signals:
        return f"[report] r/{subreddit} - 0 pain points found"

    complaints = [signal for signal in signals if signal.category == "complaint"]
    unsolved = [signal for signal in signals if signal.category == "unsolved"]
    wishes = [signal for signal in signals if signal.category == "wish"]
    monetizable = [signal for signal in signals if signal.is_monetizable]
    lines = [f"[report] r/{subreddit} - {len(signals)} pain points found", f"[money] Monetizable: {len(monetizable)}"]

    if complaints:
        lines.append(f"Complaints ({len(complaints)}): {complaints[0].summary[:80]}...")
    if unsolved:
        lines.append(f"Unsolved ({len(unsolved)}): {unsolved[0].summary[:80]}...")
    if wishes:
        lines.append(f"Wishes ({len(wishes)}): {wishes[0].summary[:80]}...")
    lines.append("Use inline actions to favorite/discard/deep dive/gtm high-value posts.")
    return "\n".join(lines)


class PainFinderBot:
    def __init__(
        self,
        scraper,
        classifier,
        db,
        reload_jobs_fn: Callable[[], Awaitable[None]] | None = None,
        analyze_fn: Callable[[str, int], Awaitable["AnalysisRun"]] | None = None,
        deep_dive_fn: Callable[[str, str, str], Awaitable["DeepDiveRun"]] | None = None,
        digest_fn: Callable[[str | None, int], Awaitable[DigestPayload]] | None = None,
        macro_fn: Callable[[int], Awaitable["MacroTrendRunResult"]] | None = None,
        budget_status_fn: Callable[[], Awaitable["BudgetStatus"]] | None = None,
        resume_budget_fn: Callable[[], Awaitable[datetime]] | None = None,
        gtm_fn: Callable[[str], Awaitable["GTMResult"]] | None = None,
        export_service=None,
    ):
        self.scraper = scraper
        self.classifier = classifier
        self.db = db
        self.reload_jobs_fn = reload_jobs_fn
        self.analyze_fn = analyze_fn
        self.deep_dive_fn = deep_dive_fn
        self.digest_fn = digest_fn
        self.macro_fn = macro_fn
        self.budget_status_fn = budget_status_fn
        self.resume_budget_fn = resume_budget_fn
        self.gtm_fn = gtm_fn
        self.export_service = export_service
        self.app: "Application | None" = None
        self._sessions: dict[str, SessionState] = {}

    def _is_authorized(self, update: "Update") -> bool:
        import config

        if update.effective_chat is None:
            return False
        return update.effective_chat.id == config.TELEGRAM_CHAT_ID

    def _evict_old_sessions(self) -> None:
        cutoff = time.time() - 86400  # 24 hours
        expired = [t for t, s in self._sessions.items() if s["created_at"] < cutoff]
        for t in expired:
            del self._sessions[t]

    def _create_session(self, signals: list["PainSignal"], label: str) -> str:
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

    def _render_list_view(self, token: str, session: SessionState) -> tuple[str, "InlineKeyboardMarkup"]:
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
        chunk_size = 5
        keyboard_rows: list[list["InlineKeyboardButton"]] = [
            num_buttons[i:i + chunk_size] for i in range(0, len(num_buttons), chunk_size)
        ]
        remaining = total - shown
        if remaining > 0:
            keyboard_rows.append([
                InlineKeyboardButton(
                    f"Load more \u2193  ({remaining} remaining)",
                    callback_data=f"loadmore:{token}",
                )
            ])
        return limit_telegram_text("\n".join(lines)), InlineKeyboardMarkup(keyboard_rows)

    def _render_card_view(self, token: str, session: SessionState, idx: int) -> tuple[str, "InlineKeyboardMarkup"]:
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
                InlineKeyboardButton("\u2b50 Favorite", callback_data=f"triage:favorite:{token}:{idx}"),
                InlineKeyboardButton("\u2717 Discard", callback_data=f"triage:discard:{token}:{idx}"),
            ],
            [
                InlineKeyboardButton(
                    "\U0001f48e Deep Dive",
                    callback_data=f"deepdive:{token}:{idx}",
                ),
                InlineKeyboardButton(
                    "\U0001f4e6 GTM",
                    callback_data=f"gtm:{token}:{idx}",
                ),
            ],
            [InlineKeyboardButton("\u2190 Back to list", callback_data=f"back:{token}")],
        ]
        return limit_telegram_text("\n".join(lines)), InlineKeyboardMarkup(keyboard_rows)

    def _resolve_session_signal(self, token: str, idx_raw: str) -> tuple[str, "PainSignal | None"]:
        session = self._sessions.get(token)
        if session is None:
            return "expired", None
        try:
            idx = int(idx_raw)
        except ValueError:
            return "malformed", None
        signals: list[PainSignal] = session["signals"]
        if not (0 <= idx < len(signals)):
            return "out_of_range", None
        return "ok", signals[idx]

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

    async def cmd_analyze(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        args = " ".join(ctx.args) if ctx.args else ""
        try:
            subreddit, limit = parse_analyze_args(args)
        except ValueError as e:
            await update.message.reply_text(str(e))
            return

        await update.message.reply_text(f"Analyzing r/{subreddit} (up to {limit} posts)...")
        try:
            if self.analyze_fn:
                run = await self.analyze_fn(subreddit, limit)
                signals = run.signals
            else:
                posts = await self.scraper.fetch_posts(subreddit, limit=limit)
                signals = await self.classifier.classify_batch(posts)
                for signal in signals:
                    await self.db.insert_pain_point(
                        subreddit=subreddit,
                        post_id=signal.post.post_id,
                        url=signal.post.url,
                        title=signal.post.title,
                        body=signal.post.body,
                        category=signal.category,
                        summary=signal.summary,
                        severity=signal.severity,
                        is_monetizable=signal.is_monetizable,
                        pain_level=signal.pain_level,
                        willingness_to_pay=signal.willingness_to_pay,
                        niche_category=signal.niche_category,
                        competitor_tags=signal.competitor_tags,
                        source=signal.post.source,
                        analysis_mode=signal.analysis_mode,
                        analysis_payload=signal.analysis_payload,
                    )
            await self._send_grouped_notification_reply(update, signals, f"r/{subreddit}")
        except Exception as e:
            logger.exception("Analyze command failed")
            await update.message.reply_text(f"Error: {e}")

    async def cmd_monitor(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        args = " ".join(ctx.args) if ctx.args else ""
        try:
            subreddit, hours = parse_monitor_args(args)
        except ValueError as e:
            await update.message.reply_text(str(e))
            return
        await self.db.add_monitored_subreddit(subreddit, interval_hours=hours)
        if self.reload_jobs_fn:
            await self.reload_jobs_fn()
        await update.message.reply_text(f"Now monitoring r/{subreddit} every {hours}h")

    async def cmd_unmonitor(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        args = " ".join(ctx.args) if ctx.args else ""
        try:
            subreddit = normalize_subreddit(args)
        except ValueError:
            await update.message.reply_text(UNMONITOR_USAGE)
            return
        await self.db.remove_monitored_subreddit(subreddit)
        if self.reload_jobs_fn:
            await self.reload_jobs_fn()
        await update.message.reply_text(f"Stopped monitoring r/{subreddit}")

    async def cmd_list(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        subs = await self.db.get_monitored_subreddits()
        if not subs:
            await update.message.reply_text("No subreddits being monitored.")
            return
        lines = ["Monitored subreddits:"]
        for sub in subs:
            last = sub["last_checked"] or "never"
            line = f"- r/{sub['name']} every {sub['interval_hours']}h (last success: {last})"
            if sub.get("last_error"):
                attempted = sub.get("last_attempted_at") or "unknown"
                line += f" last error at {attempted}: {sub['last_error']}"
            lines.append(line)
        await update.message.reply_text(limit_telegram_text("\n".join(lines)))

    async def cmd_status(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        summary = await self.db.get_monitoring_summary()
        latest_run = await self.db.get_latest_analysis_run()
        scheduled_jobs = await self.db.get_scheduled_job_statuses()
        lines = [
            "pain_finder running",
            f"Monitored subreddits: {summary['monitored']}",
            f"Favorited pain points: {summary['favorites']}",
            f"LLM paused: {'yes' if summary.get('llm_paused') else 'no'}",
        ]
        if latest_run:
            lines.append(
                "Last run: "
                f"r/{latest_run['subreddit']} "
                f"posts={latest_run['post_count']} "
                f"pain={latest_run['pain_count']} "
                f"monetizable={latest_run['monetizable_count']} "
                f"skipped_existing={latest_run.get('skipped_existing_count', 0)} "
                f"dedup_merged={latest_run.get('dedup_merged_count', 0)}"
            )
        failed_jobs = [job for job in scheduled_jobs if job.get("last_error")]
        if failed_jobs:
            lines.append("Scheduled job errors:")
            for job in failed_jobs:
                attempted = job.get("last_attempted_at") or "unknown"
                lines.append(f"- {job['job_name']} last error at {attempted}: {job['last_error']}")
        await update.message.reply_text(limit_telegram_text("\n".join(lines)))

    async def cmd_export(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        args = ctx.args if ctx.args else []
        if len(args) > 1:
            await update.message.reply_text(EXPORT_USAGE)
            return
        try:
            subreddit = normalize_subreddit(args[0]) if args else None
        except ValueError:
            await update.message.reply_text(EXPORT_USAGE)
            return

        if self.export_service:
            result: ExportResult = await self.export_service.export(subreddit=subreddit)
            with open(result.csv_path, "rb") as export_file:
                await update.message.reply_document(
                    document=export_file,
                    filename=os.path.basename(result.csv_path),
                    caption=f"Export rows: {result.row_count}",
                )
            if result.sheet_url:
                await update.message.reply_text(limit_telegram_text(f"Google Sheet updated: {result.sheet_url}"))
            if result.warning:
                await update.message.reply_text(limit_telegram_text(f"Warning: {result.warning}"))
            return

        report = await self.db.get_latest_report(subreddit=subreddit)
        if not report:
            await update.message.reply_text("No reports found yet.")
            return
        json_path = report.get("json_path")
        if not json_path or not os.path.exists(json_path):
            await update.message.reply_text(f"Report file not found: {json_path}")
            return
        import config

        report_path = Path(str(json_path)).expanduser().resolve()
        reports_root = Path(config.REPORTS_DIR).expanduser().resolve()
        if report_path.suffix.lower() != ".json":
            await update.message.reply_text("Report path is not a JSON report.")
            return
        if not _is_path_inside(report_path, reports_root):
            await update.message.reply_text("Report path is outside the configured reports directory.")
            return
        with open(report_path, "rb") as report_file:
            await update.message.reply_document(
                document=report_file,
                filename=report_path.name,
                caption=f"Latest report for r/{report['subreddit']}",
            )

    async def cmd_deepdive(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        args = " ".join(ctx.args) if ctx.args else ""
        try:
            post_id = parse_deepdive_args(args)
        except ValueError as e:
            await update.message.reply_text(str(e))
            return
        row = await self.db.get_pain_point(post_id)
        if not row:
            await update.message.reply_text(limit_telegram_text(f"Post {post_id} was not found in the database."))
            return
        if not self.deep_dive_fn:
            await update.message.reply_text("Deep dive is not configured.")
            return
        await update.message.reply_text(limit_telegram_text(f"Running deep dive for {post_id}..."))
        result = await self.deep_dive_fn(post_id, row["subreddit"], "manual")
        if result.status == "completed":
            await update.message.reply_text(limit_telegram_text(f"Deep dive complete for {post_id}: {result.summary}"))
        else:
            await update.message.reply_text(limit_telegram_text(f"Deep dive failed for {post_id}: {result.error}"))

    async def cmd_digest(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        args = " ".join(ctx.args) if ctx.args else ""
        try:
            subreddit, hours = parse_digest_args(args)
        except ValueError as e:
            await update.message.reply_text(str(e))
            return
        if not self.digest_fn:
            await update.message.reply_text("Digest is not configured.")
            return
        digest = await self.digest_fn(subreddit, hours)
        if digest["total"] == 0:
            scope = f"r/{subreddit}" if subreddit else "all monitored subreddits"
            await update.message.reply_text(f"No digest data for {scope} in the last {hours}h.")
            return
        lines = [
            f"Digest ({hours}h) for {'r/' + subreddit if subreddit else 'all subreddits'}",
            f"Total signals: {digest['total']}",
        ]
        if digest["niche_counts"]:
            top_niches = sorted(digest["niche_counts"].items(), key=lambda item: item[1], reverse=True)[:5]
            lines.append("Top niches: " + ", ".join(f"{name} ({count})" for name, count in top_niches))
        if digest.get("source_counts"):
            top_sources = sorted(digest["source_counts"].items(), key=lambda item: item[1], reverse=True)[:3]
            lines.append("Sources: " + ", ".join(f"{name} ({count})" for name, count in top_sources))
        if digest.get("top_clusters"):
            lines.append("Top canonical clusters:")
            for cluster in digest["top_clusters"][:3]:
                lines.append(
                    f"- {cluster.get('label', 'Recurring pain cluster')} | avg_opp={cluster.get('avg_opportunity_score', 0)}"
                )
        for row in digest["top_items"][:5]:
            lines.append(
                f"- {row.get('post_id')} | score={row.get('weighted_score', 0)} wtp={row.get('willingness_to_pay', 0)} | {row.get('summary', '')[:80]}"
            )
        if digest["recurring_blockers"]:
            lines.append("Recurring blockers:")
            for blocker in digest["recurring_blockers"][:3]:
                lines.append(f"- {blocker[:120]}")
        await update.message.reply_text(limit_telegram_text("\n".join(lines)))

    async def cmd_macro(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        args = " ".join(ctx.args) if ctx.args else ""
        try:
            days = parse_macro_args(args)
        except ValueError as e:
            await update.message.reply_text(str(e))
            return
        if not self.macro_fn:
            await update.message.reply_text("Macro trend clustering is not configured.")
            return
        await update.message.reply_text(f"Running macro trend clustering for last {days} days...")
        result = await self.macro_fn(days)
        if not result.clusters:
            await update.message.reply_text(
                f"No macro clusters found. Candidates scanned: {result.candidate_count}."
            )
            return
        lines = [
            f"Macro trend run #{result.run_id} ({days}d)",
            f"Candidates: {result.candidate_count}",
            f"Clusters: {len(result.clusters)}",
        ]
        for cluster in result.clusters[:5]:
            lines.append(
                f"- {cluster.label} | items={cluster.item_count} | signal={cluster.estimated_monetization_signal} | wtp_total={cluster.aggregate_wtp:.1f}"
            )
            lines.append(f"  {cluster.summary[:160]}")
        await update.message.reply_text(limit_telegram_text("\n".join(lines)))

    async def cmd_budget(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        if not self.budget_status_fn:
            await update.message.reply_text("Budget guard is not configured.")
            return
        status = await self.budget_status_fn()
        lines = [
            f"Daily cap: ${status.daily_cap_usd:.2f}",
            f"Spent today: ${status.spent_today_usd:.4f}",
            f"LLM paused: {'yes' if status.llm_paused else 'no'}",
        ]
        if status.pause_reason:
            lines.append(f"Pause reason: {status.pause_reason}")
        if status.resume_override_until:
            lines.append(f"Resume override until: {status.resume_override_until}")
        await update.message.reply_text(limit_telegram_text("\n".join(lines)))

    async def cmd_resume(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        if not self.resume_budget_fn:
            await update.message.reply_text("Budget resume is not configured.")
            return
        resume_until = await self.resume_budget_fn()
        if self.reload_jobs_fn:
            await self.reload_jobs_fn()
        await update.message.reply_text(
            f"LLM pause override is active until {resume_until.isoformat()}."
        )

    async def cmd_gtm(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        if not self.gtm_fn:
            await update.message.reply_text("GTM generator is not configured.")
            return
        args = " ".join(ctx.args) if ctx.args else ""
        try:
            post_id = parse_gtm_args(args)
        except ValueError as e:
            await update.message.reply_text(str(e))
            return
        await update.message.reply_text(limit_telegram_text(f"Generating GTM package for {post_id}..."))
        result = await self.gtm_fn(post_id)
        await update.message.reply_text(self._format_gtm_result(result))

    async def on_callback_query(self, update: "Update", ctx) -> None:
        if not self._is_authorized(update):
            return
        query = update.callback_query
        if query is None:
            return
        data = query.data or ""
        try:
            if data.startswith("sel:"):
                try:
                    token, idx = parse_sel_callback_data(data)
                except ValueError:
                    await query.answer("Malformed callback", show_alert=False)
                    return
                session = self._sessions.get(token)
                if session is None:
                    await query.answer("Session expired \u2014 re-run the command.", show_alert=True)
                    return
                if not (0 <= idx < len(session["signals"])):
                    await query.answer("Item out of range", show_alert=False)
                    return
                text, keyboard = self._render_card_view(token, session, idx)
                try:
                    await query.edit_message_text(text, reply_markup=keyboard)
                except Exception:
                    logger.warning("edit_message_text failed", exc_info=True)
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
                    logger.warning("edit_message_text failed", exc_info=True)
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
                    logger.warning("edit_message_text failed", exc_info=True)
                    await query.answer("Could not update message \u2014 try again.", show_alert=True)
                    return
                await query.answer()
                return

            if data.startswith("triage:"):
                triage_parts = data.split(":", 3)
                if len(triage_parts) < 3:
                    raise ValueError("Malformed callback data")
                _, action = triage_parts[:2]
                status_map: dict[str, TriageStatus] = {"favorite": "favorite", "discard": "discarded"}
                status = status_map.get(action)
                if not status:
                    await query.answer("Unknown action", show_alert=False)
                    return
                if len(triage_parts) == 4 and SESSION_TOKEN_RE.match(triage_parts[2]):
                    signal_status, signal = self._resolve_session_signal(triage_parts[2], triage_parts[3])
                    if signal_status == "expired":
                        await query.answer("Session expired \u2014 re-run the command.", show_alert=True)
                        return
                    if signal_status == "out_of_range":
                        await query.answer("Item out of range", show_alert=False)
                        return
                    if signal_status != "ok" or signal is None:
                        await query.answer("Malformed callback", show_alert=False)
                        return
                    post_id = signal.post.post_id
                else:
                    post_id = triage_parts[2]
                updated = await self.db.update_triage_status(post_id, status)
                if not updated:
                    await query.answer("Post not found", show_alert=False)
                    return
                await query.answer(f"Marked as {status}", show_alert=False)
                return

            if data.startswith("deepdive:"):
                payload = data[len("deepdive:"):]
                session_parts = payload.split(":", 1)
                if len(session_parts) == 2 and SESSION_TOKEN_RE.match(session_parts[0]):
                    signal_status, signal = self._resolve_session_signal(session_parts[0], session_parts[1])
                    if signal_status == "expired":
                        await query.answer("Session expired \u2014 re-run the command.", show_alert=True)
                        return
                    if signal_status == "out_of_range":
                        await query.answer("Item out of range", show_alert=False)
                        return
                    if signal_status != "ok" or signal is None:
                        await query.answer("Malformed callback", show_alert=False)
                        return
                    post_id = signal.post.post_id
                    subreddit = signal.post.subreddit
                else:
                    post_id, subreddit = parse_scoped_callback_data(data, "deepdive:")
                if not self.deep_dive_fn:
                    await query.answer("Deep dive not configured", show_alert=False)
                    return
                await query.answer("Running deep dive...", show_alert=False)
                result = await self.deep_dive_fn(post_id, subreddit, "callback")
                if result.status == "completed":
                    await query.message.reply_text(
                        limit_telegram_text(f"Deep dive complete for {post_id}: {result.summary}")
                    )
                else:
                    await query.message.reply_text(
                        limit_telegram_text(f"Deep dive failed for {post_id}: {result.error}")
                    )
                return

            if data.startswith("gtm:"):
                payload = data[len("gtm:"):]
                session_parts = payload.split(":", 1)
                if len(session_parts) == 2 and SESSION_TOKEN_RE.match(session_parts[0]):
                    signal_status, signal = self._resolve_session_signal(session_parts[0], session_parts[1])
                    if signal_status == "expired":
                        await query.answer("Session expired \u2014 re-run the command.", show_alert=True)
                        return
                    if signal_status == "out_of_range":
                        await query.answer("Item out of range", show_alert=False)
                        return
                    if signal_status != "ok" or signal is None:
                        await query.answer("Malformed callback", show_alert=False)
                        return
                    post_id = signal.post.post_id
                else:
                    post_id, _scope = parse_scoped_callback_data(data, "gtm:")
                if not self.gtm_fn:
                    await query.answer("GTM not configured", show_alert=False)
                    return
                await query.answer("Generating GTM...", show_alert=False)
                result = await self.gtm_fn(post_id)
                await query.message.reply_text(self._format_gtm_result(result))
                return

            await query.answer("Unsupported action", show_alert=False)
        except Exception:
            logger.exception("Callback processing failed")
            await query.answer("Action failed", show_alert=False)

    @staticmethod
    def _format_gtm_result(result: "GTMResult") -> str:
        payload = result.payload
        lines = [
            f"GTM package for {result.post_id}",
            f"Names: {', '.join(payload.name_options)}",
            f"H1: {payload.hero_h1}",
            f"H2: {payload.hero_h2}",
            "MVP features:",
        ]
        for feature in payload.mvp_features:
            lines.append(f"- {feature}")
        lines.append(f"Pricing: {payload.pricing_tier}")
        lines.append(f"Positioning: {payload.positioning_rationale}")
        return limit_telegram_text("\n".join(lines))

    def build_app(self):
        from telegram.ext import Application, CallbackQueryHandler, CommandHandler
        import config

        self.app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        self.app.add_handler(CommandHandler("analyze", self.cmd_analyze))
        self.app.add_handler(CommandHandler("monitor", self.cmd_monitor))
        self.app.add_handler(CommandHandler("unmonitor", self.cmd_unmonitor))
        self.app.add_handler(CommandHandler("list", self.cmd_list))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("export", self.cmd_export))
        self.app.add_handler(CommandHandler("deepdive", self.cmd_deepdive))
        self.app.add_handler(CommandHandler("digest", self.cmd_digest))
        self.app.add_handler(CommandHandler("macro", self.cmd_macro))
        self.app.add_handler(CommandHandler("budget", self.cmd_budget))
        self.app.add_handler(CommandHandler("resume", self.cmd_resume))
        self.app.add_handler(CommandHandler("gtm", self.cmd_gtm))
        self.app.add_handler(CallbackQueryHandler(self.on_callback_query))
        return self.app
