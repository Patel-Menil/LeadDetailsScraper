"""Data schemas and Pydantic models for SealAPI Lead Research Pipeline."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SourceEvidence(BaseModel):
    """Source provenance and verifiable facts."""
    source_url: str
    source_type: str = Field(
        ...,
        description="Type of source: company_website, leadership_page, profile_page, tech_blog, input_data"
    )
    retrieval_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    facts_supported: List[str] = Field(default_factory=list)


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
    research_status: str = Field(
        default="pending",
        description="completed, partial, failed, skipped"
    )
    last_research_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    sources_examined: int = 0
    errors_and_limitations: List[str] = Field(default_factory=list)


class LeadProfile(BaseModel):
    """Versioned research profile for an individual lead."""
    schema_version: str = "1.0.0"
    lead_id: str
    identity: Dict[str, Any]
    professional_context: ProfessionalContext = Field(default_factory=ProfessionalContext)
    priority: PriorityInfo
    sources: List[SourceEvidence] = Field(default_factory=list)
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
    priority_counts: Dict[str, int] = Field(default_factory=lambda: {"0": 0, "1": 0, "2": 0})
    current_lead_name: Optional[str] = None
    recent_logs: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
