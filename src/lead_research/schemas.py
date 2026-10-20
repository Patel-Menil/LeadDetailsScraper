"""Data schemas and Pydantic models for SealAPI Lead Research Pipeline (V2 Architecture).

Provides versioned models separating:
- Input snapshot (immutable original data)
- Observed source evidence (with provenance and quality)
- Grounded claims (with verification status and source references)
- Inferences & hypotheses (clearly distinguished from verified facts)
- Contact readiness (actionable outreach qualification)
- Lead fit & scoring breakdown (decoupled fit vs confidence)
- Evidence-based icebreakers and outreach drafts
- Backwards compatibility with V1 fields for existing API & UI
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


VerificationStatus = Literal[
    "input_provided",
    "verified",
    "partially_verified",
    "unverified",
    "conflicting",
    "needs_review",
]


class SourceEvidence(BaseModel):
    """Source provenance and verifiable facts."""
    source_id: str = Field(default_factory=lambda: f"src_{datetime.now(timezone.utc).strftime('%H%M%S%f')[:10]}")
    source_url: str
    source_type: str = Field(
        ...,
        description="Type: official_company, company_website, public_professional_profile, public_web_bio, tech_blog, news, job_posting, user_input, other_public",
    )
    title: Optional[str] = None
    publisher: Optional[str] = None
    retrieval_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    published_at: Optional[str] = None
    relevant_excerpt: Optional[str] = None
    evidence_quality: float = Field(default=0.5, ge=0.0, le=1.0)
    supports_claim_ids: List[str] = Field(default_factory=list)
    # Backward compatibility with v1
    facts_supported: List[str] = Field(default_factory=list)


class LeadClaim(BaseModel):
    """Specific claim verified against supporting source evidence."""
    claim_id: str
    field: str
    value: Optional[str] = None
    status: VerificationStatus = "unverified"
    source_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    last_verified_at: Optional[str] = None
    review_reason: Optional[str] = None


class ContactReadiness(BaseModel):
    """Deterministic readiness assessment for outreach."""
    status: Literal["ready", "ready_with_caveat", "needs_research", "not_ready"] = "needs_research"
    has_name: bool = False
    has_verified_role: bool = False
    has_company_context: bool = False
    has_usable_contact_channel: bool = False
    has_evidence_based_icebreaker: bool = False
    blockers: List[str] = Field(default_factory=list)


class PublicSignal(BaseModel):
    """Verifiable public signal related to the person or company."""
    signal_id: str
    signal_type: str = "general_activity"  # product_launch, technical_work, public_interview, hiring_signal, company_positioning
    headline: str
    summary: str
    source_ids: List[str] = Field(default_factory=list)
    published_date: Optional[str] = None
    relevance_to_lead: str = ""
    verification_status: VerificationStatus = "unverified"
    confidence: float = 0.5


class Icebreaker(BaseModel):
    """Evidence-grounded personalized opener."""
    text: Optional[str] = None
    icebreaker_type: Optional[str] = None  # technical_work, company_launch, public_interview, product_integration, hiring_signal, company_positioning, general_question
    source_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    why_it_matters: Optional[str] = None
    potential_pain_point: Optional[str] = None
    conversation_question: Optional[str] = None
    personalization_status: Literal["ready", "needs_review", "generic_fallback"] = "needs_review"
    outreach_draft: Optional[Dict[str, str]] = None


class ScoringBreakdown(BaseModel):
    """Decoupled scoring distinguishing Lead Fit from Verification Confidence."""
    lead_fit_score: float = Field(default=0.0, ge=0.0, le=100.0)
    role_fit_score: float = 0.0
    industry_fit_score: float = 0.0
    technical_need_score: float = 0.0
    verification_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    readiness_status: str = "needs_research"
    explanations: List[str] = Field(default_factory=list)


class SealAPIRelevance(BaseModel):
    """Relevance analysis specific to SealAPI value propositions."""
    summary: str = ""
    relevant_use_cases: List[str] = Field(default_factory=list)
    evidence_points: List[str] = Field(default_factory=list)


class ProfessionalContext(BaseModel):
    """Researched professional responsibilities, focus areas, and SealAPI alignment."""
    responsibilities: List[str] = Field(default_factory=list)
    technical_interests: List[str] = Field(default_factory=list)
    public_projects: List[str] = Field(default_factory=list)
    recent_developments: List[str] = Field(default_factory=list)
    sealapi_relevance: SealAPIRelevance = Field(default_factory=SealAPIRelevance)


class PriorityInfo(BaseModel):
    """Deterministic numeric priority score and reasoning (0, 1, or 2)."""
    numeric_priority: int = Field(..., ge=0, le=2, description="0=Highest, 1=Medium, 2=Lowest")
    reason: str
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    supporting_evidence: List[str] = Field(default_factory=list)


class ColdEmailContext(BaseModel):
    """Actionable, fact-traceable personalization for outreach."""
    verified_personalization_points: List[str] = Field(default_factory=list)
    suggested_value_propositions: List[str] = Field(default_factory=list)
    suggested_call_to_action: str = ""
    claims_to_avoid: List[str] = Field(default_factory=list)
    missing_verification_points: List[str] = Field(default_factory=list)


class ResearchMetadata(BaseModel):
    """Research status, execution timestamps, and operational limitations."""
    schema_version: str = "2.0.0"
    batch_id: str = ""
    pipeline_version: str = "2.0.0"
    researched_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    execution_status: Literal["completed", "partial", "failed"] = "partial"
    verification_status: VerificationStatus = "unverified"
    source_count: int = 0
    review_required: bool = False
    cache_fingerprint: Optional[str] = None
    errors_and_limitations: List[str] = Field(default_factory=list)
    
    # Backward compatibility with v1
    research_status: str = Field(default="pending")
    last_research_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sources_examined: int = 0


class LeadProfile(BaseModel):
    """Versioned research profile for an individual lead (V2 with V1 backwards compatibility)."""
    schema_version: str = "2.0.0"
    lead_id: str
    input_snapshot: Dict[str, Any] = Field(default_factory=dict)
    identity: Dict[str, Any]
    contact: Dict[str, Any] = Field(default_factory=dict)
    company: Dict[str, Any] = Field(default_factory=dict)
    professional_context: ProfessionalContext = Field(default_factory=ProfessionalContext)
    priority: PriorityInfo
    sources: List[SourceEvidence] = Field(default_factory=list)
    claims: List[LeadClaim] = Field(default_factory=list)
    public_signals: List[PublicSignal] = Field(default_factory=list)
    icebreaker: Icebreaker = Field(default_factory=Icebreaker)
    scoring: ScoringBreakdown = Field(default_factory=ScoringBreakdown)
    contact_readiness: ContactReadiness = Field(default_factory=ContactReadiness)
    cold_email_context: ColdEmailContext = Field(default_factory=ColdEmailContext)
    research_metadata: ResearchMetadata = Field(default_factory=ResearchMetadata)


class LeadInput(BaseModel):
    """Parsed and validated input lead."""
    lead_id: str
    name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    industry: Optional[str] = None
    linkedin_url: Optional[str] = None
    company_website: Optional[str] = None
    professional_email: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    raw_data: Dict[str, Any] = Field(default_factory=dict)


class ImportSummary(BaseModel):
    """Summary of CSV/XLSX import and validation."""
    total_input_rows: int = 0
    valid_leads: int = 0
    duplicate_records: int = 0
    malformed_rows: int = 0
    validation_errors: List[Dict[str, Any]] = Field(default_factory=list)
    column_mapping: Dict[str, str] = Field(default_factory=dict)
    sample_preview: List[Dict[str, Any]] = Field(default_factory=list)


class BatchProgress(BaseModel):
    """Live status and statistics for a research batch."""
    batch_id: str
    filename: str
    status: str = "pending"  # pending, processing, completed, failed, cancelled
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    total_leads: int = 0
    processed_leads: int = 0
    completed_count: int = 0
    partial_count: int = 0
    failed_count: int = 0
    outreach_ready_count: int = 0
    needs_review_count: int = 0
    priority_counts: Dict[str, int] = Field(default_factory=lambda: {"0": 0, "1": 0, "2": 0})
    current_lead_name: Optional[str] = None
    recent_logs: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


def migrate_profile_v1_to_v2(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure a legacy V1 profile or incomplete dictionary conforms to V2 structure.
    Preserves existing fields while initializing missing V2 fields cleanly.
    """
    migrated = dict(data)
    migrated["schema_version"] = "2.0.0"

    # Ensure research_metadata is consistent
    meta = migrated.get("research_metadata") or {}
    meta["schema_version"] = "2.0.0"
    if "pipeline_version" not in meta:
        meta["pipeline_version"] = "2.0.0"
    if "verification_status" not in meta:
        meta["verification_status"] = "partially_verified" if migrated.get("sources") else "unverified"
    migrated["research_metadata"] = meta

    # Ensure claims list exists
    if "claims" not in migrated or not migrated["claims"]:
        migrated["claims"] = []

    # Ensure contact_readiness exists
    if "contact_readiness" not in migrated or not migrated["contact_readiness"]:
        has_channel = bool(
            migrated.get("contact", {}).get("email") or
            migrated.get("contact", {}).get("linkedin_url") or
            migrated.get("identity", {}).get("professional_email") or
            migrated.get("identity", {}).get("linkedin_url")
        )
        migrated["contact_readiness"] = {
            "status": "ready_with_caveat" if has_channel else "needs_research",
            "has_name": bool(migrated.get("identity", {}).get("name")),
            "has_verified_role": False,
            "has_company_context": bool(migrated.get("company", {}).get("name")),
            "has_usable_contact_channel": has_channel,
            "has_evidence_based_icebreaker": bool(migrated.get("icebreaker", {}).get("text")),
            "blockers": [] if has_channel else ["no_usable_contact_channel"],
        }

    return migrated
