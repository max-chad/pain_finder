import logging
import os
import re
from typing import TYPE_CHECKING, Awaitable, Callable

from classifier import PainSignal

if TYPE_CHECKING:
    from pipeline import AnalysisRun

logger = logging.getLogger(__name__)

SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")
ANALYZE_USAGE = "Usage: /analyze r/<subreddit> [limit: 1-100]"
MONITOR_USAGE = "Usage: /monitor r/<subreddit> [Nh where N=1..168]"
UNMONITOR_USAGE = "Usage: /unmonitor r/<subreddit>"
EXPORT_USAGE = "Usage: /export [r/<subreddit>]"


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


def format_report(subreddit: str, signals: list[PainSignal]) -> str:
    if not signals:
        return f"📊 r/{subreddit} - 0 pain points found"

    complaints = [signal for signal in signals if signal.category == "complaint"]
    unsolved = [signal for signal in signals if signal.category == "unsolved"]
    wishes = [signal for signal in signals if signal.category == "wish"]

    lines = [f"📊 r/{subreddit} - {len(signals)} pain points found"]
    if complaints:
        sample = complaints[0].summary[:80]
        lines.append(f'🔴 Complaints ({len(complaints)}): "{sample}..."')
    if unsolved:
        sample = unsolved[0].summary[:80]
        lines.append(f'🟡 Unsolved ({len(unsolved)}): "{sample}..."')
    if wishes:
        sample = wishes[0].summary[:80]
        lines.append(f'🟢 Wishes ({len(wishes)}): "{sample}..."')
    lines.append("Full report saved. Use /export to get the latest file.")
    return "\n".join(lines)


class PainFinderBot:
    def __init__(
        self,
        scraper,
        classifier,
        db,
        reload_jobs_fn: Callable[[], Awaitable[None]] | None = None,
        analyze_fn: Callable[[str, int], Awaitable["AnalysisRun"]] | None = None,
    ):
        self.scraper = scraper
        self.classifier = classifier
        self.db = db
        self.reload_jobs_fn = reload_jobs_fn
        self.analyze_fn = analyze_fn
        self.app = None

    def _is_authorized(self, update) -> bool:
        import config

        if update.effective_chat is None:
            return False
        return update.effective_chat.id == config.TELEGRAM_CHAT_ID

    async def cmd_analyze(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        args = " ".join(ctx.args) if ctx.args else ""
        try:
            subreddit, limit = parse_analyze_args(args)
        except ValueError as e:
            await update.message.reply_text(str(e))
            return

        await update.message.reply_text(f"⏳ Analyzing r/{subreddit} (up to {limit} posts)...")
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
                    )
            await update.message.reply_text(format_report(subreddit, signals))
        except Exception as e:
            logger.exception("Analyze command failed")
            await update.message.reply_text(f"❌ Error: {e}")

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
        await update.message.reply_text(f"✅ Now monitoring r/{subreddit} every {hours}h")

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
        await update.message.reply_text(f"🗑 Stopped monitoring r/{subreddit}")

    async def cmd_list(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        subs = await self.db.get_monitored_subreddits()
        if not subs:
            await update.message.reply_text("No subreddits being monitored.")
            return
        lines = ["📋 Monitored subreddits:"]
        for sub in subs:
            last = sub["last_checked"] or "never"
            lines.append(f"• r/{sub['name']} every {sub['interval_hours']}h (last: {last})")
        await update.message.reply_text("\n".join(lines))

    async def cmd_status(self, update, ctx):
        if not self._is_authorized(update) or update.message is None:
            return
        subs = await self.db.get_monitored_subreddits()
        await update.message.reply_text(
            f"🤖 pain_finder running\n{len(subs)} subreddits monitored"
        )

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

        report = await self.db.get_latest_report(subreddit=subreddit)
        if not report:
            await update.message.reply_text("No reports found yet.")
            return

        json_path = report.get("json_path")
        if not json_path:
            await update.message.reply_text("Latest report has no file path.")
            return
        if not os.path.exists(json_path):
            await update.message.reply_text(f"Report file not found: {json_path}")
            return

        with open(json_path, "rb") as report_file:
            await update.message.reply_document(
                document=report_file,
                filename=os.path.basename(json_path),
                caption=f"Latest report for r/{report['subreddit']}",
            )

    def build_app(self):
        from telegram.ext import Application, CommandHandler
        import config

        self.app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        self.app.add_handler(CommandHandler("analyze", self.cmd_analyze))
        self.app.add_handler(CommandHandler("monitor", self.cmd_monitor))
        self.app.add_handler(CommandHandler("unmonitor", self.cmd_unmonitor))
        self.app.add_handler(CommandHandler("list", self.cmd_list))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("export", self.cmd_export))
        return self.app
