import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  STAGE_LABELS, buildStartPayload, confidenceLabel, relevanceMeta, shouldPollJob, downloadFilename, safeHttpUrl, safeAvatarUrl,
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
      "AI Usage & SealAPI Relevance", "Sources & Evidence"]) assert.ok(src.includes(t), t);
  });
});
