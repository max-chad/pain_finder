import os

# Set sentinel environment variables before any test module imports config.
# config.py reads TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, and an LLM API key
# (LLM_API_KEY / OPENAI_API_KEY / OPENROUTER_API_KEY fallback chain)
# at module import time, so these must be present before pytest collects
# (and therefore imports) any test file. Individual tests that need different
# values should override them with monkeypatch.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "123456789")
os.environ.setdefault("OPENROUTER_API_KEY", "test_openrouter_key")
os.environ.setdefault("LLM_API_KEY", "test_llm_key")

pytest_asyncio_mode = "auto"
