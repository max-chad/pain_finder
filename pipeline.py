import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime

from classifier import Classifier, PainSignal
from db import Database
from scraper import RedditScraper

logger = logging.getLogger(__name__)


@dataclass
class AnalysisRun:
    subreddit: str
    post_count: int
    pain_count: int
    signals: list[PainSignal]
    json_path: str
    report_id: int


class AnalysisPipeline:
    def __init__(
        self,
        scraper: RedditScraper,
        classifier: Classifier,
        db: Database,
        reports_dir: str,
    ):
        self.scraper = scraper
        self.classifier = classifier
        self.db = db
        self.reports_dir = reports_dir

    async def analyze_subreddit(self, subreddit: str, limit: int = 100) -> AnalysisRun:
        posts = await self.scraper.fetch_posts(subreddit, limit=limit)
        signals = await self.classifier.classify_batch(posts)

        for signal in signals:
            await self.db.insert_pain_point(
                subreddit=subreddit,
                post_id=signal.post.post_id,
                url=signal.post.url,
                title=signal.post.title,
                body=signal.post.body,
                category=signal.category,
                summary=signal.summary,
                severity=signal.severity,
            )

        os.makedirs(self.reports_dir, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        json_path = os.path.join(self.reports_dir, f"{subreddit}_{timestamp}.json")
        tmp_path = f"{json_path}.tmp"
        payload = [
            {
                "post_id": signal.post.post_id,
                "title": signal.post.title,
                "url": signal.post.url,
                "category": signal.category,
                "summary": signal.summary,
                "severity": signal.severity,
            }
            for signal in signals
        ]

        try:
            with open(tmp_path, "w", encoding="utf-8") as report_file:
                json.dump(payload, report_file, indent=2, ensure_ascii=False)
            os.replace(tmp_path, json_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

        report_id = await self.db.save_report(
            subreddit=subreddit,
            post_count=len(posts),
            pain_count=len(signals),
            json_path=json_path,
        )

        logger.info(
            "Analysis complete for r/%s: %d posts, %d pain points",
            subreddit,
            len(posts),
            len(signals),
        )

        return AnalysisRun(
            subreddit=subreddit,
            post_count=len(posts),
            pain_count=len(signals),
            signals=signals,
            json_path=json_path,
            report_id=report_id,
        )
