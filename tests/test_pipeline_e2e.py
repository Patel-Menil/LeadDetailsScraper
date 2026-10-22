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


def test_pipeline_synthetic_three_candidate_complete_validation(tmp_path: Path):
    """Phase 4: Full synthetic validation covering 3 controlled cases:
    1. Fully evidenced candidate (verified name, job title, company on official domain) -> P0, outreach_ready
    2. High-fit candidate with unverified role/identity (only homepage testimonial) -> P0 blocked, needs_review
    3. Usable contact channel candidate with unverified role and insufficient personalization -> needs_review
    Validates complete deliverables set, count agreement, referenced source IDs, immutability, and atomic latest pointer.
    """
    import csv
    import json

    input_csv = tmp_path / "synthetic_leads_3.csv"
    input_csv.write_text(
        "Full Name,Job Title,Company Name,Company Website,Email,Industry,Keywords\n"
        "Dr. Evelyn Reed,Chief Technology Officer,Vanguard Robotics,https://vanguardrobotics.test,evelyn@vanguardrobotics.test,Artificial Intelligence,ai machine learning zero trust security api governance\n"
        "Alexander Cross,VP of Cloud Engineering,Skyline Systems,https://skylinesys.test,alexander@skylinesys.test,Cloud Infrastructure,cloud infrastructure kubernetes api devops security\n"
        "Morgan Lee,Lead Data Scientist,Horizon Labs,https://horizonlabs.test,morgan@horizonlabs.test,Data Science,data science analytics machine learning\n",
        encoding="utf-8"
    )

    output_dir = tmp_path / "isolated_deliverables_output"
    pipeline = ResearchPipeline(output_dir=output_dir, concurrency=1)

    # Deterministic mocked page responses
    # Lead 1: Vanguard Robotics homepage with /team link + team bio page
    reed_home = ScrapeResult(
        url="https://vanguardrobotics.test",
        status_code=200,
        success=True,
        title="Vanguard Robotics - Enterprise Autonomous Systems",
        meta_description="Vanguard Robotics builds enterprise AI and robotic platforms.",
        extracted_text="Vanguard Robotics builds cutting-edge enterprise AI solutions.",
    )
    reed_team = ScrapeResult(
        url="https://vanguardrobotics.test/team",
        status_code=200,
        success=True,
        title="Leadership - Vanguard Robotics",
        extracted_text=(
            "Executive Leadership at Vanguard Robotics:\n"
            "Dr. Evelyn Reed serves as Chief Technology Officer, overseeing AI architecture, "
            "zero trust security, and cloud robotics infrastructure at Vanguard Robotics.\n"
            "Direct leadership email: evelyn@vanguardrobotics.test"
        ),
    )

    # Lead 2: Skyline Systems homepage with testimonial/acknowledgement mention only
    cross_home = ScrapeResult(
        url="https://skylinesys.test",
        status_code=200,
        success=True,
        title="Skyline Systems Cloud Solutions",
        meta_description="Cloud infrastructure and enterprise architecture.",
        extracted_text="Welcome to Skyline Systems. Special thanks to Alexander Cross for attending our cloud summit.",
    )

    # Lead 3: Horizon Labs homepage only, no bio page
    lee_home = ScrapeResult(
        url="https://horizonlabs.test",
        status_code=200,
        success=True,
        title="Horizon Labs Data Analytics",
        meta_description="Big data and analytics platforms.",
        extracted_text="Horizon Labs provides advanced data science and statistical solutions.",
    )

    def mock_fetch(url: str):
        if "vanguardrobotics.test/team" in url:
            return reed_team
        elif "vanguardrobotics.test" in url:
            return reed_home
        elif "skylinesys.test" in url:
            return cross_home
        elif "horizonlabs.test" in url:
            return lee_home
        return ScrapeResult(url=url, status_code=404, success=False, error="Not found")

    def mock_search_person(name: str, company: str, custom_query=None):
        if "Reed" in name or "Vanguard" in (company or ""):
            return [{
                "title": "Dr. Evelyn Reed - Chief Technology Officer - Vanguard Robotics",
                "url": "https://vanguardrobotics.test/team",
                "snippet": "Dr. Evelyn Reed serves as Chief Technology Officer at Vanguard Robotics, leading enterprise AI and robotics architecture.",
            }]
        return []

    batch_id = "batch_syn_complete_003"
    with patch.object(ScraplingScraper, "fetch_url", side_effect=mock_fetch):
        with patch.object(ScraplingScraper, "search_person", side_effect=mock_search_person):
            progress, paths = pipeline.run_batch(
                batch_id=batch_id,
                input_file=input_csv,
                dry_run=False,
                use_browser=False,
                use_tor=False,
            )

    assert progress.status == "completed"
    assert progress.total_leads == 3
    assert progress.processed_leads == 3

    # 1. Verify all expected deliverable files exist
    batch_dir = output_dir / batch_id
    prioritized_csv = batch_dir / "leads_prioritized.csv"
    enriched_csv = batch_dir / "leads_enriched.csv"
    outreach_ready_csv = batch_dir / "outreach_ready.csv"
    needs_review_csv = batch_dir / "needs_review.csv"
    input_snapshot_csv = batch_dir / "leads_input_snapshot.csv"
    jsonl_profiles = batch_dir / "lead_profiles.jsonl"
    sources_jsonl = batch_dir / "sources.jsonl"
    claims_jsonl = batch_dir / "claims.jsonl"
    errors_csv = batch_dir / "errors.csv"
    summary_json = batch_dir / "summary.json"
    manifest_json = batch_dir / "manifest.json"
    latest_json = output_dir / "latest.json"

    for deliverable in [
        prioritized_csv,
        enriched_csv,
        outreach_ready_csv,
        needs_review_csv,
        input_snapshot_csv,
        jsonl_profiles,
        sources_jsonl,
        claims_jsonl,
        errors_csv,
        summary_json,
        manifest_json,
        latest_json,
    ]:
        assert deliverable.exists(), f"Deliverable {deliverable.name} was not created"

    # 2. Verify profiles
    profiles_dir = batch_dir / "profiles"
    profile_files = list(profiles_dir.glob("*.json"))
    assert len(profile_files) == 3, f"Expected 3 profile JSON files, found {len(profile_files)}"

    # 3. Verify counts agree among all outputs and manifest
    with open(manifest_json, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)
    with open(summary_json, "r", encoding="utf-8") as f:
        summary_data = json.load(f)

    assert manifest_data["total_processed"] == 3
    assert summary_data["total_leads"] == 3
    assert manifest_data["counts"]["total"] == 3

    with open(prioritized_csv, "r", encoding="utf-8") as f:
        p_rows = list(csv.DictReader(f))
    assert len(p_rows) == 3

    with open(jsonl_profiles, "r", encoding="utf-8") as f:
        jsonl_lines = [l for l in f if l.strip()]
    assert len(jsonl_lines) == 3

    with open(outreach_ready_csv, "r", encoding="utf-8") as f:
        ready_rows = list(csv.DictReader(f))
    with open(needs_review_csv, "r", encoding="utf-8") as f:
        review_rows = list(csv.DictReader(f))

    assert len(ready_rows) == 1, "Only Candidate 1 with fully verified identity and role must be outreach_ready"
    assert len(review_rows) == 2, "Candidate 2 and Candidate 3 must be in needs_review"
    assert ready_rows[0]["name"] == "Dr. Evelyn Reed"

    # 4. Verify candidate-specific verification statuses
    reed_profile = next(json.loads(pf.read_text(encoding="utf-8")) for pf in profile_files if "reed" in pf.name.lower())
    cross_profile = next(json.loads(pf.read_text(encoding="utf-8")) for pf in profile_files if "cross" in pf.name.lower())
    lee_profile = next(json.loads(pf.read_text(encoding="utf-8")) for pf in profile_files if "lee" in pf.name.lower())

    # Candidate 1: Fully verified -> P0
    assert reed_profile["priority"]["numeric_priority"] == 0
    assert reed_profile["contact_readiness"]["has_name"] is True
    assert reed_profile["contact_readiness"]["has_verified_role"] is True
    assert reed_profile["contact_readiness"]["has_company_context"] is True
    assert reed_profile["contact_readiness"]["status"] in ("ready", "ready_with_caveat")

    # Candidate 2: High fit blocked from P0 because role/identity is unverified
    assert cross_profile["priority"]["numeric_priority"] >= 1
    assert cross_profile["contact_readiness"]["has_verified_role"] is False
    assert "current_role_not_verified" in cross_profile["contact_readiness"]["blockers"]
    assert cross_profile["contact_readiness"]["status"] != "ready"

    # Candidate 3: Unverified role and unprobed contact
    assert lee_profile["priority"]["numeric_priority"] >= 1
    assert lee_profile["contact_readiness"]["has_verified_role"] is False
    assert lee_profile["contact_readiness"]["status"] != "ready"

    # 5. Verify every referenced source_id in claims actually exists in the sources list
    for prof in [reed_profile, cross_profile, lee_profile]:
        source_id_map = {s["source_id"]: s for s in prof.get("sources", [])}
        for clm in prof.get("claims", []):
            for sid in clm.get("source_ids", []):
                assert sid in source_id_map, f"Claim references unknown source_id '{sid}' in lead {prof.get('lead_id')}"

    # 6. Verify atomic latest.json pointer
    with open(latest_json, "r", encoding="utf-8") as f:
        latest_data = json.load(f)
    assert latest_data["batch_id"] == batch_id
    assert Path(latest_data["manifest_path"]).resolve() == manifest_json.resolve()

    # 7. Verify batch immutability: rerun without resume=True must be rejected
    with pytest.raises(ValueError) as exc_info:
        pipeline.run_batch(
            batch_id=batch_id,
            input_file=input_csv,
            dry_run=False,
            resume=False,
        )
    assert "is finalized" in str(exc_info.value) or "immutable" in str(exc_info.value)
