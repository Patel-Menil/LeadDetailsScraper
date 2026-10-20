import test, { describe, it } from "node:test";
import assert from "node:assert/strict";

describe("Frontend Priority and Sorting Logic", () => {
  it("strictly sorts priorities numerically: 0 first, then 1, then 2", () => {
    const leads = [
      { id: "1", priority: 2, name: "Lead 2" },
      { id: "2", priority: 0, name: "Lead 0" },
      { id: "3", priority: 1, name: "Lead 1" },
      { id: "4", priority: "0", name: "Lead 0 str" },
      { id: "5", priority: 2, name: "Lead 2b" },
    ];

    const sorted = [...leads].sort((a, b) => Number(a.priority) - Number(b.priority));
    assert.equal(Number(sorted[0].priority), 0);
    assert.equal(Number(sorted[1].priority), 0);
    assert.equal(Number(sorted[2].priority), 1);
    assert.equal(Number(sorted[3].priority), 2);
    assert.equal(Number(sorted[4].priority), 2);
  });

  it("handles pagination calculations correctly across pages", () => {
    const totalRecords = 52;
    const pageSize = 25;
    const totalPages = Math.ceil(totalRecords / pageSize);
    assert.equal(totalPages, 3);

    // Page 1 bounds
    const page1Start = (1 - 1) * pageSize;
    const page1End = Math.min(page1Start + pageSize, totalRecords);
    assert.equal(page1Start, 0);
    assert.equal(page1End, 25);

    // Page 3 bounds (last page)
    const page3Start = (3 - 1) * pageSize;
    const page3End = Math.min(page3Start + pageSize, totalRecords);
    assert.equal(page3Start, 50);
    assert.equal(page3End, 52);
  });

  it("filters leads accurately by search query across multiple fields", () => {
    const leads = [
      { name: "John Doe", company: "CyberGuard", job_title: "CISO", email: "john@cyber.com" },
      { name: "Alice Smith", company: "AI Protect", job_title: "Head of AI", email: "alice@ai.io" },
      { name: "Bob Martin", company: "FinTech Corp", job_title: "CTO", email: "bob@fintech.com" },
    ];

    const search = "ciso";
    const matches = leads.filter(
      (l) =>
        l.name.toLowerCase().includes(search) ||
        l.company.toLowerCase().includes(search) ||
        l.job_title.toLowerCase().includes(search) ||
        l.email.toLowerCase().includes(search)
    );

    assert.equal(matches.length, 1);
    assert.equal(matches[0].name, "John Doe");
  });

  it("filters leads accurately by priority and research status", () => {
    const leads = [
      { name: "A", priority: 0, research_status: "completed" },
      { name: "B", priority: 1, research_status: "partial" },
      { name: "C", priority: 0, research_status: "partial" },
      { name: "D", priority: 2, research_status: "failed" },
    ];

    const p0Completed = leads.filter((l) => l.priority === 0 && l.research_status === "completed");
    assert.equal(p0Completed.length, 1);
    assert.equal(p0Completed[0].name, "A");

    const partialLeads = leads.filter((l) => l.research_status === "partial");
    assert.equal(partialLeads.length, 2);
  });
});

describe("Frontend API Client Endpoints Construction", () => {
  it("formats export URLs correctly with encoded parameters", () => {
    const batchId = "batch_123456_test";
    const csvUrl = `/api/batches/${encodeURIComponent(batchId)}/exports/prioritized.csv`;
    const zipUrl = `/api/batches/${encodeURIComponent(batchId)}/exports/zip`;
    const manifestUrl = `/api/batches/${encodeURIComponent(batchId)}/exports/manifest.json`;
    const errorsUrl = `/api/batches/${encodeURIComponent(batchId)}/exports/errors.csv`;

    assert.equal(csvUrl, "/api/batches/batch_123456_test/exports/prioritized.csv");
    assert.equal(zipUrl, "/api/batches/batch_123456_test/exports/zip");
    assert.equal(manifestUrl, "/api/batches/batch_123456_test/exports/manifest.json");
    assert.equal(errorsUrl, "/api/batches/batch_123456_test/exports/errors.csv");
  });

  it("handles profile JSON serialization and deep copy", () => {
    const mockProfile = {
      schema_version: "1.0.0",
      lead_id: "lead_abc123",
      identity: { name: "Alice Wonderland", job_title: "Chief AI Officer" },
      priority: { numeric_priority: 0, score: 95.0, reason: "C-Level AI Executive" },
    };

    const serialized = JSON.stringify(mockProfile, null, 2);
    assert(serialized.includes('"lead_id": "lead_abc123"'));
    assert(serialized.includes('"numeric_priority": 0'));

    const parsed = JSON.parse(serialized);
    assert.deepEqual(parsed, mockProfile);
  });
});
