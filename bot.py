import logging
from typing import Optional
from classifier import PainSignal
from scraper import Post

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
        raw = parts[1].lower()
        if raw.endswith("h") and raw[:-1].isdigit():
            hours = int(raw[:-1])
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
    def __init__(self, scraper, classifier, db):
        self.scraper = scraper
        self.classifier = classifier
        self.db = db
        self.app = None

    def _is_authorized(self, update) -> bool:
        import config
        return update.effective_chat.id == config.TELEGRAM_CHAT_ID

    async def cmd_analyze(self, update, ctx):
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
            logger.error("Analyze command failed: %s", e)
            await update.message.reply_text(f"❌ Error: {e}")

    async def cmd_monitor(self, update, ctx):
        if not self._is_authorized(update):
            return
        args = " ".join(ctx.args) if ctx.args else ""
        subreddit, hours = parse_monitor_args(args)
        await self.db.add_monitored_subreddit(subreddit, interval_hours=hours)
        await update.message.reply_text(f"✅ Now monitoring r/{subreddit} every {hours}h")

    async def cmd_unmonitor(self, update, ctx):
        if not self._is_authorized(update):
            return
        args = " ".join(ctx.args) if ctx.args else ""
        subreddit = args.strip().lstrip("r/")
        await self.db.remove_monitored_subreddit(subreddit)
        await update.message.reply_text(f"🗑 Stopped monitoring r/{subreddit}")

    async def cmd_list(self, update, ctx):
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

    async def cmd_status(self, update, ctx):
        if not self._is_authorized(update):
            return
        subs = await self.db.get_monitored_subreddits()
        await update.message.reply_text(
            f"🤖 pain_finder running\n{len(subs)} subreddits monitored"
        )

    def build_app(self):
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes
        import config
        self.app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        self.app.add_handler(CommandHandler("analyze", self.cmd_analyze))
        self.app.add_handler(CommandHandler("monitor", self.cmd_monitor))
        self.app.add_handler(CommandHandler("unmonitor", self.cmd_unmonitor))
        self.app.add_handler(CommandHandler("list", self.cmd_list))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        return self.app
