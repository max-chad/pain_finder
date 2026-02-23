import json
import logging
from dataclasses import dataclass
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"complaint", "unsolved", "wish"}
VALID_SEVERITIES = {"low", "medium", "high"}

PROMPT_TEMPLATE = """Analyze this Reddit post and extract the pain point.

Title: {title}
Body: {body}

Respond with ONLY valid JSON in this exact format:
{{"category": "complaint|unsolved|wish", "summary": "one sentence summary of the pain point", "severity": "low|medium|high"}}

Rules:
- category "complaint": expressing frustration or dissatisfaction
- category "unsolved": asking for help with something they can't figure out
- category "wish": requesting a feature or expressing something they wish existed
- severity based on emotional intensity and upvote potential"""


@dataclass
class AnalysisResult:
    category: str  # complaint | unsolved | wish
    summary: str
    severity: str  # low | medium | high


class OpenRouterClient:
    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def analyze_post(self, title: str, body: str) -> Optional[AnalysisResult]:
        prompt = PROMPT_TEMPLATE.format(title=title, body=body[:1000])
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self.BASE_URL, json=payload, headers=headers)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                if data.get("category") not in VALID_CATEGORIES or data.get("severity") not in VALID_SEVERITIES:
                    logger.warning("OpenRouter returned invalid fields: %s", data)
                    return None
                return AnalysisResult(
                    category=data["category"],
                    summary=data["summary"],
                    severity=data["severity"],
                )
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning("OpenRouter analysis failed: %s", e)
            return None
