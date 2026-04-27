from pathlib import Path


REPORT_PATH = Path("docs/reports/2026-04-27-hardening-audit.md")


def test_hardening_audit_report_covers_wave9_release_gates():
    text = REPORT_PATH.read_text(encoding="utf-8")

    required_sections = [
        "# Pain Finder Hardening Audit — 2026-04-27",
        "## Branch / PR scope",
        "## Validation evidence",
        "## Evaluation / MVP threshold status",
        "## Evidence-first safety audit",
        "## SQLite migration audit",
        "## Report/export surface audit",
        "## Runtime guardrails and source coverage",
        "## Secrets/static scan",
        "## Open risks / release decision",
    ]
    for section in required_sections:
        assert section in text

    required_thresholds = [
        "Pain precision",
        ">= 0.75",
        "Pain recall",
        ">= 0.60",
        "Evidence exact match",
        ">= 0.95",
        "Monetizable precision",
        ">= 0.65",
        "Top-10 useful insight rate",
        ">= 0.50",
        "Cluster duplicate rate",
        "<= 0.20",
    ]
    for marker in required_thresholds:
        assert marker in text

    assert "PR #6" in text
    assert "draft" in text.lower()
    assert "pytest --cov=. --cov-fail-under=80 -q" in text
    assert "static added-lines secret scan" in text
    assert "not ready for unattended production use" in text.lower()


def test_readme_documents_self_research_workflow():
    text = Path("README.md").read_text(encoding="utf-8")

    required_markers = [
        "## Self-research workflow",
        "verified pain clusters",
        "evidence-first promotion",
        "Next research action",
        "local static HTML report",
        "grouped `.docx` digest",
        "MVP threshold status",
    ]
    for marker in required_markers:
        assert marker in text


def test_eval_readme_documents_wave92_mvp_threshold_assessment():
    text = Path("eval/README.md").read_text(encoding="utf-8")

    required_markers = [
        "## Wave 9.2 MVP threshold assessment",
        "mvp_thresholds.json",
        "not usable for MVP",
        "expanded benchmark",
        "explicit waiver",
        "Pain precision",
        ">= 0.75",
        "Top-10 useful insight rate",
        ">= 0.50",
        "Cluster duplicate rate",
        "<= 0.20",
    ]
    for marker in required_markers:
        assert marker in text
