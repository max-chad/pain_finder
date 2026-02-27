import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Awaitable, Callable

from db import Database

logger = logging.getLogger(__name__)


class BudgetCapReachedError(RuntimeError):
    pass


@dataclass
class BudgetStatus:
    daily_cap_usd: float
    spent_today_usd: float
    llm_paused: bool
    pause_reason: str | None
    resume_override_until: str | None


class BudgetGuard:
    def __init__(self, db: Database, daily_cap_usd: float):
        self.db = db
        self.daily_cap_usd = max(0.0, daily_cap_usd)
        self._on_pause_callback: Callable[[str], Awaitable[None]] | None = None

    def set_on_pause_callback(self, callback: Callable[[str], Awaitable[None]] | None) -> None:
        self._on_pause_callback = callback

    async def get_status(self) -> BudgetStatus:
        flags = await self.db.get_runtime_flags()
        spent_today = await self.db.get_daily_spend_usd()
        paused = await self.db.is_llm_paused()
        return BudgetStatus(
            daily_cap_usd=self.daily_cap_usd,
            spent_today_usd=spent_today,
            llm_paused=paused,
            pause_reason=flags.get("pause_reason"),
            resume_override_until=flags.get("resume_override_until"),
        )

    async def ensure_can_spend(self, operation: str) -> None:
        now = datetime.now(UTC)
        flags = await self.db.get_runtime_flags()
        resume_override_raw = flags.get("resume_override_until")
        if resume_override_raw:
            try:
                resume_until = datetime.fromisoformat(resume_override_raw)
                if resume_until.tzinfo is None:
                    resume_until = resume_until.replace(tzinfo=UTC)
                if now <= resume_until:
                    return
            except ValueError:
                logger.warning("Invalid resume_override_until value: %s", resume_override_raw)

        spent_today = await self.db.get_daily_spend_usd(now.date())
        if spent_today >= self.daily_cap_usd:
            reason = f"budget_cap_reached:{spent_today:.4f}/{self.daily_cap_usd:.4f}"
            await self.db.pause_llm(reason=reason, pause_day=now.date())
            if self._on_pause_callback is not None:
                await self._on_pause_callback(reason)
            raise BudgetCapReachedError(
                f"Daily budget cap reached (${spent_today:.4f}/${self.daily_cap_usd:.4f}) during {operation}."
            )

        if await self.db.is_llm_paused(now):
            raise BudgetCapReachedError("LLM operations are paused by runtime flag.")

    async def record_usage(
        self,
        *,
        model: str,
        operation: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        post_id: str | None = None,
    ) -> None:
        await self.db.record_llm_usage(
            model=model,
            operation=operation,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            post_id=post_id,
        )

        status = await self.get_status()
        if status.spent_today_usd >= self.daily_cap_usd and not status.llm_paused:
            reason = f"budget_cap_reached:{status.spent_today_usd:.4f}/{self.daily_cap_usd:.4f}"
            await self.db.pause_llm(reason=reason, pause_day=datetime.now(UTC).date())
            if self._on_pause_callback is not None:
                await self._on_pause_callback(reason)

    async def resume_until_next_utc_day(self) -> datetime:
        now = datetime.now(UTC)
        next_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        await self.db.set_resume_override_until(next_day)
        return next_day
