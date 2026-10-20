export interface DashboardStats {
  total_leads: number;
  completed_count: number;
  review_required_count: number;
  failed_count: number;
  priority_0_count: number;
  priority_1_count: number;
  priority_2_count: number;
  total_batches: number;
  recent_batches: BatchSummary[];
}

export interface BatchSummary {
  batch_id: string;
  status: string;
  total_leads: number;
  completed_count: number;
  partial_count: number;
  failed_count: number;
  outreach_ready_count?: number;
  needs_review_count?: number;
  priority_counts: { [key: string]: number };
  created_at: string;
  updated_at?: string;
  input_filename?: string;
  csv_exists?: boolean;
  outreach_ready_exists?: boolean;
  needs_review_exists?: boolean;
  errors_exists?: boolean;
  profiles_count?: number;
}

export interface BatchProgress {
  batch_id: string;
  filename: string;
  status: "pending" | "processing" | "completed" | "failed" | "cancelled";
  created_at: string;
  updated_at: string;
  total_leads: number;
  processed_leads: number;
  completed_count: number;
  partial_count: number;
  failed_count: number;
  outreach_ready_count?: number;
  needs_review_count?: number;
  priority_counts: { [key: string]: number };
  current_lead_name?: string;
  recent_logs: string[];
  errors: string[];
}

export interface UploadInspection {
  batch_id: string;
  filename: string;
  size_bytes: number;
  headers: string[];
  detected_mapping: { [key: string]: string };
  preview_rows: Record<string, string>[];
  total_rows: number;
  valid_leads_count: number;
  duplicate_count: number;
  malformed_count: number;
  validation_errors: Array<{
    row_index?: number;
    error?: string;
    lead_id?: string;
    type?: string;
  }>;
}

export interface PrioritizedLead {
  lead_id: string;
  name: string;
  job_title: string;
  company: string;
  industry: string;
  linkedin_url?: string;
  company_website?: string;
  professional_email?: string;
  priority: number | string;
  priority_reason: string;
  relevance_evidence: string;
  profile_json_path: string;
  research_status: string;
  last_researched_at: string;
  contact_readiness?: string;
  icebreaker_text?: string;
  icebreaker_type?: string;
  icebreaker_status?: string;
  verification_confidence?: number;
  [key: string]: any;
}

export interface SourceEvidence {
  source_id?: string;
  source_url: string;
  source_type: string;
  title?: string;
  retrieval_timestamp: string;
  evidence_quality?: number;
  relevant_excerpt?: string;
  facts_supported: string[];
}

export interface LeadClaim {
  claim_id: string;
  field: string;
  value?: string | null;
  status: "verified" | "partially_verified" | "unverified" | "conflicting" | "needs_review";
  source_ids: string[];
  confidence: number;
  last_verified_at?: string | null;
  review_reason?: string | null;
}

export interface ContactReadiness {
  status: "ready" | "ready_with_caveat" | "needs_research" | "not_ready";
  has_name: bool_or_boolean;
  has_verified_role: bool_or_boolean;
  has_company_context: bool_or_boolean;
  has_usable_contact_channel: bool_or_boolean;
  has_evidence_based_icebreaker: bool_or_boolean;
  blockers: string[];
}
type bool_or_boolean = boolean;

export interface Icebreaker {
  text?: string | null;
  icebreaker_type?: string | null;
  source_ids: string[];
  confidence: number;
  why_it_matters?: string | null;
  potential_pain_point?: string | null;
  conversation_question?: string | null;
  personalization_status: "ready" | "needs_review" | "generic_fallback";
  outreach_draft?: {
    subject?: string;
    greeting?: string;
    opener?: string;
    sealapi_connection?: string;
    low_pressure_ask?: string;
    full_body?: string;
  } | null;
}

export interface ScoringBreakdown {
  lead_fit_score: number;
  role_fit_score?: number;
  industry_fit_score?: number;
  technical_need_score?: number;
  verification_confidence: number;
  readiness_status: string;
  explanations: string[];
}

export interface SealAPIRelevance {
  summary: string;
  relevant_use_cases: string[];
  evidence_points: string[];
}

export interface ProfessionalContext {
  responsibilities: string[];
  technical_interests: string[];
  public_projects: string[];
  recent_developments: string[];
  sealapi_relevance: SealAPIRelevance;
}

export interface PriorityInfo {
  numeric_priority: number;
  reason: string;
  score: number;
  confidence: number;
  supporting_evidence: string[];
}

export interface ColdEmailContext {
  verified_personalization_points: string[];
  suggested_value_propositions: string[];
  suggested_call_to_action: string;
  claims_to_avoid: string[];
  missing_verification_points: string[];
}

export interface ResearchMetadata {
  schema_version?: string;
  batch_id?: string;
  pipeline_version?: string;
  research_status: string;
  verification_status?: string;
  last_research_timestamp: string;
  sources_examined: number;
  errors_and_limitations: string[];
  cache_fingerprint?: string | null;
}

export interface LeadProfile {
  schema_version: string;
  lead_id: string;
  input_snapshot?: Record<string, any>;
  identity: {
    name: string;
    first_name?: string;
    last_name?: string;
    job_title?: string;
    company?: string;
    industry?: string;
    linkedin_url?: string;
    company_website?: string;
    professional_email?: string;
    city?: string;
    state?: string;
    country?: string;
  };
  contact?: Record<string, any>;
  company?: Record<string, any>;
  professional_context: ProfessionalContext;
  priority: PriorityInfo;
  sources: SourceEvidence[];
  claims?: LeadClaim[];
  icebreaker?: Icebreaker;
  scoring?: ScoringBreakdown;
  contact_readiness?: ContactReadiness;
  cold_email_context: ColdEmailContext;
  research_metadata: ResearchMetadata;
}

export interface BatchLeadsResponse {
  batch_id: string;
  total_records: number;
  page: number;
  page_size: number;
  total_pages: number;
  leads: PrioritizedLead[];
  message?: string;
}

export interface StartBatchPayload {
  mapping_override?: Record<string, string>;
  dry_run?: boolean;
  max_leads?: number;
  concurrency?: number;
  resume?: boolean;
  use_browser?: boolean;
  use_tor?: boolean;
  tor_proxy?: string;
}

export interface TorStatus {
  is_running: boolean;
  port: number | null;
  proxy_url: string | null;
  executable_found: boolean;
  executable_path: string | null;
}
