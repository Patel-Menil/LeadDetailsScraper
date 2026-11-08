import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  STAGE_LABELS, buildStartPayload, confidenceLabel, relevanceMeta, shouldPollJob, downloadFilename, safeHttpUrl, safeAvatarUrl,
  formatErrorDetail, isJobGoneError, JOB_GONE_MESSAGE,
  aiTypeLabel, aiPurposeLabel, aiContextLabel, aiStageLabel, liveStatusMeta, aiTypeChips, jobJson, copyText,
} from "../src/lib/individual.mjs";

describe("Individual research", () => {
  it("sidebar places Individual Research between Dashboard and Prioritized Leads", () => {
    const src = readFileSync(new URL("../src/components/Sidebar.tsx", import.meta.url), "utf8");
    const i = (s) => src.indexOf(`name: "${s}"`);
    assert.ok(i("Dashboard") < i("Individual Research") && i("Individual Research") < i("Prioritized Leads"));
    assert.match(src, /href: "\/individual"/);
  });
  it("stage labels follow pipeline order", () => {
    assert.deepEqual(Object.keys(STAGE_LABELS), ["discovery", "identity_resolution", "company_discovery",
      "company_research", "professional_profile", "verdict"]);
    assert.equal(STAGE_LABELS.verdict, "SealAPI relevance & priority");
  });
  it("buildStartPayload keeps only filled fields", () => {
    assert.deepEqual(buildStartPayload({ name: " Jane Doe ", company: "", location: " Berlin " }), { name: "Jane Doe", location: "Berlin" });
  });
  it("confidence and relevance labels", () => {
    assert.equal(confidenceLabel(0.8), "High"); assert.equal(confidenceLabel(0.5), "Medium"); assert.equal(confidenceLabel(0.1), "Low");
    assert.equal(confidenceLabel(0.75), "High"); assert.equal(confidenceLabel(0.35), "Medium");
    assert.deepEqual(relevanceMeta("needs_validation"), { label: "Needs validation", variant: "warning" });
    assert.deepEqual(relevanceMeta("relevant"), { label: "Relevant", variant: "success" });
    assert.deepEqual(relevanceMeta("not_relevant"), { label: "Not relevant", variant: "neutral" });
    assert.deepEqual(relevanceMeta("anything"), { label: "Insufficient evidence", variant: "info" });
  });
  it("polls only while running", () => {
    assert.equal(shouldPollJob({ running: true, status: "running" }), true);
    assert.equal(shouldPollJob({ running: false, status: "running" }), true);
    assert.equal(shouldPollJob({ running: true, status: "completed" }), true);
    assert.equal(shouldPollJob({ running: false, status: "needs_input" }), false);
    assert.equal(shouldPollJob(null), false);
  });
  it("a 404 while polling means the job is gone", () => {
    assert.equal(isJobGoneError({ status: 404 }), true);
    assert.equal(isJobGoneError({ status: 500 }), false);
    assert.equal(isJobGoneError(new Error("network")), false);
    assert.equal(isJobGoneError(null), false);
    assert.match(JOB_GONE_MESSAGE, /no longer exists.*Start a new search/);
    const page = readFileSync(new URL("../src/app/individual/page.tsx", import.meta.url), "utf8");
    assert.match(page, /shouldPollJob\(job\) && !jobGone/);
    assert.match(page, /isJobGoneError\(err\)/);
  });
  it("name input length matches the server limit", () => {
    const page = readFileSync(new URL("../src/app/individual/page.tsx", import.meta.url), "utf8");
    assert.match(page, /id="ind-name"[\s\S]*?maxLength=\{120\}/);
  });
  it("formats FastAPI validation errors readably", () => {
    const body = { detail: [
      { type: "string_too_short", loc: ["body", "name"], msg: "String should have at least 2 characters" },
      { type: "string_too_long", loc: ["body", "context"], msg: "String should have at most 1000 characters" },
    ] };
    assert.equal(formatErrorDetail(body, "x"),
      "name: String should have at least 2 characters; context: String should have at most 1000 characters");
    assert.equal(formatErrorDetail({ detail: [{ loc: ["body"], msg: "Field required" }] }, "x"), "Field required");
    assert.equal(formatErrorDetail({ detail: "Job not found" }, "x"), "Job not found");
    assert.equal(formatErrorDetail({ message: "m" }, "x"), "m");
    assert.equal(formatErrorDetail({ detail: [{}] }, "fallback"), "fallback");
    assert.equal(formatErrorDetail(null, "fallback"), "fallback");
  });
  it("download filename", () => {
    assert.equal(downloadFilename({ input: { name: "Jane O'Doe" }, created_at: "2026-11-07T10:00:00Z" }), "individual_jane_o_doe_2026-11-07.json");
  });
  it("url safety helpers", () => {
    assert.equal(safeHttpUrl("javascript:alert(1)"), "");
    assert.equal(safeHttpUrl("not a url"), "");
    assert.equal(safeHttpUrl("http://a.com/x"), "http://a.com/x");
    assert.equal(safeAvatarUrl("http://a.com/a.png"), "");
    assert.equal(safeAvatarUrl("https://a.com/a.png"), "https://a.com/a.png");
  });
  it("results page renders every required section", () => {
    const src = readFileSync(new URL("../src/components/IndividualResults.tsx", import.meta.url), "utf8");
    for (const t of ["Identity & Profile", "Professional Background", "Company Intelligence", "Products",
      "AI Usage & SealAPI Relevance", "Sources & Evidence", "Live Products", "Person's projects", "AI use cases"])
      assert.ok(src.includes(t), t);
  });
  it("AI usage and live status labels", () => {
    assert.equal(aiTypeLabel("agentic"), "Agentic");
    assert.equal(aiPurposeLabel("customer_support"), "Customer support");
    assert.equal(aiContextLabel("hiring_internal"), "Hiring / internal");
    assert.equal(aiStageLabel("unspecified"), "");
    assert.equal(aiStageLabel("beta"), "Beta / preview");
    assert.deepEqual(liveStatusMeta("beta"), { label: "Live (beta)", variant: "warning" });
    assert.equal(liveStatusMeta("weird").variant, "neutral");
    assert.deepEqual(
      aiTypeChips({ generative: 1, agentic: 3, predictive: 0 }).map((c) => [c.type, c.count]),
      [["agentic", 3], ["generative", 1]],
    );
  });
  it("copy JSON uses the clipboard, falls back, and reports failure", async () => {
    const job = { job_id: "ind_1", person: { name: "A" } };
    assert.equal(jobJson(job), JSON.stringify(job, null, 2));
    let written = "";
    const ok = await copyText("hello", { isSecureContext: true, navigator: { clipboard: { writeText: async (t) => { written = t; } } } });
    assert.equal(ok, true);
    assert.equal(written, "hello");
    const appended = [];
    const area = { value: "", style: {}, setAttribute() {}, select() {}, remove() { appended.pop(); } };
    const doc = { createElement: () => area, body: { appendChild: (el) => appended.push(el) }, execCommand: (c) => c === "copy" };
    const denied = { navigator: { clipboard: { writeText: async () => { throw new Error("denied"); } } }, document: doc };
    assert.equal(await copyText("x", denied), true);
    assert.equal(area.value, "x");
    assert.equal(appended.length, 0);
    assert.equal(await copyText("x", {}), false);
  });
  it("results page offers Copy JSON next to Download JSON", () => {
    const src = readFileSync(new URL("../src/app/individual/page.tsx", import.meta.url), "utf8");
    assert.ok(src.includes("Copy JSON") && src.includes("Download JSON"));
  });
});
