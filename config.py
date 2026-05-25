import json
import os
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDERS = {"openrouter", "codex", "openai", "openai-codex"}
EMBED_PROVIDERS = {"openrouter", "codex", "openai", "bow", "hash", "disabled", "none"}
DSPY_PROVIDERS = {"openrouter", "codex", "openai"}


def _first_env(*names: str, default: str | None = None, required: bool = False) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value
    if required:
        raise KeyError(names[0])
    return default or ""


def _default_llm_model(provider: str) -> str:
    if provider in {"codex", "openai"}:
        return "gpt-5.3-spark"
    return "meta-llama/llama-3.1-8b-instruct:free"


def _default_embed_model(provider: str) -> str:
    if provider in {"codex", "openai"}:
        return "text-embedding-3-small"
    return "google/text-embedding-004"


def _default_temperature(provider: str, model: str) -> str:
    if provider in {"codex", "openai"} and "gpt-5" in model:
        return "1.0"
    return "0.1"


def _default_max_tokens(provider: str, model: str) -> str:
    if provider in {"codex", "openai"} and "gpt-5" in model:
        return "16000"
    return "4000"


def _choice_env(name: str, default: str, choices: set[str]) -> str:
    return _choice_value(name, os.getenv(name, default), default, choices)


def _choice_value(name: str, raw: str | None, default: str, choices: set[str]) -> str:
    value = (raw if raw is not None else default).strip().lower() or default
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"{name} must be one of: {allowed}")
    return value


def _int_range_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _int_min_env(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _float_min_env(name: str, default: float, minimum: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum:g}")
    return value


def _float_range_env(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


def _json_list_env(name: str, default: list[Any]) -> list[Any]:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be a valid JSON array") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"{name} must be a JSON array")
    return parsed


def _bool_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "off", "no"}


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "pain_finder/1.0")

LLM_PROVIDER = _choice_value("LLM_PROVIDER", _first_env("LLM_PROVIDER", default="codex"), "codex", LLM_PROVIDERS)
LLM_API_KEY = _first_env("LLM_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", required=True).strip()
LLM_API_BASE = _first_env("LLM_API_BASE", "OPENROUTER_API_BASE", default="").strip()
LLM_MODEL = _first_env("LLM_MODEL", "OPENROUTER_MODEL", default=_default_llm_model(LLM_PROVIDER)).strip() or _default_llm_model(LLM_PROVIDER)
LLM_DEEP_DIVE_MODEL = _first_env("LLM_DEEP_DIVE_MODEL", "OPENROUTER_DEEP_DIVE_MODEL", default="").strip() or LLM_MODEL
LLM_CLUSTER_MODEL = _first_env("LLM_CLUSTER_MODEL", "OPENROUTER_CLUSTER_MODEL", default="").strip() or LLM_MODEL
LLM_GTM_MODEL = _first_env("LLM_GTM_MODEL", "OPENROUTER_GTM_MODEL", default="").strip() or LLM_MODEL
LLM_MODEL_PRICING_JSON = _first_env("LLM_MODEL_PRICING_JSON", "OPENROUTER_MODEL_PRICING_JSON", default="{}")
LLM_REASONING_EFFORT = _first_env("LLM_REASONING_EFFORT", default="high").strip().lower() or "high"
LLM_TEMPERATURE = _float_min_env("LLM_TEMPERATURE", float(_default_temperature(LLM_PROVIDER, LLM_MODEL)), 0.0)
LLM_MAX_TOKENS = _int_min_env("LLM_MAX_TOKENS", int(_default_max_tokens(LLM_PROVIDER, LLM_MODEL)), 1)

# Backward-compatible aliases for existing code/tests/docs.
OPENROUTER_API_KEY = LLM_API_KEY
OPENROUTER_MODEL = LLM_MODEL
OPENROUTER_DEEP_DIVE_MODEL = LLM_DEEP_DIVE_MODEL
OPENROUTER_CLUSTER_MODEL = LLM_CLUSTER_MODEL
OPENROUTER_GTM_MODEL = LLM_GTM_MODEL
OPENROUTER_MODEL_PRICING_JSON = LLM_MODEL_PRICING_JSON

_default_embed_provider = LLM_PROVIDER if LLM_PROVIDER in EMBED_PROVIDERS else "codex"
EMBED_PROVIDER = _choice_value(
    "EMBED_PROVIDER",
    _first_env("EMBED_PROVIDER", default=_default_embed_provider),
    _default_embed_provider,
    EMBED_PROVIDERS,
)
EMBED_API_KEY = _first_env("EMBED_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", default=LLM_API_KEY).strip() or LLM_API_KEY
EMBED_API_BASE = _first_env("EMBED_API_BASE", "LLM_API_BASE", "OPENROUTER_API_BASE", default=LLM_API_BASE).strip()
EMBED_MODEL = _first_env("EMBED_MODEL", default=_default_embed_model(EMBED_PROVIDER)).strip() or _default_embed_model(EMBED_PROVIDER)
DEDUP_SIMILARITY_THRESHOLD = _float_range_env("DEDUP_SIMILARITY_THRESHOLD", 0.88, 0.0, 1.0)

DB_PATH = os.getenv("DB_PATH", "pain_finder.db")
REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")

CLASSIFIER_MODE = _choice_env("CLASSIFIER_MODE", "dual", {"legacy", "b2b", "dual"})
CLASSIFIER_MAX_CONCURRENCY = _int_min_env("CLASSIFIER_MAX_CONCURRENCY", 8, 1)
LLM_MAX_CLASSIFICATIONS_PER_RUN = _int_min_env("LLM_MAX_CLASSIFICATIONS_PER_RUN", 0, 0)
SCREEN_MIN_RULE_SCORE = _int_min_env("SCREEN_MIN_RULE_SCORE", 2, 0)
SCREEN_MAX_LLM_CANDIDATES_PER_RUN = _int_min_env(
    "SCREEN_MAX_LLM_CANDIDATES_PER_RUN", LLM_MAX_CLASSIFICATIONS_PER_RUN, 0
)
PRIMARY_MAX_OUTPUT_TOKENS = _int_min_env("PRIMARY_MAX_OUTPUT_TOKENS", min(1200, LLM_MAX_TOKENS), 1)
DEEP_DIVE_WTP_THRESHOLD = _int_range_env("DEEP_DIVE_WTP_THRESHOLD", 8, 0, 10)
DEEP_DIVE_MAX_COMMENTS = _int_min_env("DEEP_DIVE_MAX_COMMENTS", 250, 0)

SCRAPER_TOP_COMMENTS = _int_min_env("SCRAPER_TOP_COMMENTS", 5, 0)
SCRAPER_COMMENT_FETCH_CONCURRENCY = _int_min_env("SCRAPER_COMMENT_FETCH_CONCURRENCY", 8, 1)
SCRAPER_RETRY_MAX_ATTEMPTS = _int_min_env("SCRAPER_RETRY_MAX_ATTEMPTS", 5, 1)
SCRAPER_RETRY_BASE_DELAY = _float_min_env("SCRAPER_RETRY_BASE_DELAY", 1.0, 0.0)
SCRAPER_FEED_MIX_JSON = os.getenv("SCRAPER_FEED_MIX_JSON", '["new", "rising", "top"]')
SCRAPER_SEARCH_QUERIES_JSON = os.getenv("SCRAPER_SEARCH_QUERIES_JSON", "[]")

DSPY_REDDIT_PARSER_ENABLED = _bool_env("DSPY_REDDIT_PARSER_ENABLED")
_default_dspy_provider = LLM_PROVIDER if LLM_PROVIDER in DSPY_PROVIDERS else "codex"
DSPY_PROVIDER = _choice_value(
    "DSPY_PROVIDER",
    _first_env("DSPY_PROVIDER", default=_default_dspy_provider),
    _default_dspy_provider,
    DSPY_PROVIDERS,
)
DSPY_MODEL = _first_env("DSPY_MODEL", default=LLM_MODEL).strip() or LLM_MODEL
DSPY_REASONING_EFFORT = _first_env("DSPY_REASONING_EFFORT", default=LLM_REASONING_EFFORT).strip().lower() or LLM_REASONING_EFFORT
DSPY_API_KEY = _first_env("DSPY_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", default=LLM_API_KEY).strip() or LLM_API_KEY
DSPY_API_BASE = _first_env("DSPY_API_BASE", "LLM_API_BASE", default=LLM_API_BASE).strip()
DSPY_TEMPERATURE = _float_min_env("DSPY_TEMPERATURE", LLM_TEMPERATURE, 0.0)
DSPY_MAX_TOKENS = _int_min_env("DSPY_MAX_TOKENS", LLM_MAX_TOKENS, 1)

EXPORT_MIN_WTP = _int_range_env("EXPORT_MIN_WTP", 8, 0, 10)
GOOGLE_SHEETS_CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "")
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
GOOGLE_SHEETS_WORKSHEET_PREFIX = os.getenv("GOOGLE_SHEETS_WORKSHEET_PREFIX", "pain_finder")

APP_MODE = _choice_env("APP_MODE", "telegram", {"telegram", "hermes"})
DIGEST_DELIVERY_ENABLED = _bool_env("DIGEST_DELIVERY_ENABLED")
DIGEST_HOURS = _int_range_env("DIGEST_HOURS", 24, 1, 168)
DIGEST_GROUP_BY = _choice_env("DIGEST_GROUP_BY", "niche", {"niche", "source", "category"})
DIGEST_HOUR_UTC = _int_range_env("DIGEST_HOUR_UTC", 9, 0, 23)
DIGEST_MINUTE_UTC = _int_range_env("DIGEST_MINUTE_UTC", 0, 0, 59)
DIGEST_MIN_WTP = _int_range_env("DIGEST_MIN_WTP", EXPORT_MIN_WTP, 0, 10)
DIGEST_MAX_ITEMS_PER_GROUP = _int_min_env("DIGEST_MAX_ITEMS_PER_GROUP", 10, 1)
CURRENT_OPPORTUNITY_MAX_AGE_DAYS = _int_min_env("CURRENT_OPPORTUNITY_MAX_AGE_DAYS", 180, 1)
EVERGREEN_MAX_AGE_DAYS = _int_min_env("EVERGREEN_MAX_AGE_DAYS", 365, 1)

DAILY_BUDGET_USD = _float_min_env("DAILY_BUDGET_USD", 2.0, 0.0)

TREND_LOOKBACK_DAYS = _int_min_env("TREND_LOOKBACK_DAYS", 30, 1)
TREND_MIN_CLUSTER_SIZE = _int_min_env("TREND_MIN_CLUSTER_SIZE", 3, 1)
TREND_CLUSTER_SIMILARITY = _float_range_env("TREND_CLUSTER_SIMILARITY", 0.72, 0.0, 1.0)
MACRO_TREND_ENABLED = _bool_env("MACRO_TREND_ENABLED", "1")
MACRO_TREND_WEEKDAY_UTC = _choice_env("MACRO_TREND_WEEKDAY_UTC", "sun", {"mon", "tue", "wed", "thu", "fri", "sat", "sun"})
MACRO_TREND_HOUR_UTC = _int_range_env("MACRO_TREND_HOUR_UTC", 8, 0, 23)

HN_ENABLED = _bool_env("HN_ENABLED")
HN_KEYWORDS_JSON = os.getenv(
    "HN_KEYWORDS_JSON",
    '["internal tool", "frustrating", "we built our own", "manual process"]',
)
HN_LOOKBACK_HOURS = _int_min_env("HN_LOOKBACK_HOURS", 72, 1)
HN_MAX_POSTS = _int_min_env("HN_MAX_POSTS", 100, 1)
HN_INTERVAL_HOURS = _int_min_env("HN_INTERVAL_HOURS", 6, 1)

REVIEWS_ENABLED = _bool_env("REVIEWS_ENABLED")
REVIEW_TARGETS_JSON = os.getenv("REVIEW_TARGETS_JSON", "[]")
REVIEWS_MAX_PER_TARGET = _int_min_env("REVIEWS_MAX_PER_TARGET", 30, 1)
REVIEWS_INTERVAL_HOURS = _int_min_env("REVIEWS_INTERVAL_HOURS", 24, 1)

GTM_ENABLED = _bool_env("GTM_ENABLED", "1")


def parse_json_env(raw: str, default):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


LLM_MODEL_PRICING = parse_json_env(LLM_MODEL_PRICING_JSON, {})
OPENROUTER_MODEL_PRICING = LLM_MODEL_PRICING
HN_KEYWORDS = _json_list_env("HN_KEYWORDS_JSON", ["internal tool", "frustrating", "we built our own", "manual process"])
if not isinstance(HN_KEYWORDS, list):
    HN_KEYWORDS = []
HN_KEYWORDS = [str(keyword).strip() for keyword in HN_KEYWORDS if str(keyword).strip()]
if HN_ENABLED and not HN_KEYWORDS:
    raise ValueError("HN_KEYWORDS_JSON must contain at least one non-empty keyword when HN_ENABLED=1")

REVIEW_TARGETS = _json_list_env("REVIEW_TARGETS_JSON", [])
if not isinstance(REVIEW_TARGETS, list):
    REVIEW_TARGETS = []
_enabled_review_targets = [
    target
    for target in REVIEW_TARGETS
    if isinstance(target, dict)
    and str(target.get("site") or "").strip()
    and str(target.get("name") or "").strip()
    and str(target.get("url") or "").strip()
    and str(target.get("enabled", "1")).strip().lower() not in {"0", "false", "off", "no"}
]
_invalid_review_urls = [
    target for target in _enabled_review_targets if not _is_http_url(str(target.get("url") or ""))
]
if _invalid_review_urls:
    raise ValueError("REVIEW_TARGETS_JSON enabled target URLs must use http or https")
_valid_review_targets = [
    target for target in _enabled_review_targets if _is_http_url(str(target.get("url") or ""))
]
if REVIEWS_ENABLED and not _valid_review_targets:
    raise ValueError("REVIEW_TARGETS_JSON must contain at least one enabled target with site, name, and url when REVIEWS_ENABLED=1")

SCRAPER_FEED_MIX = _json_list_env("SCRAPER_FEED_MIX_JSON", ["new", "rising", "top"])
if not isinstance(SCRAPER_FEED_MIX, list):
    SCRAPER_FEED_MIX = ["new", "rising", "top"]
SCRAPER_FEED_MIX = [str(feed).strip().lower() for feed in SCRAPER_FEED_MIX if str(feed).strip()]
_ALLOWED_SCRAPER_FEEDS = {"new", "rising", "top"}
_invalid_feeds = [feed for feed in SCRAPER_FEED_MIX if feed not in _ALLOWED_SCRAPER_FEEDS]
if not SCRAPER_FEED_MIX or _invalid_feeds:
    allowed_feeds = ", ".join(sorted(_ALLOWED_SCRAPER_FEEDS))
    raise ValueError(f"SCRAPER_FEED_MIX_JSON must contain only supported feeds: {allowed_feeds}")

SCRAPER_SEARCH_QUERIES = _json_list_env("SCRAPER_SEARCH_QUERIES_JSON", [])
if not isinstance(SCRAPER_SEARCH_QUERIES, list):
    SCRAPER_SEARCH_QUERIES = []
SCRAPER_SEARCH_QUERIES = [str(query).strip() for query in SCRAPER_SEARCH_QUERIES if str(query).strip()]
