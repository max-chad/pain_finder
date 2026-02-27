import json
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
OPENROUTER_DEEP_DIVE_MODEL = os.getenv("OPENROUTER_DEEP_DIVE_MODEL", "").strip() or OPENROUTER_MODEL
OPENROUTER_CLUSTER_MODEL = os.getenv("OPENROUTER_CLUSTER_MODEL", "").strip() or OPENROUTER_MODEL
OPENROUTER_GTM_MODEL = os.getenv("OPENROUTER_GTM_MODEL", "").strip() or OPENROUTER_MODEL
OPENROUTER_MODEL_PRICING_JSON = os.getenv("OPENROUTER_MODEL_PRICING_JSON", "{}")
EMBED_MODEL = os.getenv("EMBED_MODEL", "google/text-embedding-004")
DEDUP_SIMILARITY_THRESHOLD = float(os.getenv("DEDUP_SIMILARITY_THRESHOLD", "0.88"))

DB_PATH = os.getenv("DB_PATH", "pain_finder.db")
REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")

CLASSIFIER_MODE = os.getenv("CLASSIFIER_MODE", "dual").strip().lower()
DEEP_DIVE_WTP_THRESHOLD = int(os.getenv("DEEP_DIVE_WTP_THRESHOLD", "8"))
DEEP_DIVE_MAX_COMMENTS = int(os.getenv("DEEP_DIVE_MAX_COMMENTS", "250"))

SCRAPER_TOP_COMMENTS = int(os.getenv("SCRAPER_TOP_COMMENTS", "5"))
SCRAPER_RETRY_MAX_ATTEMPTS = int(os.getenv("SCRAPER_RETRY_MAX_ATTEMPTS", "5"))
SCRAPER_RETRY_BASE_DELAY = float(os.getenv("SCRAPER_RETRY_BASE_DELAY", "1.0"))

EXPORT_MIN_WTP = int(os.getenv("EXPORT_MIN_WTP", "8"))
GOOGLE_SHEETS_CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "")
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
GOOGLE_SHEETS_WORKSHEET_PREFIX = os.getenv("GOOGLE_SHEETS_WORKSHEET_PREFIX", "pain_finder")

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


OPENROUTER_MODEL_PRICING = parse_json_env(OPENROUTER_MODEL_PRICING_JSON, {})
HN_KEYWORDS = parse_json_env(HN_KEYWORDS_JSON, [])
if not isinstance(HN_KEYWORDS, list):
    HN_KEYWORDS = []

REVIEW_TARGETS = parse_json_env(REVIEW_TARGETS_JSON, [])
if not isinstance(REVIEW_TARGETS, list):
    REVIEW_TARGETS = []
