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
  priority_counts: { [key: string]: number };
  created_at: string;
  updated_at?: string;
  input_filename?: string;
  csv_exists?: boolean;
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
  [key: string]: any;
}

export interface SourceEvidence {
  source_url: string;
  source_type: string;
  retrieval_timestamp: string;
  facts_supported: string[];
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
  research_status: string;
  last_research_timestamp: string;
  sources_examined: number;
  errors_and_limitations: string[];
}

export interface LeadProfile {
  schema_version: string;
  lead_id: string;
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
  professional_context: ProfessionalContext;
  priority: PriorityInfo;
  sources: SourceEvidence[];
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
