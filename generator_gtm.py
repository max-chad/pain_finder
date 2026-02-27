import json
from dataclasses import dataclass
from typing import Any

from db import Database
from openrouter import GTMGenerationResult, OpenRouterClient


@dataclass
class GTMResult:
    post_id: str
    model: str
    payload: GTMGenerationResult
    asset_id: int


class GTMGenerator:
    def __init__(self, db: Database, openrouter: OpenRouterClient):
        self.db = db
        self.openrouter = openrouter

    async def generate(self, post_id: str) -> GTMResult:
        pain_point = await self.db.get_pain_point(post_id)
        if not pain_point:
            raise ValueError(f"Pain point not found: {post_id}")

        deep_dive = await self.db.get_deep_dive(post_id)
        macro_cluster = await self.db.get_latest_macro_cluster_for_post(post_id)

        context = self._build_context(
            pain_point=pain_point,
            deep_dive=deep_dive,
            macro_cluster=macro_cluster,
        )

        gtm = await self.openrouter.generate_gtm(context=context, post_id=post_id)
        if gtm is None:
            raise RuntimeError("GTM generation failed validation")

        payload = {
            "name_options": gtm.name_options,
            "hero_h1": gtm.hero_h1,
            "hero_h2": gtm.hero_h2,
            "mvp_features": gtm.mvp_features,
            "pricing_tier": gtm.pricing_tier,
            "positioning_rationale": gtm.positioning_rationale,
            "raw_payload": gtm.raw_payload,
        }
        asset_id = await self.db.save_gtm_asset(post_id=post_id, model=self.openrouter.gtm_model, payload=payload)
        return GTMResult(post_id=post_id, model=self.openrouter.gtm_model, payload=gtm, asset_id=asset_id)

    @staticmethod
    def _build_context(
        *,
        pain_point: dict[str, Any],
        deep_dive: dict[str, Any] | None,
        macro_cluster: dict[str, Any] | None,
    ) -> str:
        competitor_tags = pain_point.get("competitor_tags", "[]")
        if isinstance(competitor_tags, str):
            try:
                parsed = json.loads(competitor_tags)
                if isinstance(parsed, list):
                    competitor_tags = parsed
            except json.JSONDecodeError:
                competitor_tags = []
        if not isinstance(competitor_tags, list):
            competitor_tags = []

        sections = [
            f"Post ID: {pain_point.get('post_id', '')}",
            f"Title: {pain_point.get('title', '')}",
            f"Summary: {pain_point.get('summary', '')}",
            f"Category: {pain_point.get('category', '')}",
            f"Niche: {pain_point.get('niche_category', '')}",
            f"Pain level: {pain_point.get('pain_level', 0)}",
            f"Willingness to pay: {pain_point.get('willingness_to_pay', 0)}",
            f"Competitor tags: {', '.join(str(tag) for tag in competitor_tags)}",
        ]

        if deep_dive and deep_dive.get("payload_json"):
            sections.append("Deep dive payload:")
            sections.append(str(deep_dive.get("payload_json")))
        if macro_cluster:
            sections.append(
                f"Latest macro trend: {macro_cluster.get('label', '')} - {macro_cluster.get('summary', '')}"
            )

        return "\n".join(sections)
