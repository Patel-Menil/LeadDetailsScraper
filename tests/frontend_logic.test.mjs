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

describe("Operator Session Token Authentication and Web Crypto Security", () => {
  function base64UrlEncode(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary)
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  }

  function base64UrlDecode(str) {
    let base64 = str.replace(/-/g, "+").replace(/_/g, "/");
    while (base64.length % 4) {
      base64 += "=";
    }
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  }

  async function createTestToken(secret, maxAgeSeconds = 3600) {
    const now = Math.floor(Date.now() / 1000);
    const payload = {
      role: "operator",
      iat: now,
      exp: now + maxAgeSeconds,
    };
    const payloadJson = JSON.stringify(payload);
    const encoder = new TextEncoder();
    const payloadB64 = base64UrlEncode(encoder.encode(payloadJson));

    const key = await crypto.subtle.importKey(
      "raw",
      encoder.encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"]
    );

    const sigBuf = await crypto.subtle.sign(
      "HMAC",
      key,
      encoder.encode(payloadB64)
    );
    const signatureB64 = base64UrlEncode(sigBuf);
    return `${payloadB64}.${signatureB64}`;
  }

  async function verifyTestToken(token, secret) {
    if (!token || !secret) return { valid: false };
    const parts = token.split(".");
    if (parts.length !== 2) return { valid: false };
    const [payloadB64, signatureB64] = parts;
    try {
      const encoder = new TextEncoder();
      const key = await crypto.subtle.importKey(
        "raw",
        encoder.encode(secret),
        { name: "HMAC", hash: "SHA-256" },
        false,
        ["verify"]
      );
      const sigBytes = base64UrlDecode(signatureB64);
      const sigBuffer = sigBytes.buffer.slice(
        sigBytes.byteOffset,
        sigBytes.byteOffset + sigBytes.byteLength
      );
      const validSig = await crypto.subtle.verify(
        "HMAC",
        key,
        sigBuffer,
        encoder.encode(payloadB64)
      );
      if (!validSig) return { valid: false };

      const payloadBytes = base64UrlDecode(payloadB64);
      const decoder = new TextDecoder();
      const payload = JSON.parse(decoder.decode(payloadBytes));
      const now = Math.floor(Date.now() / 1000);
      if (!payload.exp || payload.exp <= now) return { valid: false };
      return { valid: true, payload };
    } catch {
      return { valid: false };
    }
  }

  it("creates and verifies valid operator session token", async () => {
    const secret = "test_super_secret_session_key_12345";
    const token = await createTestToken(secret, 3600);
    const res = await verifyTestToken(token, secret);
    assert.equal(res.valid, true);
    assert.equal(res.payload.role, "operator");
  });

  it("rejects expired session token", async () => {
    const secret = "test_super_secret_session_key_12345";
    const expiredToken = await createTestToken(secret, -100); // expired 100s ago
    const res = await verifyTestToken(expiredToken, secret);
    assert.equal(res.valid, false);
  });

  it("rejects tampered session token", async () => {
    const secret = "test_super_secret_session_key_12345";
    const validToken = await createTestToken(secret, 3600);
    const [payloadB64] = validToken.split(".");
    const tamperedToken = `${payloadB64}.tampered_signature_xyz123`;
    const res = await verifyTestToken(tamperedToken, secret);
    assert.equal(res.valid, false);
  });

  it("rejects token verified with wrong secret", async () => {
    const secret1 = "secret_one_key_111";
    const secret2 = "secret_two_key_222";
    const token = await createTestToken(secret1, 3600);
    const res = await verifyTestToken(token, secret2);
    assert.equal(res.valid, false);
  });

  it("rejects malformed token strings", async () => {
    const secret = "test_secret";
    assert.equal((await verifyTestToken("", secret)).valid, false);
    assert.equal((await verifyTestToken("invalidtokenformat", secret)).valid, false);
    assert.equal((await verifyTestToken("a.b.c", secret)).valid, false);
  });
});

describe("CSRF Origin and Security Header Validation", () => {
  function validateCsrfHeaders(origin, host, secFetchSite) {
    if (secFetchSite && secFetchSite === "cross-site") {
      return { allowed: false, status: 403, error: "Cross-site request rejected" };
    }
    if (origin) {
      try {
        const originHost = new URL(origin).host;
        if (host && originHost !== host) {
          return { allowed: false, status: 403, error: "Origin mismatch" };
        }
      } catch {
        return { allowed: false, status: 403, error: "Invalid origin header" };
      }
    }
    return { allowed: true };
  }

  it("permits same-origin mutation requests", () => {
    const res = validateCsrfHeaders("http://localhost:3000", "localhost:3000", "same-origin");
    assert.equal(res.allowed, true);
  });

  it("blocks cross-site Sec-Fetch-Site requests", () => {
    const res = validateCsrfHeaders("http://attacker.com", "localhost:3000", "cross-site");
    assert.equal(res.allowed, false);
    assert.equal(res.status, 403);
  });

  it("blocks origin header mismatch", () => {
    const res = validateCsrfHeaders("http://evil-origin.com", "localhost:3000", "same-site");
    assert.equal(res.allowed, false);
    assert.equal(res.status, 403);
  });

  it("blocks malformed origin headers", () => {
    const res = validateCsrfHeaders("not-a-valid-url", "localhost:3000", null);
    assert.equal(res.allowed, false);
    assert.equal(res.status, 403);
  });
});

describe("Readiness Contract and Export Separation", () => {
  it("strictly separates ready leads from ready_with_caveat and needs_review in exports", () => {
    const batchLeads = [
      { name: "Lead 1", priority: 0, contact_readiness: "ready", email: "lead1@corp.com" },
      { name: "Lead 2", priority: 0, contact_readiness: "ready_with_caveat", email: "lead2@corp.com" },
      { name: "Lead 3", priority: 1, contact_readiness: "needs_research", email: "lead3@corp.com" },
      { name: "Lead 4", priority: 2, contact_readiness: "not_ready", email: "" },
    ];

    // Only 'ready' leads must be exported to outreach_ready.csv
    const outreachReady = batchLeads.filter((l) => l.contact_readiness === "ready");
    assert.equal(outreachReady.length, 1);
    assert.equal(outreachReady[0].name, "Lead 1");

    // All other leads must be routed to needs_review.csv
    const needsReview = batchLeads.filter((l) => l.contact_readiness !== "ready");
    assert.equal(needsReview.length, 3);
    assert(needsReview.some((l) => l.name === "Lead 2"));
    assert(needsReview.some((l) => l.name === "Lead 3"));
    assert(needsReview.some((l) => l.name === "Lead 4"));
  });

  it("does not elevate unverified candidates to priority 0", () => {
    const evaluateLeadFit = (leadFitScore, hasVerifiedIdentity, hasVerifiedRole) => {
      if (leadFitScore >= 70 && hasVerifiedIdentity && hasVerifiedRole) {
        return 0; // Priority 0
      }
      return 1; // Blocked to Priority 1 or lower
    };

    assert.equal(evaluateLeadFit(95, true, true), 0);
    assert.equal(evaluateLeadFit(95, false, true), 1, "Unverified identity must block P0");
    assert.equal(evaluateLeadFit(95, true, false), 1, "Unverified role must block P0");
    assert.equal(evaluateLeadFit(95, false, false), 1, "Unverified candidate must block P0");
  });
});
