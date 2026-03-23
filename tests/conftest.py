import os

# Set sentinel environment variables before any test module imports config.
# config.py reads TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, and OPENROUTER_API_KEY
# via os.environ["..."] at module import time, so these must be present before
# pytest collects (and therefore imports) any test file.  Individual tests that
# need specific values can still override them with monkeypatch.setenv.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "123456789")
os.environ.setdefault("OPENROUTER_API_KEY", "test_openrouter_key")

pytest_asyncio_mode = "auto"
