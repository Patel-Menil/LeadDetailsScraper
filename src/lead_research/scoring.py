"""Deterministic, reproducible priority scoring model for SealAPI leads.

Decouples:
1. Lead Fit Score (0-100): Measures potential fit for SealAPI's value propositions.
2. Verification Confidence (0.0-1.0): Measures reliability of evidence and identity.
3. Contact Readiness: Assesses whether the lead is outreach-ready or requires review.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from .schemas import (
    ContactReadiness,
    Icebreaker,
    LeadClaim,
    LeadInput,
    PriorityInfo,
    ProfessionalContext,
    ScoringBreakdown,
    SourceEvidence,
)


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
    r"\bvp of infrastructure\b",
    r"\bvp infrastructure\b",
    r"\bhead of infrastructure\b",
    r"\bdirector of infrastructure\b",
    r"\bhead of platform\b",
    r"\bvp of platform\b",
    r"\bvp platform\b",
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
    """Calculates decoupled Lead Fit, Verification Confidence, and Contact Readiness."""

    def evaluate_lead(
        self,
        lead: LeadInput,
        prof_context: ProfessionalContext,
        sources: List[SourceEvidence],
        identity_score: float = 0.8,
        icebreaker: Optional[Icebreaker] = None,
        researched_text: str = "",
        claims: Optional[List[LeadClaim]] = None,
    ) -> Tuple[PriorityInfo, ScoringBreakdown, ContactReadiness]:
        """
        Produce deterministic Lead Fit, Verification Confidence, and Contact Readiness evaluations.
        """
        role_text = (lead.job_title or "").lower()
        industry_text = (lead.industry or "").lower()
        company_text = (lead.company or "").lower()
        raw_keywords = str(lead.raw_data.get("Keywords", "")).lower()
        combined_text = f"{role_text} {industry_text} {company_text} {raw_keywords} {researched_text.lower()}"

        supporting_evidence: List[str] = []

        # 1. Role Fit Score (0 to 35)
        role_score = 5.0
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
            if any(k in role_text for k in ["engineer", "developer", "architect"]):
                role_score = 15.0
                supporting_evidence.append(f"Technical role: '{lead.job_title}'")
            else:
                role_score = 5.0
                supporting_evidence.append(f"Non-technical or unverified role: '{lead.job_title}'")

        # 2. Industry / Vertical Fit Score (0 to 30)
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

        # 3. Technical / AI / API Need Evidence (0 to 25)
        tech_score = 2.0
        matched_keywords = [kw for kw in TECH_SECURITY_KEYWORDS if kw in combined_text]
        if len(matched_keywords) >= 4:
            tech_score = 25.0
            supporting_evidence.append(
                f"Multiple AI/API technical signals detected in profile keywords (intent unverified: {', '.join(matched_keywords[:6])})"
            )
        elif len(matched_keywords) >= 2:
            tech_score = 15.0
            supporting_evidence.append(
                f"Moderate AI/API infrastructure signals in profile context: {', '.join(matched_keywords[:4])} (buying intent unverified)"
            )
        elif len(matched_keywords) == 1:
            tech_score = 8.0
            supporting_evidence.append(f"Limited technical keywords in profile: {matched_keywords[0]} (buying intent unknown)")
        else:
            tech_score = 2.0
            supporting_evidence.append("Minimal technical/security keywords detected; technical buying intent unknown")

        # 4. Organization Fit (0 to 10)
        org_fit = 0.0
        if lead.company_website:
            org_fit += 5.0
        if lead.company:
            org_fit += 5.0

        lead_fit_score = round(role_score + industry_score + tech_score + org_fit, 1)

        # 5. Verification Confidence (0.0 to 1.0)
        # Based on identity match quality, official domain verification, and independent corroboration
        has_official_source = any(s.source_type in ("company_website", "official_company") for s in sources)
        has_public_bio = any(s.source_type in ("public_professional_profile", "public_web_bio") for s in sources)

        base_conf = max(0.2, identity_score * 0.6)
        if has_official_source:
            base_conf += 0.25
        if has_public_bio:
            base_conf += 0.15

        verification_conf = min(1.0, round(base_conf, 2))

        # 6. Contact Readiness Classification
        blockers: List[str] = []
        has_name = bool(lead.name and len(lead.name.strip()) > 1)

        # Strict identity verification check:
        # A lead must not pass the identity-verification gate unless the person's name claim has
        # status 'verified' and is supported by eligible, nonempty evidence source IDs that actually exist in sources.
        # Claims with statuses such as 'input_provided', 'partially_verified', 'needs_review', or 'unverified'
        # must not satisfy the verified-identity requirement. A high identity_score must not override missing evidence.
        has_verified_identity = False
        valid_sources = {
            s.source_id: s for s in (sources or [])
            if s.source_id and s.source_type != "user_input" and s.evidence_quality > 0.0
        }

        def _has_verified_claim_with_valid_source(claim: Optional[LeadClaim]) -> bool:
            if not claim or claim.status != "verified" or not claim.source_ids:
                return False
            # Referenced source IDs must actually exist in the observed source evidence
            return any(sid in valid_sources for sid in claim.source_ids)

        if claims is not None:
            name_claim = next((c for c in claims if c.field == "name"), None)
            if _has_verified_claim_with_valid_source(name_claim):
                has_verified_identity = True
            else:
                blockers.append("identity_not_verified")
        else:
            # No claims provided (e.g. standalone calculate_priority): identity cannot be verified
            # A high identity_score and supplied name alone must never establish verified identity
            blockers.append("identity_not_verified")

        if identity_score < 0.60 and "identity_not_verified" not in blockers:
            blockers.append("identity_not_verified")

        # Cap verification confidence if identity is unverified
        if not has_verified_identity:
            verification_conf = min(verification_conf, 0.50)

        # has_verified_role must be derived strictly from verified job_title claim with existing source evidence
        # A missing claims list must never trigger a weaker verification fallback
        has_verified_role = False
        if claims is not None:
            for clm in claims:
                if clm.field == "job_title" and _has_verified_claim_with_valid_source(clm):
                    has_verified_role = True
                    break

        # has_company_ctx requires a verified company claim or corroborated official source
        # Mere presence of company name and URL is not verified company context
        has_company_ctx = False
        if claims is not None:
            has_company_ctx = any(
                clm.field == "company" and _has_verified_claim_with_valid_source(clm)
                for clm in claims
            )
        else:
            has_company_ctx = any(
                s.source_type == "official_company" and any("company identity" in f.lower() for f in s.facts_supported)
                for s in (sources or [])
            )

        # Contact channel validation: require syntactically valid email format
        email_val = (lead.professional_email or "").strip()
        email_syntax_valid = bool(re.match(r"^[^@\s]+@[^@\s]+\.[a-zA-Z0-9]{2,}$", email_val))
        has_usable_channel = email_syntax_valid

        has_evidence_icebreaker = bool(icebreaker and icebreaker.personalization_status == "ready")

        # Classify email channel deliverability vs syntax unprobed
        email_claim = next((c for c in (claims or []) if c.field == "professional_email"), None)
        is_email_verified = bool(email_claim and email_claim.status == "verified")
        is_email_unprobed = bool(email_syntax_valid and not is_email_verified)

        if not has_verified_role:
            blockers.append("current_role_not_verified")
        if not has_company_ctx:
            blockers.append("company_not_verified")
        if not has_usable_channel:
            blockers.append("no_usable_contact_channel")
        if icebreaker and icebreaker.personalization_status == "needs_review":
            blockers.append("icebreaker_needs_review")
        if is_email_unprobed:
            blockers.append("email_syntax_valid_unprobed")

        # Deduplicate blockers preserving order
        blockers = list(dict.fromkeys(blockers))

        # Readiness Policy Gates:
        # A lead is ready only when identity, verified role, company, usable channel, and grounded icebreaker are satisfied
        if not has_usable_channel or identity_score < 0.40 or not has_verified_identity:
            readiness_status = "not_ready" if (not has_usable_channel or identity_score < 0.40) else "needs_research"
        elif "current_role_not_verified" in blockers or "identity_not_verified" in blockers or "company_not_verified" in blockers:
            readiness_status = "needs_research"
        elif "icebreaker_needs_review" in blockers or is_email_unprobed or not has_evidence_icebreaker:
            # Core identity, role, and company are verified with usable contact channel, but caveats remain (unprobed email, icebreaker review)
            readiness_status = "ready_with_caveat"
        else:
            readiness_status = "ready"

        readiness = ContactReadiness(
            status=readiness_status,
            has_name=has_name and has_verified_identity,
            has_verified_role=has_verified_role,
            has_company_context=has_company_ctx,
            has_usable_contact_channel=has_usable_channel,
            has_evidence_based_icebreaker=has_evidence_icebreaker,
            blockers=blockers,
        )

        scoring_breakdown = ScoringBreakdown(
            lead_fit_score=lead_fit_score,
            role_fit_score=role_score,
            industry_fit_score=industry_score,
            technical_need_score=tech_score,
            verification_confidence=verification_conf,
            readiness_status=readiness_status,
            explanations=supporting_evidence,
        )

        # 7. Deterministic Numeric Priority (0, 1, 2)
        # Priority 0: Decision maker in regulated/tech vertical with real technical need AND verified identity
        if (
            lead_fit_score >= 70.0
            and role_score >= 25.0
            and industry_score >= 18.0
            and tech_score >= 15.0
            and has_verified_identity
            and "identity_not_verified" not in blockers
        ):
            numeric_priority = 0
            reason = (
                f"Priority 0 (Highest Fit): {lead.job_title or 'Executive'} at {lead.company or 'Target Account'} "
                f"matches core decision-maker criteria in a target vertical with active AI/API needs and verified identity."
            )
        elif lead_fit_score >= 45.0:
            numeric_priority = 1
            reason = (
                f"Priority 1 (Medium Fit): {lead.job_title or 'Contact'} at {lead.company or 'Company'} "
                f"is in a relevant role or vertical, but requires further qualification of immediate security/AI deployment urgency or verified identity."
            )
        else:
            numeric_priority = 2
            reason = (
                f"Priority 2 (Lowest Fit): Limited evidence of immediate relevance to SealAPI's secure AI and API governance platform."
            )

        priority_info = PriorityInfo(
            numeric_priority=numeric_priority,
            reason=reason,
            score=lead_fit_score,
            confidence=verification_conf,
            supporting_evidence=supporting_evidence,
        )

        return priority_info, scoring_breakdown, readiness

    def calculate_priority(
        self,
        lead: LeadInput,
        prof_context: ProfessionalContext,
        sources: List[SourceEvidence],
        researched_text: str = "",
    ) -> PriorityInfo:
        """Backward-compatible entry point returning PriorityInfo."""
        p_info, _, _ = self.evaluate_lead(
            lead=lead,
            prof_context=prof_context,
            sources=sources,
            identity_score=0.8,
            researched_text=researched_text,
        )
        return p_info
