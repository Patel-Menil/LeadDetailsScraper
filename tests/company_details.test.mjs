import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { LEAD_PROFILE_TABS, companyStatusMeta, shouldPoll } from "../src/lib/companyIntel.mjs";

const page = readFileSync(new URL("../src/app/leads/[leadId]/page.tsx", import.meta.url), "utf8");
const component = readFileSync(new URL("../src/components/CompanyDetails.tsx", import.meta.url), "utf8");

describe("Lead profile tabs", () => {
  it("places Company Details immediately after Icebreaker & Outreach", () => {
    assert.deepEqual(
      LEAD_PROFILE_TABS.map((t) => t.label),
      [
        "Overview & Relevance",
        "Icebreaker & Outreach",
        "Company Details",
        "Verified Claims",
        "Source Evidence",
        "Raw JSON Profile",
      ]
    );
  });

  it("renders the tab bar from the ordered list and mounts Company Details on its tab", () => {
    assert.match(page, /LEAD_PROFILE_TABS\.map\(/);
    assert.match(page, /activeTab === "company" && \(\s*<CompanyDetails/);
    assert.match(page, /<CompanyOutreachCard /);
    // the old hand-written tab buttons are gone, so the order cannot drift
    assert.doesNotMatch(page, /onClick=\{\(\) => setActiveTab\("claims"\)\}/);
  });

  it("Company Details contains every required section A–I", () => {
    for (const title of [
      "Company Overview",
      "Technology and Integrations",
      "Company Products",
      "Product Architecture and Data Flows",
      "Security Gap Analysis",
      "Where BAVRIX Adds Value",
      "Necessity and Product Fit",
      "Discovery Questions",
      "Evidence and Research Limitations",
    ]) {
      assert.ok(component.includes(`title="${title}"`), `missing section ${title}`);
    }
    assert.match(component, /Potential risk — not a verified vulnerability/);
  });
});

describe("Company research states", () => {
  it("offers Start only before research and with a domain", () => {
    const m = companyStatusMeta("not_researched", false, true);
    assert.equal(m.canStart, true);
    assert.equal(m.busy, false);
    assert.equal(m.hasResults, false);
    const noDomain = companyStatusMeta("needs_review", false, false);
    assert.equal(noDomain.canStart, false);
    assert.equal(noDomain.needsDomain, true);
  });

  it("treats pending, researching and running jobs as busy (no duplicate starts)", () => {
    for (const s of ["pending", "researching"]) {
      const m = companyStatusMeta(s, false, true);
      assert.equal(m.busy, true);
      assert.equal(m.canStart || m.canRefresh || m.canRetry, false);
    }
    const running = companyStatusMeta("completed", true, true);
    assert.equal(running.busy, true);
    assert.equal(running.canRefresh, false);
  });

  it("shows results with refresh for completed, partial and review states", () => {
    for (const s of ["completed", "completed_with_warnings", "needs_review"]) {
      const m = companyStatusMeta(s, false, true);
      assert.equal(m.hasResults, true, s);
      assert.equal(m.canRefresh, true, s);
    }
    assert.equal(companyStatusMeta("completed_with_warnings").tone, "warning");
  });

  it("offers Retry only for failed research", () => {
    const m = companyStatusMeta("failed", false, true);
    assert.equal(m.canRetry, true);
    assert.equal(m.hasResults, false);
    assert.equal(m.tone, "danger");
  });

  it("polls only while a job is queued or running", () => {
    assert.equal(shouldPoll({ research_status: "researching", job_running: true }), true);
    assert.equal(shouldPoll({ research_status: "completed", job_running: false }), false);
    assert.equal(shouldPoll(null), false);
  });
});
