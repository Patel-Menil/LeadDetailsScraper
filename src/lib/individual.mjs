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
