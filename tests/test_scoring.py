"""Tests for deterministic priority scoring model."""

import pytest
from src.lead_research.schemas import LeadInput, ProfessionalContext, SourceEvidence
from src.lead_research.scoring import LeadScorer


def test_priority_0_highest_fit():
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="lead_123",
        name="Sarah Connor",
        job_title="Chief Information Security Officer & Head of AI",
        company="SecureHealth Technologies",
        industry="hospital & health care",
        professional_email="sarah@securehealth.com",
        company_website="https://securehealth.com",
        raw_data={"Keywords": "ai, machine learning, hipaa, zero trust, api security"}
    )
    prof = ProfessionalContext()
    sources = [
        SourceEvidence(
            source_url="https://securehealth.com",
            source_type="company_website",
            facts_supported=["Healthcare AI platform with HIPAA compliance"]
        )
    ]

    p_info = scorer.calculate_priority(lead, prof, sources, researched_text="llm security api tokens")
    assert p_info.numeric_priority == 0
    assert p_info.score >= 70.0
    assert "Priority 0 (Highest Fit)" in p_info.reason
    assert len(p_info.supporting_evidence) >= 3


def test_priority_1_medium_fit():
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="lead_456",
        name="Mark Miller",
        job_title="Director of Operations",
        company="RetailPulse",
        industry="marketing & advertising",
        professional_email="mark@retailpulse.com",
        raw_data={"Keywords": "ecommerce, advertising"}
    )
    prof = ProfessionalContext()
    sources = []

    p_info = scorer.calculate_priority(lead, prof, sources, researched_text="")
    # Non-technical role in moderate vertical without AI signals
    # Role = 5, Industry = 18, Tech = 2, Verification = 5 -> Total 30 -> Priority 2
    assert p_info.numeric_priority in (1, 2)


def test_priority_deterministic_repeatability():
    scorer = LeadScorer()
    lead = LeadInput(
        lead_id="lead_789",
        name="Alex Chen",
        job_title="Chief Technology Officer",
        company="FintechSecure",
        industry="financial services",
        professional_email="alex@fintechsecure.com",
        raw_data={"Keywords": "banking, api, microservices, encryption"}
    )
    prof = ProfessionalContext()

    res1 = scorer.calculate_priority(lead, prof, [], researched_text="")
    res2 = scorer.calculate_priority(lead, prof, [], researched_text="")

    assert res1.numeric_priority == res2.numeric_priority
    assert res1.score == res2.score
    assert res1.reason == res2.reason
