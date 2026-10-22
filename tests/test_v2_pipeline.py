"""Integration and unit tests for V2 pipeline features:
- SSRF protection
- Claim provenance and verification
- Evidence-grounded icebreaker and outreach drafts
- Decoupled scoring model
- Batch storage isolation, batch IDs, and fingerprint cache invalidation
- Multi-file exports (outreach_ready, needs_review, manifest, summary)
"""

import json
from pathlib import Path
import re
from unittest.mock import MagicMock, patch
import pytest

from src.lead_research.exporter import LeadExporter
from src.lead_research.fingerprint import create_batch_id, research_fingerprint
from src.lead_research.icebreaker import build_icebreaker, extract_public_signals
from src.lead_research.pipeline import ResearchPipeline
from src.lead_research.research import LeadResearcher
from src.lead_research.schemas import (
    ColdEmailContext,
    ContactReadiness,
    Icebreaker,
    LeadClaim,
    LeadInput,
    LeadProfile,
    PriorityInfo,
    ProfessionalContext,
    PublicSignal,
    ResearchMetadata,
    ScoringBreakdown,
    SealAPIRelevance,
    SourceEvidence,
    migrate_profile_v1_to_v2,
)
from src.lead_research.scoring import LeadScorer
from src.lead_research.scraper import ScrapeResult, ScraplingScraper, is_safe_url


def test_ssrf_protection_blocks_private_and_loopback():
    unsafe_targets = [
        "http://127.0.0.1:8000/internal",
        "http://localhost:3000",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/admin",
        "http://192.168.1.1/router",
        "http://172.16.0.10/database",
        "ftp://example.com/file",
        "javascript:alert(1)",
    ]
    for url in unsafe_targets:
        safe, reason = is_safe_url(url)
        assert not safe, f"URL {url} should be blocked by SSRF protection, but was allowed. Reason: {reason}"

    safe_targets = [
        "https://www.google.com",
        "https://github.com/Patel-Menil",
        "http://example.com",
    ]
    for url in safe_targets:
        safe, reason = is_safe_url(url)
        assert safe, f"Public URL {url} should be allowed, got error: {reason}"


def test_research_fingerprint_invalidation():
    lead_input = {
        "name": "Elena Rostova",
        "company": "CyberShield AI",
        "job_title": "Head of Platform Architecture",
        "company_website": "cybershield.ai",
        "professional_email": "elena@cybershield.ai",
        "linkedin_url": "https://linkedin.com/in/elena-rostova",
    }
    fp1 = research_fingerprint(lead_input, pipeline_version="2.0.0", schema_version="2.0.0")
    fp2 = research_fingerprint(lead_input, pipeline_version="2.0.0", schema_version="2.0.0")
    assert fp1 == fp2, "Identical inputs must yield identical fingerprints"

    # Fingerprint must invalidate if config or version changes
    fp_v3 = research_fingerprint(lead_input, pipeline_version="2.1.0", schema_version="2.0.0")
    assert fp1 != fp_v3, "Changing pipeline version must invalidate cache fingerprint"

    # Fingerprint must invalidate if lead input changes
    modified_lead = dict(lead_input, company="OtherCo")
    fp_mod = research_fingerprint(modified_lead, pipeline_version="2.0.0", schema_version="2.0.0")
    assert fp1 != fp_mod, "Changing lead data must invalidate cache fingerprint"


def test_batch_id_uniqueness_and_format():
    batch_ids = [create_batch_id() for _ in range(20)]
    assert len(set(batch_ids)) == 20, "Batch IDs must be strictly unique"
    pattern = r"^batch_\d{8}T\d{6}Z_[a-f0-9]{8}$"
    for b_id in batch_ids:
        assert re.match(pattern, b_id), f"Batch ID {b_id} does not match required format"


def test_decoupled_scoring_evaluation():
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="test_lead_01",
        name="Marcus Vance",
        first_name="Marcus",
        last_name="Vance",
        job_title="VP of Infrastructure",
        company="CloudMatrix",
        company_website="https://cloudmatrix.io",
        professional_email="marcus@cloudmatrix.io",
        industry="Computer Software",
    )
    prof_ctx = ProfessionalContext(
        responsibilities=["Platform Engineering", "Kubernetes cluster security", "API gateways"],
        technical_interests=["AI agent infrastructure", "Zero-trust API access"],
        public_projects=[],
        recent_developments=["CloudMatrix expanded agent API platform"],
        sealapi_relevance=SealAPIRelevance(
            summary="CloudMatrix provides agent APIs that require enterprise authentication guardrails.",
            relevant_use_cases=["API token governance", "Secure tool calling for LLMs"],
            evidence_points=["https://cloudmatrix.io/platform"],
        ),
    )
    sources = [
        SourceEvidence(
            source_id="src_001",
            source_url="https://cloudmatrix.io/team",
            source_type="official_company",
            evidence_quality=0.95,
            facts_supported=["Marcus Vance is VP of Infrastructure at CloudMatrix"],
        ),
        SourceEvidence(
            source_id="src_002",
            source_url="https://cloudmatrix.io/blog/ai-agents",
            source_type="official_company_blog",
            evidence_quality=0.90,
            facts_supported=["CloudMatrix introduces agent workflow APIs"],
        ),
    ]

    # Without verified claims, missing claims list must NOT trigger weak fallback.
    # After identity gate fix: claims=None means identity is unverified, blocking P0.
    p_info_no_claims, breakdown_no_claims, readiness_no_claims = scorer.evaluate_lead(
        lead=lead,
        prof_context=prof_ctx,
        sources=sources,
        identity_score=0.90,
        researched_text="Marcus Vance leads infrastructure engineering at CloudMatrix.",
    )
    assert breakdown_no_claims.lead_fit_score >= 70.0
    assert p_info_no_claims.numeric_priority >= 1  # P0 blocked: no verified claims
    assert readiness_no_claims.status == "needs_research"
    assert "identity_not_verified" in readiness_no_claims.blockers
    assert "current_role_not_verified" in readiness_no_claims.blockers
    assert "company_not_verified" in readiness_no_claims.blockers

    # With verified claims, role and company are established
    from src.lead_research.schemas import LeadClaim
    claims = [
        LeadClaim(claim_id="c1", field="name", value="Marcus Vance", status="verified", source_ids=["src_001"]),
        LeadClaim(claim_id="c2", field="job_title", value="VP of Infrastructure", status="verified", source_ids=["src_001"]),
        LeadClaim(claim_id="c3", field="company", value="CloudMatrix", status="verified", source_ids=["src_001"]),
        LeadClaim(claim_id="c4", field="professional_email", value="marcus@cloudmatrix.io", status="input_provided", source_ids=["src_001"]),
    ]

    p_info, breakdown, readiness = scorer.evaluate_lead(
        lead=lead,
        prof_context=prof_ctx,
        sources=sources,
        identity_score=0.90,
        researched_text="Marcus Vance leads infrastructure engineering at CloudMatrix.",
        claims=claims,
    )

    # 1. Lead Fit Score is high (VP of Infrastructure at software company with active AI/API context)
    assert breakdown.lead_fit_score >= 70.0
    # 2. Priority 0 assigned
    assert p_info.numeric_priority == 0
    # 3. Verification confidence is strong
    assert breakdown.verification_confidence >= 0.75
    # 4. Readiness is ready or ready_with_caveat
    assert readiness.status in ("ready", "ready_with_caveat")
    assert readiness.has_usable_contact_channel is True
    assert readiness.has_name is True
    assert readiness.has_verified_role is True
    assert readiness.has_company_context is True


def test_icebreaker_generation_no_hardcoded_dates():
    lead = LeadInput(
        lead_id="test_lead_02",
        name="Elena Rostova",
        first_name="Elena",
        last_name="Rostova",
        job_title="Head of Platform Architecture",
        company="CyberShield AI",
        company_website="https://cybershield.ai",
        professional_email="elena@cybershield.ai",
    )
    sources = [
        SourceEvidence(
            source_id="src_001",
            source_url="https://cybershield.ai",
            source_type="company_website",
            title="CyberShield AI - Autonomous Agent Security Platform",
            evidence_quality=0.95,
            relevant_excerpt="CyberShield AI launches enterprise multi-agent workflows with API integrations.",
            facts_supported=["CyberShield AI features agentic workflow integrations"],
        )
    ]
    signals = extract_public_signals(lead=lead, fetched_sources=sources, candidate_bio_snippets=[])
    assert len(signals) >= 1
    assert signals[0].source_ids == ["src_001"]

    icebreaker = build_icebreaker(lead=lead, signals=signals, sources=sources, identity_verified=True)
    assert icebreaker.personalization_status in ("ready", "needs_review")
    assert icebreaker.source_ids == ["src_001"]
    assert icebreaker.conversation_question is not None

    draft = icebreaker.outreach_draft
    assert draft is not None
    full_text = draft.get("full_body", "")

    # Zero-fabrication & no hardcoded dates verification:
    forbidden_terms = ["next tuesday", "next wednesday", "tomorrow at", "hop on a call next tuesday"]
    for term in forbidden_terms:
        assert term not in full_text.lower(), f"Draft contains prohibited hardcoded date '{term}'"


def test_exporter_batch_isolation_and_atomic_latest(tmp_path: Path):
    exporter = LeadExporter(tmp_path)
    lead_input = LeadInput(
        lead_id="person_001",
        name="Alice Wonderland",
        first_name="Alice",
        company="Wonderland Security",
        company_website="https://wonderland.io",
        job_title="CTO",
        professional_email="alice@wonderland.io",
        industry="Cybersecurity",
    )
    profile = LeadProfile(
        schema_version="2.0.0",
        lead_id="person_001",
        identity={
            "name": "Alice Wonderland",
            "first_name": "Alice",
            "job_title": "CTO",
            "company": "Wonderland Security",
            "professional_email": "alice@wonderland.io",
            "company_website": "https://wonderland.io",
        },
        professional_context=ProfessionalContext(),
        priority=PriorityInfo(numeric_priority=0, reason="High fit", score=85.0, confidence=0.9),
        sources=[
            SourceEvidence(
                source_id="src_001",
                source_url="https://wonderland.io",
                source_type="official_company",
                evidence_quality=0.9,
                facts_supported=["Alice is CTO"],
            )
        ],
        claims=[
            LeadClaim(
                claim_id="clm_001",
                field="current_title",
                value="CTO",
                status="verified",
                source_ids=["src_001"],
                confidence=0.9,
            )
        ],
        contact_readiness=ContactReadiness(
            status="ready",
            has_name=True,
            has_verified_role=True,
            has_company_context=True,
            has_usable_contact_channel=True,
            has_evidence_based_icebreaker=True,
            blockers=[],
        ),
        research_metadata=ResearchMetadata(
            research_status="completed",
            sources_examined=1,
            errors_and_limitations=[],
        ),
    )

    batch_id = "batch_test_001"
    paths = exporter.export_batch(
        batch_id=batch_id,
        leads_with_profiles=[(lead_input, profile)],
        errors=[],
        batch_metadata={
            "batch_id": batch_id,
            "total_leads": 1,
            "completed_leads": 1,
            "outreach_ready": 1,
            "needs_review": 0,
        },
    )

    batch_dir = tmp_path / batch_id
    # Check that deliverables exist in the batch directory
    assert (batch_dir / "leads_prioritized.csv").exists()
    assert (batch_dir / "outreach_ready.csv").exists()
    assert (batch_dir / "needs_review.csv").exists()
    assert (batch_dir / "summary.json").exists()
    assert (batch_dir / "manifest.json").exists()
    assert (batch_dir / "lead_profiles.jsonl").exists()
    assert (batch_dir / "claims.jsonl").exists()
    assert (batch_dir / "sources.jsonl").exists()

    # Read outreach_ready.csv and verify alice is in it
    with open(batch_dir / "outreach_ready.csv", "r", encoding="utf-8") as f:
        content = f.read()
        assert "Alice Wonderland" in content
        assert "alice@wonderland.io" in content


def test_input_provided_facts_are_not_verified_by_default():
    lead = LeadInput(
        lead_id="person_input_01",
        name="Morgan Freeman",
        first_name="Morgan",
        last_name="Freeman",
        job_title="VP of Product",
        company="Horizon Labs",
        company_website="https://horizonlabs.io",
        professional_email="morgan@horizonlabs.io",
    )
    researcher = LeadResearcher()
    profile = researcher.research_lead(lead, skip_web_scrape=True)

    # Input-provided claims must never be automatically labeled "verified"
    for claim in profile.claims:
        assert claim.status in ("input_provided", "needs_review", "unverified"), (
            f"Claim for {claim.field} has status '{claim.status}', but input claims must not be verified by default"
        )
        assert claim.confidence <= 0.50

    # Abbreviated names get needs_review and lower confidence
    lead_abbr = LeadInput(
        lead_id="person_abbr_01",
        name="Jon B.",
        company="Horizon Labs",
    )
    profile_abbr = researcher.research_lead(lead_abbr, skip_web_scrape=True)
    name_claims = [c for c in profile_abbr.claims if c.field == "name"]
    assert len(name_claims) == 1
    assert name_claims[0].status == "needs_review"
    assert name_claims[0].confidence <= 0.30


def test_company_homepage_fetch_does_not_verify_person_identity():
    lead = LeadInput(
        lead_id="person_no_mention_01",
        name="Arthur Dent",
        first_name="Arthur",
        last_name="Dent",
        job_title="Head of Safety",
        company="Megadodo Publications",
        company_website="https://megadodo.com",
    )
    mock_scraper = MagicMock()
    # Mock company page fetch returning company info without mentioning Arthur Dent
    mock_scraper.fetch_url.return_value = ScrapeResult(
        success=True,
        url="https://megadodo.com",
        title="Megadodo Publications - Galactic Guides",
        meta_description="Publishers of the Hitchhiker's Guide and digital encyclopedias.",
        extracted_text="Megadodo Publications produces galaxy-wide guidebooks and digital APIs. Our leadership team is based in Ursa Minor.",
        status_code=200,
        engine="test_engine",
    )
    mock_scraper.search_public_person.return_value = []

    researcher = LeadResearcher(scraper=mock_scraper)
    profile = researcher.research_lead(lead)

    # Company claim should be verified
    company_claim = next(c for c in profile.claims if c.field == "company")
    assert company_claim.status == "verified"
    assert company_claim.confidence >= 0.90

    # Person claims must NOT be verified because company page does not mention Arthur Dent
    name_claim = next(c for c in profile.claims if c.field == "name")
    assert name_claim.status != "verified"
    title_claim = next(c for c in profile.claims if c.field == "job_title")
    assert title_claim.status != "verified"


def test_ai_capability_vs_product_launch_signal_distinction():
    lead = LeadInput(
        lead_id="test_lead_signals",
        name="Ada Lovelace",
        company="Analytical Engine Co",
        company_website="https://analytical.org",
    )
    # 1. Company with AI/platform keywords but no announcement/launch terms -> ai_capability
    cap_source = SourceEvidence(
        source_id="src_cap_01",
        source_url="https://analytical.org",
        source_type="company_website",
        title="Analytical Engine Co - AI Workflows",
        relevant_excerpt="We provide an AI platform and automation API for algorithmic analysis and data pipelines.",
        evidence_quality=0.9,
    )
    cap_signals = extract_public_signals(lead=lead, fetched_sources=[cap_source], candidate_bio_snippets=[])
    assert len(cap_signals) >= 1
    assert cap_signals[0].signal_type == "ai_capability"
    assert cap_signals[0].signal_type != "product_launch"

    # 2. Company explicitly announcing/introducing a new launch -> product_launch
    launch_source = SourceEvidence(
        source_id="src_launch_01",
        source_url="https://analytical.org/news",
        source_type="company_blog",
        title="Analytical Engine Co - News",
        relevant_excerpt="Today we are thrilled to announce and introduce our new autonomous security agent platform.",
        evidence_quality=0.9,
    )
    launch_signals = extract_public_signals(lead=lead, fetched_sources=[launch_source], candidate_bio_snippets=[])
    assert len(launch_signals) >= 1
    assert any(s.signal_type == "product_launch" for s in launch_signals)


def test_legacy_profile_without_fingerprint_rejected_on_resume(tmp_path: Path):
    pipeline = ResearchPipeline(output_dir=tmp_path / "output", concurrency=1)

    legacy_profile_dict = {
        "lead_id": "lead_legacy_01",
        "identity": {"name": "Test User", "company": "Legacy Corp"},
        "professional_context": {},
        "priority": {"numeric_priority": 2, "reason": "Legacy", "score": 10.0, "confidence": 0.5},
        "sources": [],
        "claims": [],
        "contact_readiness": {"status": "needs_research"},
        "research_metadata": {
            "schema_version": "1.0.0",
            "pipeline_version": "1.0.0",
            "research_fingerprint": None,
        },
    }

    checkpoints_dir = tmp_path / "output" / "batches" / "batch_resume_test" / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = checkpoints_dir / "lead_legacy_01.json"
    checkpoint_file.write_text(json.dumps(legacy_profile_dict), encoding="utf-8")

    lead_input = LeadInput(
        lead_id="lead_legacy_01",
        name="Test User",
        company="Legacy Corp",
    )
    expected_fp = research_fingerprint(lead_input.model_dump(), pipeline_version="2.0.0", schema_version="2.0.0")

    with open(checkpoint_file, "r", encoding="utf-8") as f:
        cached_data = json.load(f)
    cached_fp = cached_data.get("research_metadata", {}).get("research_fingerprint")
    assert cached_fp is None
    assert cached_fp != expected_fp


def test_schema_migration_v1_to_v2():
    v1_data = {
        "lead_id": "legacy_v1_lead",
        "identity": {"name": "Grace Hopper", "job_title": "Admiral"},
        "contact": {"email": "grace@navy.mil"},
        "company": {"name": "US Navy"},
        "sources": [],
    }
    migrated = migrate_profile_v1_to_v2(v1_data)

    assert migrated["schema_version"] == "2.0.0"
    assert migrated["research_metadata"]["schema_version"] == "2.0.0"
    assert migrated["research_metadata"]["pipeline_version"] == "2.0.0"
    assert isinstance(migrated["claims"], list)
    assert migrated["contact_readiness"]["has_name"] is True
    assert migrated["contact_readiness"]["has_usable_contact_channel"] is True


def test_worker_exception_handled_as_failed_profile_in_pipeline(tmp_path: Path):
    input_csv = tmp_path / "error_leads.csv"
    input_csv.write_text(
        "Full Name,Company Name,Email\n"
        "Broken Worker,CrashCorp,crash@crashcorp.io\n",
        encoding="utf-8"
    )
    pipeline = ResearchPipeline(output_dir=tmp_path / "output", concurrency=1)

    with patch.object(LeadResearcher, "research_lead", side_effect=RuntimeError("Simulated worker network failure")):
        progress, paths = pipeline.run_batch(
            batch_id="batch_worker_err_01",
            input_file=input_csv,
            dry_run=False,
        )

    assert progress.status == "failed"
    assert progress.failed_count == 1
    assert progress.total_leads == 1

    batch_dir = tmp_path / "output" / "batch_worker_err_01"
    assert (batch_dir / "errors.csv").exists()
    assert (batch_dir / "errors.jsonl").exists()

    errors_csv_content = (batch_dir / "errors.csv").read_text(encoding="utf-8")
    assert "Simulated worker network failure" in errors_csv_content

    lead_profiles_jsonl = (batch_dir / "lead_profiles.jsonl").read_text(encoding="utf-8")
    assert "Simulated worker network failure" in lead_profiles_jsonl
    assert "Broken Worker" in lead_profiles_jsonl


def test_company_homepage_mention_does_not_verify_job_title():
    scraper = ScraplingScraper(use_browser=False, use_tor=False)
    researcher = LeadResearcher(scraper=scraper)
    lead = LeadInput(
        lead_id="lead_test_homepage",
        name="Taylor Brooks",
        job_title="VP of AI Architecture",
        company="NexusFlow AI",
        company_website="https://nexusflow.ai",
    )
    # Mock company homepage mentioning name in general text without a leadership bio
    mock_res = ScrapeResult(
        url="https://nexusflow.ai",
        status_code=200,
        success=True,
        title="NexusFlow AI - Enterprise Workflows",
        extracted_text="NexusFlow AI powers autonomous agents. Special thanks to Taylor Brooks and our advisors for consulting.",
    )
    with patch.object(researcher.scraper, "fetch_url", return_value=mock_res):
        with patch.object(researcher.scraper, "search_person", return_value=[]):
            profile = researcher.research_lead(lead, skip_web_scrape=False)

    name_claim = next(c for c in profile.claims if c.field == "name")
    title_claim = next(c for c in profile.claims if c.field == "job_title")

    # Name is partially verified from company homepage mention, but NOT fully verified
    assert name_claim.status == "partially_verified"
    assert name_claim.confidence <= 0.80

    # Job title must NOT be verified because homepage mention alone does not corroborate role
    assert title_claim.status != "verified"
    assert "current_role_not_verified" in profile.contact_readiness.blockers
    assert profile.contact_readiness.status != "ready"


def test_search_snippets_do_not_verify_job_title_claim():
    scraper = ScraplingScraper(use_browser=False, use_tor=False)
    researcher = LeadResearcher(scraper=scraper)
    lead = LeadInput(
        lead_id="lead_test_snippets",
        name="Jordan Lee",
        job_title="Chief Information Security Officer",
        company="SecureCloud Inc",
    )
    # Search snippet matching person and company strongly
    mock_candidates = [
        {
            "title": "Jordan Lee - Chief Information Security Officer - SecureCloud Inc | LinkedIn",
            "url": "https://linkedin.com/in/jordan-lee-ciso",
            "snippet": "Jordan Lee is Chief Information Security Officer at SecureCloud Inc leading zero-trust initiatives.",
        }
    ]
    with patch.object(researcher.scraper, "search_person", return_value=mock_candidates):
        profile = researcher.research_lead(lead, skip_web_scrape=False)

    title_claim = next(c for c in profile.claims if c.field == "job_title")
    # Search snippet alone cannot verify current role claim
    assert title_claim.status != "verified"
    assert profile.contact_readiness.has_verified_role is False
    assert "current_role_not_verified" in profile.contact_readiness.blockers


def test_high_fit_score_with_unverified_role_blocks_ready_status():
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="lead_high_fit_unverified_role",
        name="Morgan Hayes",
        job_title="VP of Engineering",
        company="DataVault Systems",
        company_website="https://datavault.io",
        professional_email="morgan@datavault.io",
        industry="Cybersecurity",
    )
    # Unverified role claim despite valid company & email
    claims = [
        LeadClaim(claim_id="c1", field="name", value="Morgan Hayes", status="partially_verified", confidence=0.70, source_ids=["src_01"]),
        LeadClaim(claim_id="c2", field="job_title", value="VP of Engineering", status="unverified", confidence=0.40, source_ids=[]),
        LeadClaim(claim_id="c3", field="company", value="DataVault Systems", status="verified", confidence=0.95, source_ids=["src_01"]),
        LeadClaim(claim_id="c4", field="professional_email", value="morgan@datavault.io", status="input_provided", confidence=0.50, source_ids=["src_01"]),
    ]
    p_info, breakdown, readiness = scorer.evaluate_lead(
        lead=lead,
        prof_context=ProfessionalContext(),
        sources=[],
        identity_score=0.75,
        claims=claims,
        researched_text="DataVault systems engineering overview",
    )
    # High fit score does NOT compensate for unverified role
    assert breakdown.lead_fit_score >= 60.0
    assert readiness.has_verified_role is False
    assert "current_role_not_verified" in readiness.blockers
    assert readiness.status == "needs_research"
    assert readiness.status != "ready"


def test_unprobed_email_sets_ready_with_caveat():
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="lead_unprobed_email",
        name="Casey Morgan",
        job_title="VP of Security",
        company="ShieldNet",
        company_website="https://shieldnet.com",
        professional_email="casey@shieldnet.com",
        industry="Cybersecurity",
    )
    claims = [
        LeadClaim(claim_id="c1", field="name", value="Casey Morgan", status="verified", confidence=0.90, source_ids=["src_01"]),
        LeadClaim(claim_id="c2", field="job_title", value="VP of Security", status="verified", confidence=0.90, source_ids=["src_01"]),
        LeadClaim(claim_id="c3", field="company", value="ShieldNet", status="verified", confidence=0.95, source_ids=["src_01"]),
        LeadClaim(claim_id="c4", field="professional_email", value="casey@shieldnet.com", status="input_provided", confidence=0.50, source_ids=["src_01"]),
    ]
    icebreaker = Icebreaker(
        text="I noticed ShieldNet's public developer API portal.",
        icebreaker_type="product_integration",
        source_ids=["src_01"],
        confidence=0.85,
        personalization_status="ready",
    )
    p_info, breakdown, readiness = scorer.evaluate_lead(
        lead=lead,
        prof_context=ProfessionalContext(),
        sources=[
            SourceEvidence(
                source_id="src_01",
                source_url="https://shieldnet.com",
                source_type="official_company",
                evidence_quality=0.90,
                facts_supported=["Casey Morgan corroborated on official domain", "Company identity corroborated"],
            )
        ],
        identity_score=0.90,
        claims=claims,
        icebreaker=icebreaker,
        researched_text="Casey Morgan leads security at ShieldNet.",
    )
    # Core identity, role, company, and icebreaker are verified, but email is unprobed syntax-only
    assert readiness.has_verified_role is True
    assert readiness.has_name is True
    assert readiness.has_company_context is True
    assert readiness.has_evidence_based_icebreaker is True
    assert "email_syntax_valid_unprobed" in readiness.blockers
    assert readiness.status == "ready_with_caveat"


def test_icebreaker_grounding_non_technical_snippet_no_leadership_fabrication():
    lead = LeadInput(
        lead_id="lead_hr_exec",
        name="Samira Khan",
        job_title="Director of People Operations",
        company="ScaleFlow",
    )
    candidate_bios = [
        {
            "source_id": "src_bio_01",
            "title": "Samira Khan - People Operations - ScaleFlow",
            "snippet": "Samira Khan manages human resources, organizational development, and recruiting at ScaleFlow.",
        }
    ]
    signals = extract_public_signals(lead=lead, fetched_sources=[], candidate_bio_snippets=candidate_bios)
    assert len(signals) == 1
    # Must NOT classify non-technical HR biography as technical_work
    assert signals[0].signal_type == "professional_background"
    assert signals[0].signal_type != "technical_work"

    icebreaker = build_icebreaker(lead=lead, signals=signals, sources=[], identity_verified=True)
    # Must NOT fabricate technical leadership statement
    assert "technical leadership" not in (icebreaker.text or "").lower()


def test_csv_header_aliases_normalized_identically_in_fingerprint():
    raw_csv_lead = {
        "Full Name": "Devon Miller",
        "Company Name": "Apex Systems",
        "Job Title": "Chief Technology Officer",
        "Email": "devon@apexsystems.com",
        "Company Website": "apexsystems.com",
        "Industry": "Information Technology",
        "Keywords": "cloud, security, kubernetes",
    }
    canonical_lead = {
        "name": "Devon Miller",
        "company": "Apex Systems",
        "job_title": "Chief Technology Officer",
        "professional_email": "devon@apexsystems.com",
        "company_website": "apexsystems.com",
        "industry": "Information Technology",
        "keywords": "cloud, security, kubernetes",
    }
    fp_raw = research_fingerprint(raw_csv_lead, pipeline_version="2.0.0", schema_version="2.0.0")
    fp_canonical = research_fingerprint(canonical_lead, pipeline_version="2.0.0", schema_version="2.0.0")

    # Raw CSV headers and canonical keys must produce identical fingerprints
    assert fp_raw == fp_canonical

    # Changing any single field must invalidate the fingerprint
    assert fp_raw != research_fingerprint(dict(raw_csv_lead, **{"Job Title": "VP of Architecture"}))
    assert fp_raw != research_fingerprint(dict(raw_csv_lead, **{"Email": "dmiller@apexsystems.com"}))
    assert fp_raw != research_fingerprint(dict(raw_csv_lead, **{"Company Name": "Apex Security"}))
    assert fp_raw != research_fingerprint(dict(raw_csv_lead, **{"Company Website": "apexsecurity.io"}))


def test_ssrf_rejects_credentials_and_prevalidates_unsafe_redirects():
    # URL credentials must be rejected
    safe, reason = is_safe_url("http://user:password@example.com")
    assert not safe
    assert "credentials" in reason.lower()

    safe, reason = is_safe_url("https://admin:token@10.0.0.1/dashboard")
    assert not safe

    # Mock redirect to internal metadata service
    scraper = ScraplingScraper(use_browser=False, use_tor=False)
    redirect_response = MagicMock()
    redirect_response.status = 302
    redirect_response.headers = {"location": "http://169.254.169.254/latest/meta-data/"}

    with patch.object(scraper, "_execute_pinned_get", return_value=redirect_response):
        result = scraper.fetch_url("http://example.com/test-redirect")

    assert result.status_code == 400
    assert result.success is False
    assert "SSRF" in result.error or "Redirect destination blocked" in result.error

    # Mock redirect loop
    loop_response1 = MagicMock()
    loop_response1.status = 302
    loop_response1.headers = {"location": "http://example.com/hop2"}

    loop_response2 = MagicMock()
    loop_response2.status = 302
    loop_response2.headers = {"location": "http://example.com/hop1"}

    with patch.object(scraper, "_execute_pinned_get", side_effect=[loop_response1, loop_response2, loop_response1]):
        result = scraper.fetch_url("http://example.com/hop1")

    assert result.status_code == 400
    assert result.success is False
    assert "redirect loop" in result.error.lower()


def test_homepage_name_mention_does_not_raise_candidate_identity_score():
    scraper = ScraplingScraper(use_browser=False, use_tor=False)
    researcher = LeadResearcher(scraper=scraper)
    lead = LeadInput(
        lead_id="lead_test_no_shortcut",
        name="Jordan Lee",
        job_title="VP of Product",
        company="Acrobatics Security",
        company_website="https://acrobatics.io",
    )
    # Homepage mentions Jordan Lee in an acknowledgement footer
    mock_res = ScrapeResult(
        url="https://acrobatics.io",
        status_code=200,
        success=True,
        title="Acrobatics Security - Cloud Security",
        extracted_text="Acrobatics Security provides zero-trust identity management. Acknowledgements: Jordan Lee, contributor.",
    )
    with patch.object(researcher.scraper, "fetch_url", return_value=mock_res):
        with patch.object(researcher.scraper, "search_person", return_value=[]):
            profile = researcher.research_lead(lead, skip_web_scrape=False)

    # Candidate identity score must NOT be raised to 0.85
    assert profile.priority.score < 80.0
    # Identity is not independently verified
    name_claim = next(c for c in profile.claims if c.field == "name")
    assert name_claim.status != "verified"
    assert profile.contact_readiness.has_verified_role is False
    assert profile.contact_readiness.status != "ready"


def test_ssrf_blocks_ipv4_mapped_ipv6_and_unspecified():
    safe, reason = is_safe_url("http://[::ffff:127.0.0.1]/status")
    assert not safe
    assert "private/reserved IP" in reason or "blocked" in reason

    safe, reason = is_safe_url("http://[::ffff:192.168.1.1]/admin")
    assert not safe

    safe, reason = is_safe_url("http://0.0.0.0/test")
    assert not safe

    safe, reason = is_safe_url("http://[::]/test")
    assert not safe


def test_cache_fingerprint_changes_with_research_config_and_versions():
    lead = LeadInput(
        lead_id="lead_fp_cfg_test",
        name="Sam Rivera",
        job_title="Head of AI",
        company="NeuralWave",
    )
    fp_base = research_fingerprint(
        lead.model_dump(),
        pipeline_version="2.1.0",
        schema_version="2.0.0",
        research_config={"dry_run": False, "use_browser": False, "use_tor": False},
    )

    # Toggling browser mode changes fingerprint
    fp_browser = research_fingerprint(
        lead.model_dump(),
        pipeline_version="2.1.0",
        schema_version="2.0.0",
        research_config={"dry_run": False, "use_browser": True, "use_tor": False},
    )
    assert fp_base != fp_browser

    # Toggling Tor mode changes fingerprint
    fp_tor = research_fingerprint(
        lead.model_dump(),
        pipeline_version="2.1.0",
        schema_version="2.0.0",
        research_config={"dry_run": False, "use_browser": False, "use_tor": True},
    )
    assert fp_base != fp_tor

    # Version bump changes fingerprint
    fp_v3 = research_fingerprint(
        lead.model_dump(),
        pipeline_version="3.0.0",
        schema_version="2.0.0",
        research_config={"dry_run": False, "use_browser": False, "use_tor": False},
    )
    assert fp_base != fp_v3


def test_lead_exporter_rejects_overwriting_finalized_batch(tmp_path: Path):
    exporter = LeadExporter(output_base_dir=tmp_path / "batches")
    batch_id = "batch_finalized_test_01"
    batch_dir = tmp_path / "batches" / batch_id
    batch_dir.mkdir(parents=True)
    manifest_file = batch_dir / "manifest.json"
    manifest_file.write_text(
        json.dumps({"batch_id": batch_id, "status": "completed", "total_processed": 1}),
        encoding="utf-8",
    )

    lead = LeadInput(lead_id="lead_1", name="Test Lead", company="Acme")
    profile = LeadProfile(
        schema_version="2.0.0",
        lead_id="lead_1",
        identity={"name": "Test Lead"},
        company={"name": "Acme"},
        contact={},
        priority=PriorityInfo(numeric_priority=1, reason="Test", score=50.0, confidence=0.5, supporting_evidence=[]),
        contact_readiness=ContactReadiness(),
        scoring_breakdown=ScoringBreakdown(lead_fit_score=50.0, verification_confidence=0.5, readiness_status="needs_research", explanations=[]),
        research_metadata=ResearchMetadata(research_status="completed", last_research_timestamp="2026-10-21T00:00:00Z", sources_examined=1, errors_and_limitations=[]),
        professional_context=ProfessionalContext(),
        icebreaker=Icebreaker(),
        cold_email_context=ColdEmailContext(suggested_call_to_action=""),
        claims=[],
        sources=[],
    )

    with pytest.raises(ValueError, match="immutable"):
        exporter.export_batch(batch_id=batch_id, leads_with_profiles=[(lead, profile)])


def test_strict_identity_gate_blocks_high_scoring_unverified_candidate():
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="test_lead_strict_id",
        name="Alexander Hamilton",
        job_title="Chief Information Security Officer",
        company="Treasury AI",
        industry="Financial Services",
        professional_email="alex@treasury.ai",
        raw_data={"Keywords": "ai, security, api, zero trust, compliance, cloud"}
    )
    prof_ctx = ProfessionalContext()
    sources = [
        SourceEvidence(
            source_id="src_snip_1",
            source_url="https://duckduckgo.com",
            source_type="search_snippet",
            evidence_quality=0.60,
            facts_supported=["Search Snippet: Alexander Hamilton Treasury AI"],
        )
    ]
    # Name claim is partially verified or input_provided, NOT verified
    claims_unverified = [
        LeadClaim(claim_id="c1", field="name", value="Alexander Hamilton", status="partially_verified", source_ids=["src_snip_1"]),
        LeadClaim(claim_id="c2", field="job_title", value="Chief Information Security Officer", status="verified", source_ids=["src_snip_1"]),
        LeadClaim(claim_id="c3", field="company", value="Treasury AI", status="verified", source_ids=["src_snip_1"]),
        LeadClaim(claim_id="c4", field="professional_email", value="alex@treasury.ai", status="verified", source_ids=["src_snip_1"]),
    ]

    # Even with high identity_score (0.95) and high fit score (>80), unverified name claim must block identity gate
    p_info, breakdown, readiness = scorer.evaluate_lead(
        lead=lead,
        prof_context=prof_ctx,
        sources=sources,
        identity_score=0.95,
        claims=claims_unverified,
    )
    assert "identity_not_verified" in readiness.blockers
    assert readiness.has_name is False
    assert readiness.status != "ready"
    assert p_info.numeric_priority != 0  # Blocked from Priority 0


def test_company_corroboration_distinguishes_genuine_from_misleading_or_parked():
    from src.lead_research.research import is_company_corroborated

    # 1. Genuine company match
    ok, reason = is_company_corroborated(
        lead_company="Apex Security Systems",
        original_url="https://apexsecurity.io",
        final_url="https://apexsecurity.io",
        title="Apex Security — Zero Trust Cloud Defense",
        meta_desc="Apex Security provides zero trust API protection.",
        extracted_text="Welcome to Apex Security Systems. We secure enterprise cloud APIs.",
    )
    assert ok is True

    # 2. Parked domain / domain for sale
    ok, reason = is_company_corroborated(
        lead_company="Apex Security Systems",
        original_url="https://apexsecurity.io",
        final_url="https://apexsecurity.io",
        title="Apex Security - Domain For Sale",
        meta_desc="Buy this domain on Dan.com",
        extracted_text="This domain is parked. Buy this domain today.",
    )
    assert ok is False
    assert "parked" in reason.lower()

    # 3. Generic error page / 404
    ok, reason = is_company_corroborated(
        lead_company="Apex Security Systems",
        original_url="https://apexsecurity.io",
        final_url="https://apexsecurity.io",
        title="404 Not Found",
        meta_desc="",
        extracted_text="Page not found. Error 404.",
    )
    assert ok is False

    # 4. Domain equality alone does not verify if company name is completely absent
    ok, reason = is_company_corroborated(
        lead_company="Apex Security Systems",
        original_url="https://unrelated-domain.com",
        final_url="https://unrelated-domain.com",
        title="Blue Sky Travel Agency",
        meta_desc="Book luxury holidays worldwide.",
        extracted_text="Find the best deals on flights and hotels.",
    )
    assert ok is False

    # 5. Misleading redirect to unrelated domain
    ok, reason = is_company_corroborated(
        lead_company="Apex Security Systems",
        original_url="https://apexsecurity.io",
        final_url="https://gamblingportal.biz",
        title="Best Casino Bonuses",
        meta_desc="Play slots online",
        extracted_text="Top casino games online.",
    )
    assert ok is False
    assert "redirected" in reason.lower()


def test_person_role_association_handles_historical_and_testimonials():
    from src.lead_research.research import check_person_role_association

    # 1. Valid current leadership on official bio page
    name_ver, role_ver, reason = check_person_role_association(
        person_name="Rachel Green",
        job_title="Head of Engineering",
        text="Executive Team. Rachel Green is our Head of Engineering overseeing infrastructure.",
        is_bio_page=True,
    )
    assert name_ver is True
    assert role_ver is True

    # 2. Historical / former role
    name_ver, role_ver, reason = check_person_role_association(
        person_name="Rachel Green",
        job_title="Head of Engineering",
        text="Rachel Green previously served as Head of Engineering until 2021 before joining another firm.",
        is_bio_page=True,
    )
    assert name_ver is True
    assert role_ver is False
    assert "historical" in reason.lower() or "past" in reason.lower()

    # 3. Testimonial context
    name_ver, role_ver, reason = check_person_role_association(
        person_name="Rachel Green",
        job_title="Head of Engineering",
        text="What our clients say: 'Amazing service!' - Customer review by Rachel Green, Head of Engineering.",
        is_bio_page=True,
    )
    assert name_ver is False
    assert role_ver is False
    assert "testimonial" in reason.lower()

    # 4. Mention on generic non-bio page
    name_ver, role_ver, reason = check_person_role_association(
        person_name="Rachel Green",
        job_title="Head of Engineering",
        text="Blog article: We interviewed Rachel Green regarding tech trends.",
        is_bio_page=False,
    )
    assert name_ver is False
    assert role_ver is False


def test_ssrf_dns_resolution_failure_fails_closed():
    import socket
    with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name or service not known")):
        safe, reason = is_safe_url("https://unresolvable-ghost-host-test.org/api")
        assert safe is False
        assert "DNS resolution failed" in reason


def test_exporter_reservation_lock_blocks_concurrent_publication(tmp_path: Path):
    exporter = LeadExporter(output_base_dir=tmp_path / "batches")
    batch_id = "batch_concurrent_test_lock"

    # Simulate an active concurrent writer by holding the actual reservation lock
    held_lock = exporter.acquire_batch_lock(batch_id)
    try:
        lead = LeadInput(lead_id="l1", name="Test Lead", company="Acme")
        profile = LeadProfile(
            schema_version="2.0.0",
            lead_id="l1",
            identity={"name": "Test Lead"},
            company={"name": "Acme"},
            contact={},
            priority=PriorityInfo(numeric_priority=1, reason="Test", score=50.0, confidence=0.5, supporting_evidence=[]),
            contact_readiness=ContactReadiness(),
            scoring_breakdown=ScoringBreakdown(lead_fit_score=50.0, verification_confidence=0.5, readiness_status="needs_research", explanations=[]),
            research_metadata=ResearchMetadata(research_status="completed", last_research_timestamp="2026-10-21T00:00:00Z", sources_examined=1, errors_and_limitations=[]),
            professional_context=ProfessionalContext(),
            icebreaker=Icebreaker(),
            cold_email_context=ColdEmailContext(suggested_call_to_action=""),
            claims=[],
            sources=[],
        )

        with pytest.raises(RuntimeError, match="Concurrent export lock detected"):
            exporter.export_batch(batch_id=batch_id, leads_with_profiles=[(lead, profile)])
    finally:
        held_lock.release()


def test_icebreaker_signals_reject_client_marketing_and_outdated_announcements():
    lead = LeadInput(lead_id="lead_ib_test", name="Laura Croft", company="Archeology Digital")

    # 1. Agency marketing: "we help you launch"
    marketing_source = SourceEvidence(
        source_id="src_mkt_1",
        source_url="https://archeologydigital.com/services",
        source_type="company_website",
        facts_supported=["We help you launch your digital business and launch a campaign."],
        relevant_excerpt="We help clients launch products and scale marketing.",
    )
    signals_mkt = extract_public_signals(lead, fetched_sources=[marketing_source], candidate_bio_snippets=[])
    assert not any(s.signal_type == "product_launch" for s in signals_mkt)

    # 2. Outdated announcement from 2020
    outdated_source = SourceEvidence(
        source_id="src_outdated_1",
        source_url="https://archeologydigital.com/news",
        source_type="company_website",
        facts_supported=["Announced in 2020: New legacy platform."],
        relevant_excerpt="Archeology Digital announced in 2020 its new search platform.",
    )
    signals_old = extract_public_signals(lead, fetched_sources=[outdated_source], candidate_bio_snippets=[])
    assert not any(s.signal_type == "product_launch" for s in signals_old)

    # 3. Genuine announcement
    genuine_source = SourceEvidence(
        source_id="src_gen_1",
        source_url="https://archeologydigital.com/press",
        source_type="company_website",
        title="Press Release: Archeology Digital Announces New AI Platform",
        facts_supported=["Archeology Digital unveils AI platform."],
        relevant_excerpt="Today we are proud to announce our new generative AI platform for enterprise search.",
    )
    signals_gen = extract_public_signals(lead, fetched_sources=[genuine_source], candidate_bio_snippets=[])
    assert any(s.signal_type == "product_launch" for s in signals_gen)


def test_claims_none_identity_gate_blocks_priority_0_and_caps_confidence():
    """Regression test for fix.md #2: claims=None must never allow verified identity.

    A high identity score and supplied name must never establish verified identity
    by themselves. When claims is None, the identity gate must block P0, cap
    verification confidence at 0.50, and set readiness to needs_research or not_ready.
    """
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="test_claims_none_gate",
        name="Diana Prince",
        first_name="Diana",
        last_name="Prince",
        job_title="Chief Information Security Officer",
        company="Themyscira Security",
        industry="Cybersecurity",
        professional_email="diana@themyscira.io",
        company_website="https://themyscira.io",
        raw_data={"Keywords": "ai, security, api, zero trust, compliance, cloud"},
    )
    prof_ctx = ProfessionalContext()
    sources = [
        SourceEvidence(
            source_id="src_off_1",
            source_url="https://themyscira.io",
            source_type="official_company",
            evidence_quality=0.95,
            facts_supported=["Company identity corroborated on official domain"],
        ),
    ]

    # claims=None: identity gate MUST block P0
    p_info, breakdown, readiness = scorer.evaluate_lead(
        lead=lead,
        prof_context=prof_ctx,
        sources=sources,
        identity_score=0.99,  # High identity score must not override
        claims=None,
    )
    assert "identity_not_verified" in readiness.blockers, "claims=None must always add identity_not_verified blocker"
    assert readiness.has_name is False, "has_name must be False when identity is unverified"
    assert readiness.status != "ready", "Readiness must not be 'ready' without verified identity"
    assert p_info.numeric_priority >= 1, "P0 must be blocked without verified claims"
    assert breakdown.verification_confidence <= 0.50, "Confidence must be capped at 0.50 for unverified identity"


def test_partially_verified_name_does_not_satisfy_identity_gate():
    """Regression test for fix.md #2: partially_verified name claim must not pass identity gate.

    Only claims with status='verified' and nonempty source_ids satisfy the gate.
    """
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="test_partial_name",
        name="Bruce Wayne",
        first_name="Bruce",
        last_name="Wayne",
        job_title="Head of AI",
        company="Wayne Enterprises",
        industry="Information Technology",
        professional_email="bruce@wayne.com",
        raw_data={"Keywords": "ai, machine learning, cloud, api, security"},
    )
    prof_ctx = ProfessionalContext()
    sources = [
        SourceEvidence(
            source_id="src_web_1",
            source_url="https://wayne.com",
            source_type="official_company",
            evidence_quality=0.90,
            facts_supported=["Company identity corroborated"],
        ),
    ]
    claims_partial = [
        LeadClaim(claim_id="c1", field="name", value="Bruce Wayne", status="partially_verified", source_ids=["src_web_1"]),
        LeadClaim(claim_id="c2", field="job_title", value="Head of AI", status="verified", source_ids=["src_web_1"]),
        LeadClaim(claim_id="c3", field="company", value="Wayne Enterprises", status="verified", source_ids=["src_web_1"]),
        LeadClaim(claim_id="c4", field="professional_email", value="bruce@wayne.com", status="input_provided", source_ids=["src_web_1"]),
    ]

    p_info, breakdown, readiness = scorer.evaluate_lead(
        lead=lead,
        prof_context=prof_ctx,
        sources=sources,
        identity_score=0.95,
        claims=claims_partial,
    )
    assert "identity_not_verified" in readiness.blockers
    assert readiness.has_name is False
    assert p_info.numeric_priority >= 1, "partially_verified name must block P0"
    assert breakdown.verification_confidence <= 0.50


def test_correctly_evidenced_verified_identity_grants_priority_0():
    """Regression test for fix.md #2: correctly evidenced verified identity SHOULD allow P0.

    When name, role, and company claims are all verified with eligible source_ids,
    the identity gate must pass and allow P0 for a high-fit lead.
    """
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="test_verified_identity",
        name="Lara Croft",
        first_name="Lara",
        last_name="Croft",
        job_title="VP of Infrastructure",
        company="Croft Analytics",
        industry="Information Technology",
        professional_email="lara@croftanalytics.com",
        company_website="https://croftanalytics.com",
        raw_data={"Keywords": "ai, machine learning, cloud, api, security, zero trust"},
    )
    prof_ctx = ProfessionalContext()
    sources = [
        SourceEvidence(
            source_id="src_team_1",
            source_url="https://croftanalytics.com/team",
            source_type="official_company",
            evidence_quality=0.95,
            facts_supported=["Lara Croft is VP of Infrastructure at Croft Analytics", "Company identity corroborated"],
        ),
    ]
    claims_verified = [
        LeadClaim(claim_id="c1", field="name", value="Lara Croft", status="verified", source_ids=["src_team_1"]),
        LeadClaim(claim_id="c2", field="job_title", value="VP of Infrastructure", status="verified", source_ids=["src_team_1"]),
        LeadClaim(claim_id="c3", field="company", value="Croft Analytics", status="verified", source_ids=["src_team_1"]),
        LeadClaim(claim_id="c4", field="professional_email", value="lara@croftanalytics.com", status="input_provided", source_ids=["src_team_1"]),
    ]

    p_info, breakdown, readiness = scorer.evaluate_lead(
        lead=lead,
        prof_context=prof_ctx,
        sources=sources,
        identity_score=0.90,
        claims=claims_verified,
    )
    assert "identity_not_verified" not in readiness.blockers
    assert readiness.has_name is True
    assert readiness.has_verified_role is True
    assert readiness.has_company_context is True
    assert p_info.numeric_priority == 0, "Fully verified identity with high-fit lead must achieve P0"
    assert breakdown.verification_confidence > 0.50
    assert readiness.status in ("ready", "ready_with_caveat")


def test_calculate_priority_backward_compat_blocks_p0_without_claims():
    """Regression test for fix.md #2: calculate_priority (backward-compat entry) must block P0.

    calculate_priority passes claims=None internally. After the identity gate fix,
    it must not grant P0 even for the highest-fit leads.
    """
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="test_calc_priority_bc",
        name="Tony Stark",
        first_name="Tony",
        last_name="Stark",
        job_title="Chief Technology Officer",
        company="Stark Industries",
        industry="Artificial Intelligence",
        professional_email="tony@starkindustries.com",
        raw_data={"Keywords": "ai, machine learning, api, zero trust, encryption, compliance"},
    )
    prof_ctx = ProfessionalContext()
    sources = [
        SourceEvidence(
            source_id="src_1",
            source_url="https://starkindustries.com",
            source_type="official_company",
            evidence_quality=0.95,
            facts_supported=["Stark Industries AI platform"],
        ),
    ]

    p_info = scorer.calculate_priority(lead, prof_ctx, sources, researched_text="ai security api")
    # Score is high but P0 blocked because calculate_priority passes claims=None
    assert p_info.score >= 70.0
    assert p_info.numeric_priority >= 1, "calculate_priority (claims=None) must block P0"


def test_invalid_source_ids_rejected_by_identity_gate():
    """Regression test for fix.md #2: Arbitrary/nonexistent source IDs must not satisfy identity verification."""
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="test_invalid_src_id",
        name="Barry Allen",
        first_name="Barry",
        last_name="Allen",
        job_title="Lead Forensic Scientist",
        company="Central City Police",
        professional_email="barry@ccpd.gov",
        raw_data={"Keywords": "security, forensic, cloud, api"},
    )
    prof_ctx = ProfessionalContext()
    # Real source in sources has id "src_real_99"
    sources = [
        SourceEvidence(
            source_id="src_real_99",
            source_url="https://ccpd.gov",
            source_type="official_company",
            evidence_quality=0.90,
            facts_supported=["Central City Police corroborated"],
        ),
    ]
    # Name claim references "src_nonexistent_404" which does NOT exist in sources
    claims_invalid_src = [
        LeadClaim(claim_id="c1", field="name", value="Barry Allen", status="verified", source_ids=["src_nonexistent_404"]),
        LeadClaim(claim_id="c2", field="job_title", value="Lead Forensic Scientist", status="verified", source_ids=["src_real_99"]),
        LeadClaim(claim_id="c3", field="company", value="Central City Police", status="verified", source_ids=["src_real_99"]),
    ]

    p_info, breakdown, readiness = scorer.evaluate_lead(
        lead=lead,
        prof_context=prof_ctx,
        sources=sources,
        identity_score=0.95,
        claims=claims_invalid_src,
    )
    assert "identity_not_verified" in readiness.blockers, "Nonexistent source ID must fail identity verification"
    assert readiness.has_name is False
    assert p_info.numeric_priority >= 1
    assert breakdown.verification_confidence <= 0.50


def test_unverified_role_blocks_ready_status_and_priority_0():
    """Regression test for fix.md #2: Unverified role must block P0 and prevent 'ready' status."""
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="test_unverified_role",
        name="Arthur Curry",
        first_name="Arthur",
        last_name="Curry",
        job_title="Director of Marine Infrastructure",
        company="Atlantis Systems",
        industry="Technology",
        professional_email="arthur@atlantis.io",
        raw_data={"Keywords": "ai, cloud, api, security, zero trust, governance"},
    )
    prof_ctx = ProfessionalContext()
    sources = [
        SourceEvidence(
            source_id="src_atl_1",
            source_url="https://atlantis.io",
            source_type="official_company",
            evidence_quality=0.95,
            facts_supported=["Arthur Curry corroborated on official domain", "Company identity corroborated"],
        ),
    ]
    # Name and company verified, but role is unverified
    claims = [
        LeadClaim(claim_id="c1", field="name", value="Arthur Curry", status="verified", source_ids=["src_atl_1"]),
        LeadClaim(claim_id="c2", field="job_title", value="Director of Marine Infrastructure", status="unverified", source_ids=[]),
        LeadClaim(claim_id="c3", field="company", value="Atlantis Systems", status="verified", source_ids=["src_atl_1"]),
        LeadClaim(claim_id="c4", field="professional_email", value="arthur@atlantis.io", status="input_provided", source_ids=["src_atl_1"]),
    ]

    p_info, breakdown, readiness = scorer.evaluate_lead(
        lead=lead,
        prof_context=prof_ctx,
        sources=sources,
        identity_score=0.95,
        claims=claims,
    )
    assert "current_role_not_verified" in readiness.blockers
    assert readiness.has_verified_role is False
    assert readiness.status != "ready"
    assert p_info.numeric_priority >= 1, "Unverified role must block Priority 0"


def test_unverified_company_blocks_ready_status_and_priority_0():
    """Regression test for fix.md #2: Unverified company must block P0 and prevent 'ready' status."""
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="test_unverified_company",
        name="Hal Jordan",
        first_name="Hal",
        last_name="Jordan",
        job_title="VP of Flight Engineering",
        company="Ferris Aircraft",
        industry="Aerospace",
        professional_email="hal@ferrisair.com",
        raw_data={"Keywords": "ai, cloud, api, security, zero trust, aerospace"},
    )
    prof_ctx = ProfessionalContext()
    sources = [
        SourceEvidence(
            source_id="src_bio_1",
            source_url="https://aerospace-bio.org/hal",
            source_type="public_web_bio",
            evidence_quality=0.90,
            facts_supported=["Hal Jordan VP of Flight Engineering"],
        ),
    ]
    # Name and role verified, but company claim is unverified
    claims = [
        LeadClaim(claim_id="c1", field="name", value="Hal Jordan", status="verified", source_ids=["src_bio_1"]),
        LeadClaim(claim_id="c2", field="job_title", value="VP of Flight Engineering", status="verified", source_ids=["src_bio_1"]),
        LeadClaim(claim_id="c3", field="company", value="Ferris Aircraft", status="unverified", source_ids=[]),
        LeadClaim(claim_id="c4", field="professional_email", value="hal@ferrisair.com", status="input_provided", source_ids=["src_bio_1"]),
    ]

    p_info, breakdown, readiness = scorer.evaluate_lead(
        lead=lead,
        prof_context=prof_ctx,
        sources=sources,
        identity_score=0.90,
        claims=claims,
    )
    assert "company_not_verified" in readiness.blockers
    assert readiness.has_company_context is False
    assert readiness.status != "ready"
    assert p_info.numeric_priority >= 1, "Unverified company must block Priority 0"

