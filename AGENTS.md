# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## High-value commands
- `pip install -r requirements.txt`
- `python main.py`
- `ruff check .`
- `mypy db.py scraper.py openrouter.py classifier.py pipeline.py bot.py scheduler.py export_sheets.py main.py`
- `pytest --cov=. --cov-fail-under=80 -q`
- `pytest tests/test_pipeline.py -q`
- `pytest tests/test_pipeline.py::test_name -q`

## Project-specific guardrails
- `config.py` reads required env at import time (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OPENROUTER_API_KEY`); missing values fail early during import.
- Keep `main.py` as the composition root; inject callbacks/services into `bot.py`, `pipeline.py`, and `scheduler.py` instead of creating hidden globals.
- Database evolution is additive-only: extend `PAIN_POINT_COLUMNS` and migration names in `db.py`; do not drop/rename existing columns.
- Preserve SQLite reliability PRAGMAs in DB init: `WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, `foreign_keys=ON`.
- Telegram callback payloads can contain `:` inside `post_id`; parse with bounded splits (`split(":", 2)` / `rsplit(":", 1)`).
- LLM paths must enforce budget pause semantics (`BudgetGuard.ensure_can_spend()` or explicit paused checks). `/resume` sets an override only until next UTC midnight.
- `CLASSIFIER_MODE=dual` is the operationally safe mode: strict B2B analysis first, legacy fallback second.
- Keep report writes atomic (`.tmp` file then `os.replace`).
- Cross-source dedup marks duplicates as `triage_status='merged'`; export/digest queries intentionally exclude `merged` and `discarded` rows.

## Mode-specific details
- `.kilocode/rules-code/AGENTS.md`
- `.kilocode/rules-debug/AGENTS.md`
- `.kilocode/rules-ask/AGENTS.md`
- `.kilocode/rules-architect/AGENTS.md`
