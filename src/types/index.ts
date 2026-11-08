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

export type VerificationStatus =
  | "input_provided"
  | "verified"
  | "partially_verified"
  | "unverified"
  | "conflicting"
  | "needs_review";

export interface LeadClaim {
  claim_id: string;
  field: string;
  value?: string | null;
  status: VerificationStatus;
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
  enabled?: boolean;
  state?: string;
  is_running: boolean;
  socks_reachable?: boolean;
  routing_checked?: boolean;
  routing_verified?: boolean;
  port: number | null;
  proxy_url: string | null;
  executable_found: boolean;
  executable_path: string | null;
  details?: string;
}

// ---- Company intelligence (Company Details tab) ----

export type ReviewStatus = "unreviewed" | "verified" | "rejected" | "needs_review";

export interface CompanyFinding {
  finding_id: string;
  product_id: string | null;
  category: string;
  label: string;
  title: string;
  evidence: string;
  source_id: string;
  source_url: string;
  source_domain: string;
  publication_date: string | null;
  accessed_at: string;
  confidence: number;
  verification_status: ReviewStatus;
  review_note: string;
  stale: boolean;
}

export interface ArchitectureComponent {
  id: string;
  name: string;
  responsibility: string;
  documented: boolean;
  evidence_ids: string[];
  source_urls: string[];
  confidence: number;
  known_controls: string[];
  unknowns: string[];
  sealapi_relevance: string;
}

export interface ArchitectureFlow {
  from: string;
  to: string;
  data: string;
  documented: boolean;
  crosses_trust_boundary: boolean;
}

export interface ProductFit {
  classification: "strong" | "validation_required" | "weak" | "insufficient_evidence" | "not_suitable";
  label: string;
  role: string;
  reasoning: string;
  supporting_finding_ids: string[];
  existing_controls_compared: string[];
  compatibility_concerns: string[];
  scope_note: string;
}

export interface CompanyProduct {
  product_id: string;
  name: string;
  url: string;
  inferred: boolean;
  description: string;
  features: string[];
  category?: string;
  rank?: number;
  api_details?: string[];
  ai_details?: string[];
  integration_details?: string[];
  architecture?: {
    status: "documented" | "partial" | "insufficient";
    components: ArchitectureComponent[];
    flows: ArchitectureFlow[];
    trust_boundaries: ArchitectureFlow[];
    unknowns: string[];
    limitation: string;
  };
  fit?: ProductFit;
  score?: {
    total: number;
    factors: { factor: string; value: number; weight: number; points: number; explanation: string }[];
    uncertainty_penalty: number;
    note: string;
  };
}

export interface CompanyGap {
  gap_id: string;
  kind: string;
  product_id: string;
  product_name: string;
  feature: string;
  title: string;
  technical_context: string;
  evidence_ids: string[];
  exposure_scenario: string;
  possible_consequence: string;
  existing_controls: { control: string; finding_id: string; source_url: string }[];
  unverified_controls: string[];
  confidence: number;
  information_needed: string[];
  discovery_question: string;
  capability_ids: string[];
  classification: "potential_risk";
  verified_vulnerability: false;
}

export interface CompanyOpportunity {
  opportunity_id: string;
  product_id: string;
  product_name: string;
  gap_id: string;
  feature: string;
  trust_boundary: string;
  security_requirement: string;
  problem_hypothesis: string;
  why_it_matters: string;
  proposed_contribution: string;
  integration_point: string;
  expected_benefit: string;
  dependencies: string[];
  compatibility: { status: "compatible_pending_validation" | "requires_validation" | "not_supported"; detail: string };
  complexity: { estimate: string; assumptions: string };
  operational_tradeoffs: string;
  capability_ids: string[];
  supporting_finding_ids: string[];
  confidence: number;
  discovery_question: string;
}

export interface CompanyPage {
  source_id: string;
  url: string;
  source_domain: string;
  title: string;
  status_code: number;
  success: boolean;
  error: string;
  published_at: string;
  accessed_at: string;
  category: string;
}

export interface CompanyRecord {
  company_id: string;
  canonical_name: string;
  normalized_domain: string;
  domain_source: string;
  official_website: string;
  input_context: { industry: string; headquarters: string; employee_range: string };
  research_status: string;
  research_warnings: string[];
  errors: string[];
  last_researched_at: string | null;
  identity_corroborated: boolean | null;
  corroboration_note: string;
  overview: {
    official_name?: string;
    logo_url?: string;
    description?: string;
    homepage_title?: string;
    business_model?: string[];
    customer_segments?: string;
    pages_fetched?: number;
  };
  pages: CompanyPage[];
  findings: CompanyFinding[];
  products: CompanyProduct[];
  gaps: CompanyGap[];
  opportunities: CompanyOpportunity[];
  company_fit: ProductFit | null;
  discovery_questions: string[];
  limitations: string[];
  lead_refs: { lead_id: string; batch_id: string; name: string; job_title: string }[];
  progress: { stage: string; pages_done: number; pages_planned: number };
}

export interface CompanyView {
  company_id: string;
  job_running: boolean;
  research_status: string;
  company: CompanyRecord;
  role_questions: string[];
}

export interface OutreachVariant {
  variant_id: string;
  label: string;
  subject: string;
  body: string;
  word_count: number;
  supporting_finding_ids: string[];
  observation_source_url: string | null;
  requires_review: boolean;
  guardrail_violations: string[];
}

export interface CompanyOutreach {
  generated_at: string;
  fit_classification: string;
  capabilities_referenced: string[];
  discovery_questions: string[];
  note: string;
  variants: OutreachVariant[];
  auto_send: false;
}

// ---- Individual research (name-only person research) ----

export type IndividualStageName =
  | "discovery"
  | "identity_resolution"
  | "company_discovery"
  | "company_research"
  | "professional_profile"
  | "verdict";

export interface IndividualStage {
  name: IndividualStageName;
  status: "pending" | "running" | "done" | "failed" | "skipped" | "needs_input" | string;
  message: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface IndividualResearchInput {
  name: string;
  company?: string;
  linkedin_url?: string;
  x_url?: string;
  github_url?: string;
  website?: string;
  location?: string;
  context?: string;
  use_browser?: boolean;
  use_tor?: boolean;
}

export interface IndividualObservation {
  source_id: string;
  source_type: string;
  url: string;
  name: string;
  title: string;
  company: string;
  location: string;
  snippet: string;
  /** Domain from a GitHub company field such as "https://vercel.com"; "" otherwise. */
  company_domain?: string;
}

export interface IndividualCandidate {
  candidate_id: string;
  name: string;
  title: string;
  company: string;
  location: string;
  avatar_url: string;
  profile_url: string;
  description: string;
  linkedin_slug: string;
  github_login: string;
  website: string;
  observations: IndividualObservation[];
  confidence: number;
  confidence_reasons: string[];
}

export interface IndividualFact {
  text: string;
  basis: "verified" | "inferred" | string;
  source_ids: string[];
}

export interface IndividualPerson {
  current_title: string;
  current_company: string;
  location: string;
  role: { category?: string; authority?: string; [key: string]: unknown } | null;
  facts: IndividualFact[];
  github: { login: string; public_repos: number; languages: string[]; ai_repos: unknown[] };
  projects?: IndividualProjects;
  candidate: IndividualCandidate;
  identity_confidence: number;
}

export type LiveStatus = "live" | "beta" | "not_live" | "discontinued" | "unknown";

export interface IndividualLiveProduct {
  name: string;
  url: string;
  description: string;
  features: string[];
  source: "product_page" | "ai_page" | "company_level" | string;
  status: LiveStatus;
  status_label: string;
  signal: string;
  ai_types: string[];
  ai_purposes: string[];
  reason?: string;
}

export interface IndividualRepoProject {
  name: string;
  description: string;
  language: string;
  topics: string[];
  stars: number;
  pushed_at: string;
  repo_url: string;
  homepage: string;
  status: "live" | "down" | "code_only" | "not_checked";
  ai_types: string[];
  ai_purposes: string[];
}

export interface IndividualProjects {
  live: IndividualRepoProject[];
  code_only: IndividualRepoProject[];
  site: { name: string; url: string; status: "live" }[];
  checks_used: number;
}

export interface IndividualAiUseCase {
  evidence: string;
  types: string[];
  purposes: string[];
  stage: "ga" | "beta" | "unspecified";
  context: "product" | "hiring_internal" | "company";
  product: string;
  source_url: string;
  page_title: string;
}

export interface IndividualAiSummary {
  type_counts: Record<string, number>;
  primary_type: string;
  purposes: { purpose: string; label: string; count: number }[];
  stage: "ga" | "beta" | "unspecified";
  contexts: Record<string, number>;
  providers: string[];
}

export interface IndividualCompany {
  name: string;
  domain: string;
  domain_source: string;
  corroborated: boolean | null;
  note: string;
  status: string;
  company_id: string;
  intel: CompanyRecord | null;
}

export interface IndividualSource {
  source_id: string;
  url: string;
  source_type: string;
  title: string;
  retrieved_at: string;
  query?: string;
}

export interface IndividualJob {
  job_id: string;
  status: "running" | "needs_input" | "completed" | "partial" | "failed";
  created_at: string;
  updated_at: string;
  input: IndividualResearchInput;
  stages: IndividualStage[];
  candidates: IndividualCandidate[];
  selected_candidate_id: string;
  identity: { mode: string; message: string; confidence: number } | null;
  person: IndividualPerson | null;
  company: IndividualCompany | null;
  ai_usage: {
    ai_findings: { evidence: string; source_url: string; label: string }[];
    providers: string[];
    ai_products: string[];
    use_cases?: IndividualAiUseCase[];
    summary?: IndividualAiSummary;
  };
  live_products?: { live: IndividualLiveProduct[]; excluded: IndividualLiveProduct[] };
  search_options?: { use_browser: boolean; use_tor: boolean };
  sealapi: {
    relevance: string;
    fit_label: string;
    reasoning: string;
    opportunities: CompanyOpportunity[];
    discovery_questions: string[];
    scope_note: string;
  } | null;
  priority: { level: number; label: string; reasons: string[] } | null;
  sources: IndividualSource[];
  errors: string[];
  limitations: string[];
  running: boolean;
}
