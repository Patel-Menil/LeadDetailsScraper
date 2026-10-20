"""Tests for Identity Resolution and Marketplace Rejection."""

import pytest
from src.lead_research.identity import (
    build_targeted_queries,
    companies_match,
    extract_domain,
    identity_match_score,
    is_abbreviated_name,
    is_marketplace_false_positive,
    names_compatible,
    titles_compatible,
)
from src.lead_research.schemas import LeadInput


def test_extract_domain():
    assert extract_domain("https://www.example.com/about") == "example.com"
    assert extract_domain("sealapi.com:443") == "sealapi.com"
    assert extract_domain("http://sub.domain.co.uk/path") == "sub.domain.co.uk"
    assert extract_domain("") == ""


def test_is_abbreviated_name():
    assert is_abbreviated_name("Andrew R") is True
    assert is_abbreviated_name("Jon B.") is True
    assert is_abbreviated_name("Matt F") is True
    assert is_abbreviated_name("Andrew Roberts") is False
    assert is_abbreviated_name("Alice") is False


def test_names_compatible():
    # Exact match
    compat, score = names_compatible("John Doe", "John Doe")
    assert compat is True and score > 0.3

    # Initial compatibility
    compat, score = names_compatible("Andrew R", "Andrew Roberts")
    assert compat is True and score > 0.15

    compat, score = names_compatible("Jon B.", "Jon B")
    assert compat is True and score > 0.15

    # Mismatch
    compat, score = names_compatible("John Doe", "Jane Doe")
    assert compat is False and score == 0.0

    compat, score = names_compatible("Alice Smith", "Bob Jones")
    assert compat is False and score == 0.0


def test_companies_match():
    # Exact match
    compat, score = companies_match("Acme Corp", "Acme Corp is a provider...")
    assert compat is True and score >= 0.3

    # Cleaned name match
    compat, score = companies_match("SealAPI Technologies LLC", "Welcome to SealAPI developer docs")
    assert compat is True and score >= 0.3

    # Domain match
    compat, score = companies_match("Stripe", "Stripe payment platform", candidate_url="https://stripe.com/docs", lead_website="https://stripe.com")
    assert compat is True and score >= 0.3

    # Complete mismatch
    compat, score = companies_match("Google", "Microsoft Azure Cloud Services")
    assert compat is False and score == 0.0


def test_titles_compatible():
    # Same or compatible titles
    compat, score = titles_compatible("CTO", "CTO and Founder at Company")
    assert compat is True and score > 0.0

    compat, score = titles_compatible("VP of Engineering", "VP Engineering")
    assert compat is True and score > 0.0

    # Incompatible roles
    compat, score = titles_compatible("Chief Technology Officer", "Freelance copywriter and junior developer")
    assert compat is False and score < 0.0


def test_is_marketplace_false_positive():
    lead = LeadInput(
        lead_id="lead_001",
        name="Andrew R",
        company="Upwork",
        job_title="VP of Engineering",
        company_website="https://upwork.com",
    )
    # Marketplace profile for random freelancer on Upwork should be flagged
    marketplace_cand = {
        "title": "Andrew Randolph - Freelance Full-Stack Developer - Upwork",
        "snippet": "Experienced freelancer building web apps.",
        "url": "https://www.upwork.com/freelancers/~01abcdef",
    }
    assert is_marketplace_false_positive(lead, marketplace_cand) is True

    # Real executive bio / LinkedIn should NOT be flagged
    real_cand = {
        "title": "Andrew Rabinovich - Head of AI - Upwork | LinkedIn",
        "snippet": "Leading artificial intelligence and platform engineering at Upwork.",
        "url": "https://www.linkedin.com/in/andrew-rabinovich",
    }
    assert is_marketplace_false_positive(lead, real_cand) is False


def test_identity_match_score_high_for_matching_executive():
    lead = LeadInput(
        lead_id="lead_002",
        name="Elena Rostova",
        company="CyberShield AI",
        job_title="Head of Platform Architecture",
        company_website="https://cybershield.ai",
    )
    matching_cand = {
        "title": "Elena Rostova - Head of Platform Architecture - CyberShield AI",
        "snippet": "Elena Rostova leads platform engineering and infrastructure at CyberShield AI.",
        "url": "https://cybershield.ai/team/elena-rostova",
    }
    score = identity_match_score(lead, matching_cand)
    assert score >= 0.80, f"Expected high identity match score, got {score}"


def test_identity_match_score_low_for_unrelated_person():
    lead = LeadInput(
        lead_id="lead_003",
        name="Elena Rostova",
        company="CyberShield AI",
        job_title="Head of Platform Architecture",
        company_website="https://cybershield.ai",
    )
    unrelated_cand = {
        "title": "Elena Rostova - Freelance Graphic Designer",
        "snippet": "Experienced UI/UX designer and illustrator based in Prague.",
        "url": "https://dribbble.com/elena-rostova",
    }
    score = identity_match_score(lead, unrelated_cand)
    assert score <= 0.40, f"Expected low identity match score for unrelated person, got {score}"


def test_build_targeted_queries():
    lead = LeadInput(
        lead_id="lead_123",
        name="Marcus Vance",
        first_name="Marcus",
        last_name="Vance",
        job_title="VP of Infrastructure",
        company="CloudMatrix",
        company_website="https://cloudmatrix.io",
    )
    queries = build_targeted_queries(lead)
    assert len(queries) >= 3
    # Check that name and company query is present
    assert any('"Marcus Vance"' in q and '"CloudMatrix"' in q for q in queries)
    # Check domain query is present
    assert any("site:cloudmatrix.io" in q for q in queries)
    # Check industry / topic query is present
    assert any("API" in q or "AI" in q or "security" in q for q in queries)
