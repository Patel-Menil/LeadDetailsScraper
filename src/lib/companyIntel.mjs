/**
 * Lead profile tab order and Company Details research-state helpers.
 *
 * Plain ESM JavaScript so the same code runs in Next.js and under `node --test`.
 */

/** Lead Research Profile tabs, in display order. Company Details sits right after Icebreaker & Outreach. */
export const LEAD_PROFILE_TABS = [
  { id: "overview", label: "Overview & Relevance" },
  { id: "icebreaker", label: "Icebreaker & Outreach" },
  { id: "company", label: "Company Details" },
  { id: "claims", label: "Verified Claims" },
  { id: "evidence", label: "Source Evidence" },
  { id: "json", label: "Raw JSON Profile" },
];

const STATUS_META = {
  not_researched: { label: "Not researched", tone: "neutral" },
  pending: { label: "Pending", tone: "info" },
  researching: { label: "Researching", tone: "info" },
  completed: { label: "Completed", tone: "success" },
  completed_with_warnings: { label: "Completed with warnings", tone: "warning" },
  needs_review: { label: "Needs review", tone: "warning" },
  failed: { label: "Failed", tone: "danger" },
};

/**
 * What the Company Details tab should show and allow for a research status.
 * @param {string} status research_status from the API
 * @param {boolean} jobRunning whether a research job is running server-side
 * @param {boolean} hasDomain whether the company has an official domain to research
 */
export function companyStatusMeta(status, jobRunning = false, hasDomain = true) {
  const meta = STATUS_META[status] || { label: status || "Unknown", tone: "neutral" };
  const busy = jobRunning || status === "pending" || status === "researching";
  const hasResults = ["completed", "completed_with_warnings", "needs_review"].includes(status);
  return {
    ...meta,
    busy,
    hasResults,
    canStart: !busy && hasDomain && status === "not_researched",
    canRefresh: !busy && hasDomain && hasResults,
    canRetry: !busy && hasDomain && status === "failed",
    needsDomain: !hasDomain,
  };
}

/** Poll while a job is queued or running. */
export function shouldPoll(view) {
  return Boolean(view && companyStatusMeta(view.research_status, view.job_running).busy);
}

export const FIT_TONE = {
  strong: "success",
  validation_required: "info",
  weak: "warning",
  insufficient_evidence: "neutral",
  not_suitable: "danger",
};
