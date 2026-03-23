from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from generator_gtm import GTMGenerator


async def test_generate_gtm_happy_path_persists_asset():
    db = AsyncMock()
    db.get_pain_point.return_value = {
        "post_id": "reddit:abc",
        "title": "Need sync",
        "summary": "Inventory sync breaks",
        "category": "complaint",
        "niche_category": "E-commerce",
        "pain_level": 9,
        "willingness_to_pay": 8,
        "competitor_tags": '["shopify","quickbooks"]',
    }
    db.get_deep_dive.return_value = {"payload_json": '{"actionable_summary":"Build retries"}'}
    db.get_latest_macro_cluster_for_post.return_value = {"label": "Commerce integrations", "summary": "Recurring failures"}
    db.save_gtm_asset.return_value = 42

    payload = SimpleNamespace(
        name_options=["A", "B", "C"],
        hero_h1="H1",
        hero_h2="H2",
        mvp_features=["f1", "f2", "f3"],
        pricing_tier="$39",
        positioning_rationale="Because",
        raw_payload={"ok": True},
    )
    openrouter = AsyncMock()
    openrouter.gtm_model = "gpt-test"
    openrouter.generate_gtm.return_value = payload

    generator = GTMGenerator(db=db, openrouter=openrouter)
    result = await generator.generate("reddit:abc")

    assert result.asset_id == 42
    assert result.post_id == "reddit:abc"
    assert result.model == "gpt-test"
    openrouter.generate_gtm.assert_awaited_once()
    db.save_gtm_asset.assert_awaited_once()


async def test_generate_gtm_raises_when_post_missing():
    db = AsyncMock()
    db.get_pain_point.return_value = None
    generator = GTMGenerator(db=db, openrouter=AsyncMock())

    with pytest.raises(ValueError):
        await generator.generate("reddit:missing")


async def test_generate_gtm_raises_when_model_fails():
    db = AsyncMock()
    db.get_pain_point.return_value = {
        "post_id": "reddit:x",
        "title": "",
        "summary": "",
        "category": "",
        "niche_category": "",
        "pain_level": 0,
        "willingness_to_pay": 0,
        "competitor_tags": "[]",
    }
    db.get_deep_dive.return_value = None
    db.get_latest_macro_cluster_for_post.return_value = None
    openrouter = AsyncMock()
    openrouter.generate_gtm.return_value = None
    generator = GTMGenerator(db=db, openrouter=openrouter)

    with pytest.raises(RuntimeError):
        await generator.generate("reddit:x")


def test_build_context_handles_bad_competitor_json():
    text = GTMGenerator._build_context(
        pain_point={
            "post_id": "reddit:y",
            "title": "t",
            "summary": "s",
            "category": "complaint",
            "niche_category": "Ops",
            "pain_level": 5,
            "willingness_to_pay": 6,
            "competitor_tags": "{bad",
        },
        deep_dive={"payload_json": '{"workarounds":["manual"]}'},
        macro_cluster={"label": "Trend", "summary": "Summary"},
    )
    assert "Post ID: reddit:y" in text
    assert "Deep dive payload:" in text
    assert "Latest macro trend: Trend - Summary" in text
