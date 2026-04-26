import json
import os

from dotenv import load_dotenv

load_dotenv()


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


TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "pain_finder/1.0")

LLM_PROVIDER = _first_env("LLM_PROVIDER", default="codex").strip().lower() or "codex"
LLM_API_KEY = _first_env("LLM_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", required=True).strip()
LLM_API_BASE = _first_env("LLM_API_BASE", "OPENROUTER_API_BASE", default="").strip()
LLM_MODEL = _first_env("LLM_MODEL", "OPENROUTER_MODEL", default=_default_llm_model(LLM_PROVIDER)).strip() or _default_llm_model(LLM_PROVIDER)
LLM_DEEP_DIVE_MODEL = _first_env("LLM_DEEP_DIVE_MODEL", "OPENROUTER_DEEP_DIVE_MODEL", default="").strip() or LLM_MODEL
LLM_CLUSTER_MODEL = _first_env("LLM_CLUSTER_MODEL", "OPENROUTER_CLUSTER_MODEL", default="").strip() or LLM_MODEL
LLM_GTM_MODEL = _first_env("LLM_GTM_MODEL", "OPENROUTER_GTM_MODEL", default="").strip() or LLM_MODEL
LLM_MODEL_PRICING_JSON = _first_env("LLM_MODEL_PRICING_JSON", "OPENROUTER_MODEL_PRICING_JSON", default="{}")
LLM_REASONING_EFFORT = _first_env("LLM_REASONING_EFFORT", default="high").strip().lower() or "high"
LLM_TEMPERATURE = float(_first_env("LLM_TEMPERATURE", default=_default_temperature(LLM_PROVIDER, LLM_MODEL)))
LLM_MAX_TOKENS = int(_first_env("LLM_MAX_TOKENS", default=_default_max_tokens(LLM_PROVIDER, LLM_MODEL)))

# Backward-compatible aliases for existing code/tests/docs.
OPENROUTER_API_KEY = LLM_API_KEY
OPENROUTER_MODEL = LLM_MODEL
OPENROUTER_DEEP_DIVE_MODEL = LLM_DEEP_DIVE_MODEL
OPENROUTER_CLUSTER_MODEL = LLM_CLUSTER_MODEL
OPENROUTER_GTM_MODEL = LLM_GTM_MODEL
OPENROUTER_MODEL_PRICING_JSON = LLM_MODEL_PRICING_JSON

EMBED_PROVIDER = _first_env("EMBED_PROVIDER", default=LLM_PROVIDER).strip().lower() or LLM_PROVIDER
EMBED_API_KEY = _first_env("EMBED_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", default=LLM_API_KEY).strip() or LLM_API_KEY
EMBED_API_BASE = _first_env("EMBED_API_BASE", "LLM_API_BASE", "OPENROUTER_API_BASE", default=LLM_API_BASE).strip()
EMBED_MODEL = _first_env("EMBED_MODEL", default=_default_embed_model(EMBED_PROVIDER)).strip() or _default_embed_model(EMBED_PROVIDER)
DEDUP_SIMILARITY_THRESHOLD = float(os.getenv("DEDUP_SIMILARITY_THRESHOLD", "0.88"))

DB_PATH = os.getenv("DB_PATH", "pain_finder.db")
REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")

CLASSIFIER_MODE = os.getenv("CLASSIFIER_MODE", "dual").strip().lower()
CLASSIFIER_MAX_CONCURRENCY = int(os.getenv("CLASSIFIER_MAX_CONCURRENCY", "8"))
LLM_MAX_CLASSIFICATIONS_PER_RUN = int(os.getenv("LLM_MAX_CLASSIFICATIONS_PER_RUN", "0"))
SCREEN_MIN_RULE_SCORE = int(os.getenv("SCREEN_MIN_RULE_SCORE", "1"))
SCREEN_MAX_LLM_CANDIDATES_PER_RUN = int(
    os.getenv("SCREEN_MAX_LLM_CANDIDATES_PER_RUN", str(LLM_MAX_CLASSIFICATIONS_PER_RUN))
)
SEMANTIC_CANDIDATE_RETRIEVAL_ENABLED = os.getenv("SEMANTIC_CANDIDATE_RETRIEVAL_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "off",
    "no",
}
SEMANTIC_CANDIDATE_MAX_PER_RUN = int(os.getenv("SEMANTIC_CANDIDATE_MAX_PER_RUN", "25"))
SEMANTIC_CANDIDATE_MAX_POOL = int(os.getenv("SEMANTIC_CANDIDATE_MAX_POOL", "200"))
SEMANTIC_CANDIDATE_MIN_SIMILARITY = float(os.getenv("SEMANTIC_CANDIDATE_MIN_SIMILARITY", "0.22"))
DEFAULT_SEMANTIC_CANDIDATE_QUERIES_JSON = json.dumps(
    [
        "manual workflow workaround causes repeated operational overhead",
        "reconcile payments invoices payouts between business systems",
        "tool sync integration failure export csv spreadsheet handoff",
        "switching from incumbent software because pricing support reliability is painful",
        "deadline approval customer escalation caused by broken internal process",
    ]
)
SEMANTIC_CANDIDATE_QUERIES_JSON = os.getenv(
    "SEMANTIC_CANDIDATE_QUERIES_JSON",
    DEFAULT_SEMANTIC_CANDIDATE_QUERIES_JSON,
)
MIN_CONFIDENCE_FOR_PROMOTION = float(os.getenv("MIN_CONFIDENCE_FOR_PROMOTION", "0.55"))
PRIMARY_MAX_OUTPUT_TOKENS = int(os.getenv("PRIMARY_MAX_OUTPUT_TOKENS", str(min(1200, LLM_MAX_TOKENS))))
DEEP_DIVE_WTP_THRESHOLD = int(os.getenv("DEEP_DIVE_WTP_THRESHOLD", "8"))
DEEP_DIVE_MAX_COMMENTS = int(os.getenv("DEEP_DIVE_MAX_COMMENTS", "250"))

SCRAPER_TOP_COMMENTS = int(os.getenv("SCRAPER_TOP_COMMENTS", "5"))
SCRAPER_COMMENT_FETCH_CONCURRENCY = int(os.getenv("SCRAPER_COMMENT_FETCH_CONCURRENCY", "8"))
SCRAPER_RETRY_MAX_ATTEMPTS = int(os.getenv("SCRAPER_RETRY_MAX_ATTEMPTS", "5"))
SCRAPER_RETRY_BASE_DELAY = float(os.getenv("SCRAPER_RETRY_BASE_DELAY", "1.0"))
SCRAPER_FEED_MIX_JSON = os.getenv("SCRAPER_FEED_MIX_JSON", '["new", "rising", "top"]')
SCRAPER_SEARCH_QUERIES_JSON = os.getenv("SCRAPER_SEARCH_QUERIES_JSON", "[]")

DSPY_REDDIT_PARSER_ENABLED = os.getenv("DSPY_REDDIT_PARSER_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}
DSPY_PROVIDER = _first_env("DSPY_PROVIDER", default=LLM_PROVIDER).strip().lower() or LLM_PROVIDER
DSPY_MODEL = _first_env("DSPY_MODEL", default=LLM_MODEL).strip() or LLM_MODEL
DSPY_REASONING_EFFORT = _first_env("DSPY_REASONING_EFFORT", default=LLM_REASONING_EFFORT).strip().lower() or LLM_REASONING_EFFORT
DSPY_API_KEY = _first_env("DSPY_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", default=LLM_API_KEY).strip() or LLM_API_KEY
DSPY_API_BASE = _first_env("DSPY_API_BASE", "LLM_API_BASE", default=LLM_API_BASE).strip()
DSPY_TEMPERATURE = float(_first_env("DSPY_TEMPERATURE", default=str(LLM_TEMPERATURE)))
DSPY_MAX_TOKENS = int(_first_env("DSPY_MAX_TOKENS", default=str(LLM_MAX_TOKENS)))

EXPORT_MIN_WTP = int(os.getenv("EXPORT_MIN_WTP", "8"))
GOOGLE_SHEETS_CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "")
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
GOOGLE_SHEETS_WORKSHEET_PREFIX = os.getenv("GOOGLE_SHEETS_WORKSHEET_PREFIX", "pain_finder")

APP_MODE = os.getenv("APP_MODE", "telegram").strip().lower() or "telegram"
DIGEST_DELIVERY_ENABLED = os.getenv("DIGEST_DELIVERY_ENABLED", "0").strip().lower() not in {"0", "false", "off", "no"}
DIGEST_HOURS = int(os.getenv("DIGEST_HOURS", "24"))
DIGEST_GROUP_BY = os.getenv("DIGEST_GROUP_BY", "niche").strip().lower() or "niche"
DIGEST_HOUR_UTC = int(os.getenv("DIGEST_HOUR_UTC", "9"))
DIGEST_MINUTE_UTC = int(os.getenv("DIGEST_MINUTE_UTC", "0"))
DIGEST_MIN_WTP = int(os.getenv("DIGEST_MIN_WTP", str(EXPORT_MIN_WTP)))
DIGEST_MAX_ITEMS_PER_GROUP = int(os.getenv("DIGEST_MAX_ITEMS_PER_GROUP", "10"))
CURRENT_OPPORTUNITY_MAX_AGE_DAYS = int(os.getenv("CURRENT_OPPORTUNITY_MAX_AGE_DAYS", "180"))
EVERGREEN_MAX_AGE_DAYS = int(os.getenv("EVERGREEN_MAX_AGE_DAYS", "365"))

DAILY_BUDGET_USD = float(os.getenv("DAILY_BUDGET_USD", "2.0"))

TREND_LOOKBACK_DAYS = int(os.getenv("TREND_LOOKBACK_DAYS", "30"))
TREND_MIN_CLUSTER_SIZE = int(os.getenv("TREND_MIN_CLUSTER_SIZE", "3"))
TREND_CLUSTER_SIMILARITY = float(os.getenv("TREND_CLUSTER_SIMILARITY", "0.72"))
MACRO_TREND_ENABLED = os.getenv("MACRO_TREND_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}
MACRO_TREND_WEEKDAY_UTC = os.getenv("MACRO_TREND_WEEKDAY_UTC", "sun")
MACRO_TREND_HOUR_UTC = int(os.getenv("MACRO_TREND_HOUR_UTC", "8"))

HN_ENABLED = os.getenv("HN_ENABLED", "0").strip().lower() not in {"0", "false", "off", "no"}
HN_KEYWORDS_JSON = os.getenv(
    "HN_KEYWORDS_JSON",
    '["internal tool", "frustrating", "we built our own", "manual process"]',
)
HN_LOOKBACK_HOURS = int(os.getenv("HN_LOOKBACK_HOURS", "72"))
HN_MAX_POSTS = int(os.getenv("HN_MAX_POSTS", "100"))
HN_INTERVAL_HOURS = int(os.getenv("HN_INTERVAL_HOURS", "6"))

REVIEWS_ENABLED = os.getenv("REVIEWS_ENABLED", "0").strip().lower() not in {"0", "false", "off", "no"}
REVIEW_TARGETS_JSON = os.getenv("REVIEW_TARGETS_JSON", "[]")
REVIEWS_MAX_PER_TARGET = int(os.getenv("REVIEWS_MAX_PER_TARGET", "30"))
REVIEWS_INTERVAL_HOURS = int(os.getenv("REVIEWS_INTERVAL_HOURS", "24"))

GTM_ENABLED = os.getenv("GTM_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}


def parse_json_env(raw: str, default):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


LLM_MODEL_PRICING = parse_json_env(LLM_MODEL_PRICING_JSON, {})
OPENROUTER_MODEL_PRICING = LLM_MODEL_PRICING
HN_KEYWORDS = parse_json_env(HN_KEYWORDS_JSON, [])
if not isinstance(HN_KEYWORDS, list):
    HN_KEYWORDS = []

REVIEW_TARGETS = parse_json_env(REVIEW_TARGETS_JSON, [])
if not isinstance(REVIEW_TARGETS, list):
    REVIEW_TARGETS = []

SCRAPER_FEED_MIX = parse_json_env(SCRAPER_FEED_MIX_JSON, ["new", "rising", "top"])
if not isinstance(SCRAPER_FEED_MIX, list):
    SCRAPER_FEED_MIX = ["new", "rising", "top"]
SCRAPER_FEED_MIX = [str(feed) for feed in SCRAPER_FEED_MIX]

SCRAPER_SEARCH_QUERIES = parse_json_env(SCRAPER_SEARCH_QUERIES_JSON, [])
if not isinstance(SCRAPER_SEARCH_QUERIES, list):
    SCRAPER_SEARCH_QUERIES = []
SCRAPER_SEARCH_QUERIES = [str(query).strip() for query in SCRAPER_SEARCH_QUERIES if str(query).strip()]

SEMANTIC_CANDIDATE_QUERIES = parse_json_env(SEMANTIC_CANDIDATE_QUERIES_JSON, [])
if not isinstance(SEMANTIC_CANDIDATE_QUERIES, list):
    SEMANTIC_CANDIDATE_QUERIES = []
SEMANTIC_CANDIDATE_QUERIES = [str(query).strip() for query in SEMANTIC_CANDIDATE_QUERIES if str(query).strip()]
