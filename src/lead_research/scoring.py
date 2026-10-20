"""Deterministic, reproducible priority scoring model for SealAPI leads."""

import re
from typing import Any, Dict, List, Tuple
from .schemas import LeadInput, PriorityInfo, ProfessionalContext, SourceEvidence


HIGH_FIT_ROLES = [
    r"\bciso\b",
    r"\bchief information security officer\b",
    r"\bchief ai officer\b",
    r"\bhead of ai\b",
    r"\bchief technology officer\b",
    r"\bcto\b",
    r"\bvp of engineering\b",
    r"\bvp engineering\b",
    r"\bhead of engineering\b",
    r"\bhead of data\b",
    r"\bchief product officer\b",
    r"\bcpo\b",
    r"\bhead of security\b",
    r"\bdirector of security\b",
]

MODERATE_FIT_ROLES = [
    r"\bceo\b",
    r"\bfounder\b",
    r"\bco-founder\b",
    r"\bdirector of engineering\b",
    r"\bvp product\b",
    r"\bprincipal engineer\b",
    r"\blead architect\b",
    r"\bsolutions architect\b",
    r"\bai engineer\b",
    r"\bdata science\b",
]

HIGH_FIT_INDUSTRIES = [
    "information technology",
    "computer software",
    "financial services",
    "hospital & health care",
    "health care",
    "fintech",
    "cybersecurity",
    "artificial intelligence",
    "cloud computing",
    "internet",
    "banking",
    "insurance",
]

MODERATE_FIT_INDUSTRIES = [
    "marketing & advertising",
    "management consulting",
    "e-learning",
    "telecommunications",
    "media",
    "venture capital",
    "retail",
]

TECH_SECURITY_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "llm", "genai", "generative ai",
    "agentic", "api", "apis", "security", "hipaa", "soc2", "compliance", "data privacy",
    "zero trust", "cloud", "saas", "infrastructure", "token", "encryption", "gateway"
]


class LeadScorer:
    """Calculates deterministic 0/1/2 priority and provides explainable evidence."""

    def calculate_priority(
        self,
        lead: LeadInput,
        prof_context: ProfessionalContext,
        sources: List[SourceEvidence],
        researched_text: str = ""
    ) -> PriorityInfo:
        role_text = (lead.job_title or "").lower()
        industry_text = (lead.industry or "").lower()
        company_text = (lead.company or "").lower()
        raw_keywords = str(lead.raw_data.get("Keywords", "")).lower()
        combined_text = f"{role_text} {industry_text} {company_text} {raw_keywords} {researched_text.lower()}"

        supporting_evidence: List[str] = []

        # 1. Role Score (0 to 35)
        role_score = 0.0
        role_matched = False
        for pattern in HIGH_FIT_ROLES:
            if re.search(pattern, role_text):
                role_score = 35.0
                role_matched = True
                supporting_evidence.append(f"High-authority security/AI decision maker role: '{lead.job_title}'")
                break

        if not role_matched:
            for pattern in MODERATE_FIT_ROLES:
                if re.search(pattern, role_text):
                    role_score = 25.0
                    role_matched = True
                    supporting_evidence.append(f"Technical leadership role: '{lead.job_title}'")
                    break

        if not role_matched:
            if "engineer" in role_text or "developer" in role_text or "architect" in role_text:
                role_score = 15.0
                supporting_evidence.append(f"Technical role: '{lead.job_title}'")
            else:
                role_score = 5.0
                supporting_evidence.append(f"Non-technical or unverified role: '{lead.job_title}'")

        # 2. Industry / Company Fit Score (0 to 30)
        industry_score = 5.0
        for ind in HIGH_FIT_INDUSTRIES:
            if ind in industry_text:
                industry_score = 30.0
                supporting_evidence.append(f"Target enterprise vertical matching SealAPI: '{ind}'")
                break

        if industry_score < 30.0:
            for ind in MODERATE_FIT_INDUSTRIES:
                if ind in industry_text:
                    industry_score = 18.0
                    supporting_evidence.append(f"Adjacent vertical: '{ind}'")
                    break

        # 3. Technical / Security / AI Need Evidence (0 to 25)
        tech_score = 0.0
        matched_keywords = [kw for kw in TECH_SECURITY_KEYWORDS if kw in combined_text]
        if len(matched_keywords) >= 4:
            tech_score = 25.0
            supporting_evidence.append(
                f"Strong verified AI/API security need (matched signals: {', '.join(matched_keywords[:6])})"
            )
        elif len(matched_keywords) >= 2:
            tech_score = 15.0
            supporting_evidence.append(
                f"Moderate AI/API infrastructure signals: {', '.join(matched_keywords[:4])}"
            )
        elif len(matched_keywords) == 1:
            tech_score = 8.0
            supporting_evidence.append(f"Limited technical keywords: {matched_keywords[0]}")
        else:
            tech_score = 2.0
            supporting_evidence.append("Minimal technical/security keywords detected")

        # 4. Data Completeness & Verification Confidence (0 to 10)
        verification_score = 0.0
        if lead.professional_email and "@" in lead.professional_email:
            verification_score += 5.0
            supporting_evidence.append(f"Verified business email domain: {lead.professional_email}")
        if lead.company_website:
            verification_score += 5.0

        total_score = round(role_score + industry_score + tech_score + verification_score, 1)

        # Confidence calculation
        sources_count = len(sources)
        confidence = min(1.0, 0.4 + (sources_count * 0.15) + (0.2 if lead.professional_email else 0.0))
        confidence = round(confidence, 2)

        # Classification Rule: Exactly 0, 1, or 2
        if total_score >= 70.0 and role_score >= 25.0 and industry_score >= 18.0 and tech_score >= 15.0:
            numeric_priority = 0
            reason = (
                f"Priority 0 (Highest Fit): {lead.job_title or 'Executive'} at {lead.company or 'Target Account'} "
                f"matches core decision-maker criteria in a regulated/tech-driven industry with active AI/API needs."
            )
        elif total_score >= 45.0:
            numeric_priority = 1
            reason = (
                f"Priority 1 (Medium Fit): {lead.job_title or 'Contact'} at {lead.company or 'Company'} "
                f"is in a relevant role or vertical, but requires further qualification of immediate security/AI deployment urgency."
            )
        else:
            numeric_priority = 2
            reason = (
                f"Priority 2 (Lowest Fit): Limited evidence of immediate relevance to SealAPI's secure AI and API governance platform."
            )

        return PriorityInfo(
            numeric_priority=numeric_priority,
            reason=reason,
            score=total_score,
            confidence=confidence,
            supporting_evidence=supporting_evidence
        )
