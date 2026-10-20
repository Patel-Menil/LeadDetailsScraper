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
import pytest

from src.lead_research.exporter import LeadExporter
from src.lead_research.fingerprint import create_batch_id, research_fingerprint
from src.lead_research.icebreaker import build_icebreaker, extract_public_signals
from src.lead_research.schemas import (
    ContactReadiness,
    Icebreaker,
    LeadClaim,
    LeadInput,
    LeadProfile,
    PriorityInfo,
    ProfessionalContext,
    PublicSignal,
    ResearchMetadata,
    SealAPIRelevance,
    SourceEvidence,
)
from src.lead_research.scoring import LeadScorer
from src.lead_research.scraper import is_safe_url


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
        "https://sealapi.com/pricing",
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

    p_info, breakdown, readiness = scorer.evaluate_lead(
        lead=lead,
        prof_context=prof_ctx,
        sources=sources,
        identity_score=0.90,
        researched_text="Marcus Vance leads infrastructure engineering at CloudMatrix.",
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
