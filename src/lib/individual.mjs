/**
 * Pure helpers for the Individual Research page.
 * Plain ESM JavaScript so the same code runs in Next.js and under `node --test`.
 */

/** Pipeline stages in execution order. */
export const STAGE_LABELS = {
  discovery: "Public identity discovery",
  identity_resolution: "Identity resolution",
  company_discovery: "Current company discovery",
  company_research: "Company & product research",
  professional_profile: "Professional background",
  verdict: "SealAPI relevance & priority",
};

export const OPTIONAL_FIELDS = ["company", "linkedin_url", "x_url", "github_url", "website", "location", "context"];

export const JOB_GONE_MESSAGE =
  "This research job no longer exists (the server may have restarted). Start a new search.";

/**
 * Readable message from an API error body. FastAPI validation errors (422) send `detail` as an array of
 * `{loc, msg}` objects; join them ("name: String should have at least 2 characters") instead of "[object Object]".
 */
export function formatErrorDetail(body, fallback) {
  const detail = body?.detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => {
        if (typeof d === "string") return d;
        const msg = typeof d?.msg === "string" ? d.msg : "";
        const field = Array.isArray(d?.loc) ? d.loc[d.loc.length - 1] : "";
        return msg && typeof field === "string" && field && field !== "body" ? `${field}: ${msg}` : msg;
      })
      .filter(Boolean);
    return msgs.length ? msgs.join("; ") : fallback;
  }
  if (typeof detail === "string" && detail) return detail;
  if (typeof body?.message === "string" && body.message) return body.message;
  return fallback;
}

/** A 404 while polling means the job was evicted or lost on restart: stop polling for it. */
export function isJobGoneError(err) {
  return Number(err?.status) === 404;
}

/** Poll only while the server says the job is running. */
export function shouldPollJob(job) {
  return Boolean(job && (job.running === true || job.status === "running"));
}

export function confidenceLabel(x) {
  const n = Number(x) || 0;
  if (n >= 0.75) return "High";
  if (n >= 0.35) return "Medium";
  return "Low";
}

const RELEVANCE = {
  relevant: { label: "Relevant", variant: "success" },
  needs_validation: { label: "Needs validation", variant: "warning" },
  not_relevant: { label: "Not relevant", variant: "neutral" },
  insufficient_evidence: { label: "Insufficient evidence", variant: "info" },
};

export function relevanceMeta(r) {
  const m = RELEVANCE[r] || RELEVANCE.insufficient_evidence;
  return { ...m };
}

/** Trim all fields and drop empty optional ones; `name` is always kept. */
export function buildStartPayload(form) {
  const f = form || {};
  const out = { name: String(f.name ?? "").trim() };
  for (const k of OPTIONAL_FIELDS) {
    const v = String(f[k] ?? "").trim();
    if (v) out[k] = v;
  }
  return out;
}

export function downloadFilename(job) {
  const name = String(job?.input?.name ?? "");
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "person";
  const m = /^\d{4}-\d{2}-\d{2}/.exec(String(job?.created_at ?? ""));
  const date = m ? m[0] : new Date().toISOString().slice(0, 10);
  return `individual_${slug}_${date}.json`;
}

/** Return the URL only if it is a well-formed http(s) URL, else "". */
export function safeHttpUrl(u) {
  try {
    const url = new URL(String(u ?? "").trim());
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : "";
  } catch {
    return "";
  }
}

/** Avatar images are loaded only from https URLs. */
export function safeAvatarUrl(u) {
  const href = safeHttpUrl(u);
  return href.startsWith("https:") ? href : "";
}

export const AI_TYPE_LABELS = {
  generative: "Generative",
  agentic: "Agentic",
  predictive: "Predictive / analytical ML",
  retrieval: "Retrieval / search",
  general: "General AI (type unclear)",
};

export const AI_PURPOSE_LABELS = {
  customer_support: "Customer support",
  coding: "Coding / developer tools",
  content_marketing: "Content & marketing",
  search_knowledge: "Search & knowledge",
  analytics: "Analytics & insights",
  security_fraud: "Security & fraud",
  sales_crm: "Sales & CRM",
  workflow_automation: "Workflow automation",
  document_processing: "Document processing",
  other: "Other",
};

const AI_CONTEXT_LABELS = { product: "In their product", hiring_internal: "Hiring / internal", company: "Company page" };
const AI_STAGE_LABELS = { ga: "GA", beta: "Beta / preview", unspecified: "" };

export function aiTypeLabel(t) {
  return AI_TYPE_LABELS[t] || String(t ?? "");
}

export function aiPurposeLabel(p) {
  return AI_PURPOSE_LABELS[p] || String(p ?? "");
}

export function aiContextLabel(c) {
  return AI_CONTEXT_LABELS[c] || String(c ?? "");
}

export function aiStageLabel(s) {
  return s in AI_STAGE_LABELS ? AI_STAGE_LABELS[s] : String(s ?? "");
}

const LIVE_STATUS = {
  live: { label: "Live", variant: "success" },
  beta: { label: "Live (beta)", variant: "warning" },
  not_live: { label: "Not live", variant: "neutral" },
  discontinued: { label: "Discontinued", variant: "danger" },
  unknown: { label: "Could not confirm live", variant: "neutral" },
  down: { label: "Site down", variant: "danger" },
  code_only: { label: "Code only", variant: "neutral" },
  not_checked: { label: "Not checked", variant: "neutral" },
};

export function liveStatusMeta(s) {
  return { ...(LIVE_STATUS[s] || { label: String(s ?? ""), variant: "neutral" }) };
}

/** Non-zero AI type counts, most common first. */
export function aiTypeChips(typeCounts) {
  return Object.entries(typeCounts || {})
    .filter(([, n]) => Number(n) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .map(([type, count]) => ({ type, label: aiTypeLabel(type), count: Number(count) }));
}
