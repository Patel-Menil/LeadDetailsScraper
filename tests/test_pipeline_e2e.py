"""End-to-end tests for the research pipeline and resume behavior."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from src.lead_research.pipeline import ResearchPipeline
from src.lead_research.research import LeadResearcher
from src.lead_research.schemas import LeadProfile, PriorityInfo, ProfessionalContext, ResearchMetadata
from src.lead_research.scraper import ScraplingScraper, ScrapeResult


def test_pipeline_dry_run_and_resume(tmp_path: Path):
    input_csv = tmp_path / "test_leads.csv"
    input_csv.write_text(
        "Full Name,Job Title,Company Name,Industry,Email\n"
        "Elena Rostova,Chief AI Officer,Cognitive Corp,information technology,elena@cognitive.com\n"
        "Marcus Vance,VP Engineering,DataMesh,financial services,marcus@datamesh.io\n",
        encoding="utf-8"
    )

    output_dir = tmp_path / "output"
    pipeline = ResearchPipeline(output_dir=output_dir, concurrency=2)

    # 1. Run batch in dry-run mode
    progress, paths = pipeline.run_batch(
        batch_id="batch_dry_01",
        input_file=input_csv,
        dry_run=True,
    )

    assert progress.status == "completed"
    assert progress.total_leads == 2
    assert progress.processed_leads == 2
    assert Path(paths["csv_path"]).exists()
    assert Path(paths["manifest_path"]).exists()

    # 2. Run again with resume=True: verify existing profiles are loaded
    progress2, paths2 = pipeline.run_batch(
        batch_id="batch_dry_01",
        input_file=input_csv,
        dry_run=True,
        resume=True,
    )
    assert progress2.processed_leads == 2
    assert any("loaded from resume cache" in msg for msg in progress2.recent_logs)


def test_pipeline_synthetic_e2e_verification_and_exports(tmp_path: Path):
    import json
    input_csv = tmp_path / "synthetic_leads.csv"
    input_csv.write_text(
        "Full Name,Job Title,Company Name,Company Website,Email,Industry\n"
        "Alex Rivera,VP of Security,CyberShield,https://cybershield.test,alex@cybershield.test,Computer Software\n"
        "Sam Doe,Software Engineer,UnknownCo,https://unknownco.test,sam@unknownco.test,Information Technology\n",
        encoding="utf-8"
    )

    output_dir = tmp_path / "e2e_output"
    pipeline = ResearchPipeline(output_dir=output_dir, concurrency=1)

    lead1_page = ScrapeResult(
        url="https://cybershield.test/team",
        status_code=200,
        success=True,
        title="CyberShield - Leadership Team",
        meta_description="CyberShield develops next-generation API security.",
        extracted_text="Leadership Team: Alex Rivera, VP of Security. Alex Rivera oversees enterprise security architecture at CyberShield.",
    )
    lead2_page = ScrapeResult(
        url="https://unknownco.test",
        status_code=200,
        success=True,
        title="UnknownCo Homepage",
        extracted_text="Welcome to UnknownCo. Special thanks to Sam Doe for visiting.",
    )

    def mock_fetch(url: str):
        if "cybershield.test" in url:
            return lead1_page
        return lead2_page

    with patch.object(ScraplingScraper, "fetch_url", side_effect=mock_fetch):
        with patch.object(ScraplingScraper, "search_person", return_value=[]):
            progress, paths = pipeline.run_batch(
                batch_id="batch_synthetic_e2e_01",
                input_file=input_csv,
                dry_run=False,
                use_browser=False,
                use_tor=False,
            )

    assert progress.status == "completed"
    assert progress.total_leads == 2
    assert progress.processed_leads == 2

    # Check manifest and summary agree
    manifest_p = Path(paths["manifest_path"])
    summary_p = Path(paths["summary_path"])
    with open(manifest_p, "r", encoding="utf-8") as f:
        m = json.load(f)
    with open(summary_p, "r", encoding="utf-8") as f:
        s = json.load(f)

    assert m["total_processed"] == 2
    assert s["total_leads"] == 2
    assert m["counts"]["total"] == s["total_leads"] == 2

    # Check profile files
    profiles_dir = Path(paths["profiles_dir"])
    p_files = list(profiles_dir.glob("*.json"))
    assert len(p_files) == 2

    # Verify Lead 1 profile claims and readiness
    p1_data = next(json.loads(pf.read_text(encoding="utf-8")) for pf in p_files if "alex" in pf.name.lower())
    title_claim = next(c for c in p1_data["claims"] if c["field"] == "job_title")
    assert title_claim["status"] == "verified"
    assert p1_data["contact_readiness"]["has_verified_role"] is True

    # Verify Lead 2 profile claims and readiness
    p2_data = next(json.loads(pf.read_text(encoding="utf-8")) for pf in p_files if "sam" in pf.name.lower())
    p2_title_claim = next(c for c in p2_data["claims"] if c["field"] == "job_title")
    assert p2_title_claim["status"] != "verified"
    assert p2_data["contact_readiness"]["has_verified_role"] is False
    assert "current_role_not_verified" in p2_data["contact_readiness"]["blockers"]

