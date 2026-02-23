# tests/test_classifier.py
import pytest
from unittest.mock import AsyncMock
from classifier import Classifier, PainSignal
from scraper import Post
from openrouter import AnalysisResult


def make_post(title="", body="", post_id="p1"):
    return Post(post_id=post_id, subreddit="test", title=title, body=body,
                url="", score=10)


def test_keyword_score_high_for_clear_complaint():
    clf = Classifier(openrouter=None)
    score = clf.keyword_score(make_post(title="I can't get this to work, so frustrated"))
    assert score >= 2


def test_keyword_score_zero_for_neutral():
    clf = Classifier(openrouter=None)
    score = clf.keyword_score(make_post(title="Cool new project announcement"))
    assert score == 0


def test_keyword_score_wish_detected():
    clf = Classifier(openrouter=None)
    score = clf.keyword_score(make_post(title="I wish this had dark mode"))
    assert score >= 1


def test_keyword_score_max_is_3():
    clf = Classifier(openrouter=None)
    score = clf.keyword_score(make_post(
        title="I can't do this, wish it worked, help me please"
    ))
    assert score == 3


async def test_classify_skips_llm_for_zero_score():
    mock_llm = AsyncMock()
    clf = Classifier(openrouter=mock_llm)
    result = await clf.classify(make_post(title="Random announcement post"))
    mock_llm.analyze_post.assert_not_called()
    assert result is None


async def test_classify_calls_llm_for_pain_posts():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = AnalysisResult(
        category="complaint", summary="User can't do X", severity="high"
    )
    clf = Classifier(openrouter=mock_llm)
    result = await clf.classify(make_post(title="I can't believe how broken this is"))
    assert result is not None
    assert result.category == "complaint"
    assert result.severity == "high"
    mock_llm.analyze_post.assert_called_once()


async def test_classify_falls_back_to_keyword_when_llm_returns_none():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = None
    clf = Classifier(openrouter=mock_llm)
    post = make_post(title="I wish this tool had export feature")
    result = await clf.classify(post)
    assert result is not None
    assert result.category == "wish"
    assert result.summary == post.title[:120]


async def test_classify_without_llm_uses_keyword_fallback():
    clf = Classifier(openrouter=None)
    post = make_post(title="I can't figure this out, stuck on it for days")
    result = await clf.classify(post)
    assert result is not None
    assert result.category == "complaint"


async def test_classify_batch_filters_nones():
    clf = Classifier(openrouter=None)
    posts = [
        make_post(title="Cool announcement", post_id="p1"),
        make_post(title="I can't get this working", post_id="p2"),
        make_post(title="Just sharing news", post_id="p3"),
        make_post(title="Wish this had dark mode", post_id="p4"),
    ]
    signals = await clf.classify_batch(posts)
    assert len(signals) >= 1
    assert all(s is not None for s in signals)
    pain_ids = {s.post.post_id for s in signals}
    assert "p2" in pain_ids and "p4" in pain_ids
