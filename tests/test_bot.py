# tests/test_bot.py
import pytest
from bot import format_report, parse_analyze_args, parse_monitor_args
from classifier import PainSignal
from scraper import Post


# --- parse_analyze_args ---

def test_parse_analyze_args_subreddit_only():
    subreddit, limit = parse_analyze_args("r/python")
    assert subreddit == "python"
    assert limit == 100


def test_parse_analyze_args_with_limit():
    subreddit, limit = parse_analyze_args("r/startups 50")
    assert subreddit == "startups"
    assert limit == 50


def test_parse_analyze_args_without_r_prefix():
    subreddit, limit = parse_analyze_args("python")
    assert subreddit == "python"
    assert limit == 100


def test_parse_analyze_args_empty_string():
    subreddit, limit = parse_analyze_args("")
    assert isinstance(subreddit, str)
    assert isinstance(limit, int)


# --- parse_monitor_args ---

def test_parse_monitor_args_with_hours():
    subreddit, hours = parse_monitor_args("r/webdev 6h")
    assert subreddit == "webdev"
    assert hours == 6


def test_parse_monitor_args_default_interval():
    subreddit, hours = parse_monitor_args("r/python")
    assert subreddit == "python"
    assert hours == 24


def test_parse_monitor_args_without_h_suffix():
    subreddit, hours = parse_monitor_args("r/python 12")
    assert hours == 24  # "12" without "h" suffix should use default


# --- format_report ---

def test_format_report_empty():
    text = format_report("python", [])
    assert "python" in text
    assert "0" in text


def test_format_report_with_complaint():
    signals = [
        PainSignal(
            post=Post("p1", "python", "Can't import module", "", "", 10),
            category="complaint",
            summary="User can't import module",
            severity="high",
        )
    ]
    text = format_report("python", signals)
    assert "python" in text
    assert "1" in text
    assert "🔴" in text


def test_format_report_with_wish():
    signals = [
        PainSignal(
            post=Post("p1", "python", "Wish there was a linter", "", "", 5),
            category="wish",
            summary="User wants a linter",
            severity="low",
        )
    ]
    text = format_report("python", signals)
    assert "🟢" in text


def test_format_report_with_unsolved():
    signals = [
        PainSignal(
            post=Post("p1", "python", "How do I do X", "", "", 5),
            category="unsolved",
            summary="User needs help with X",
            severity="medium",
        )
    ]
    text = format_report("python", signals)
    assert "🟡" in text


def test_format_report_count_is_correct():
    signals = [
        PainSignal(post=Post(f"p{i}", "python", "T", "", "", 1), category="complaint", summary="s", severity="low")
        for i in range(5)
    ]
    text = format_report("python", signals)
    assert "5" in text
