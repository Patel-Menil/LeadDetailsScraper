# LeadDetailsScraper — Critical Bug Fixes and Production-Readiness Implementation

## Repository

GitHub: https://github.com/Patel-Menil/LeadDetailsScraper/

Repository: `Patel-Menil/LeadDetailsScraper`

Default branch: `main`

## Primary Objective

Audit and fix the existing LeadDetailsScraper codebase. The project already has a Next.js frontend, FastAPI backend, Scrapling-based public-web research, identity resolution, lead scoring, evidence schemas, icebreaker generation, batch exports, and Docker support.

Do not rewrite the application from scratch. Preserve the existing architecture, user interface, API contracts, and useful functionality wherever possible.

**Implement the fixes directly in the code, run the tests, investigate failures, and deliver a working result. Do not stop after producing an audit or development plan.**

Start by checking the latest commit and repository state. Re-read the current versions of the files before changing them because the repository may have changed since the previous review.

Primary files to inspect:

- `src/lead_research/research.py`
- `src/lead_research/identity.py`
- `src/lead_research/icebreaker.py`
- `src/lead_research/scoring.py`
- `src/lead_research/schemas.py`
- `src/lead_research/scraper.py`
- `src/lead_research/pipeline.py`
- `src/lead_research/fingerprint.py`
- `src/lead_research/exporter.py`
- `src/lead_research/server.py`
- `tests/`
- `src/lib/api.ts`
- `src/types/`
- `Dockerfile`
- `docker-compose.yml`
- `.gitignore`
- `README.md`

---

# Phase 1 — Fix Identity Verification and Claim Provenance

**Priority: P0 — must be fixed before trusting the research results.**

## Current problems to investigate

The research process has allowed imported lead data to be treated as verified information. It also raises the identity score when a company website is successfully fetched, even though the website may not mention the intended person.

A successful HTTP response only demonstrates that a page could be fetched. It does not prove:
- The intended person has been identified correctly.
- The person works for the supplied company.
- The job title is current.
- The email belongs to that person.
- The page supports the particular claim being made.

## Required changes

### 1.1 Separate input-provided information from web-verified information

Preserve the original imported row in `input_snapshot`.

For every researched field, maintain its provenance and status separately.

Recommended statuses:

- `input_provided`
- `verified`
- `partially_verified`
- `unverified`
- `conflicting`
- `needs_review`

Adapt these to the existing schema without unnecessarily breaking backwards compatibility.

Never mark a name, title, employer, email, or other person-specific field as `verified` solely because it appeared in the input CSV.

### 1.2 Remove the company-fetch identity shortcut

In `research.py`, remove any behavior that automatically raises the person's identity score simply because the company website was fetched successfully.

The company website can support claims about the company, products, domain, and public announcements. It supports a person's employment or title only when the actual evidence establishes that relationship.

### 1.3 Verify claims independently

For each important claim, store:
- Claim ID.
- Field and value.
- Verification status.
- Supporting source IDs.
- Evidence quality or confidence.
- Verification timestamp.
- Explanation for review or rejection.

Every verified claim must reference existing source IDs. Every referenced source ID must resolve to a source record.

A verification threshold is not proof. Prevent high scores from overriding identity conflicts or absent supporting evidence.

### 1.4 Handle abbreviated names safely

Names such as `Jon B` and `Andrew R` must not be automatically expanded from an unrelated same-name search result.

Retain the exact imported value. Expand the name only when reliable evidence supports the full identity and the company association. Otherwise, keep the record in review.

### Acceptance tests

- An imported full name is not automatically an independently verified identity.
- Fetching a company homepage alone cannot verify the person or title.
- An identity mismatch triggers review or conflict.
- A verified claim without valid source IDs is rejected.
- Abbreviated names are not expanded without adequate supporting evidence.

---

# Phase 2 — Fix Search Discovery, Page Fetching, and Source Quality

**Priority: P0.**

## Current problem

Search results and snippets may be stored as research sources and used to generate professional context without fetching their destination pages.

Search is useful for finding candidates, but a search-result title or snippet is not equivalent to inspected source content.

## Required implementation

Use this sequence:

1. Generate a limited number of targeted searches using the lead's name, company, domain, and role.
2. Parse candidate URLs and discovery metadata.
3. Normalize URLs and remove duplicates.
4. Rank candidate results for identity and topical relevance.
5. Fetch eligible destination pages using the existing Scrapling implementation.
6. Extract relevant text, title, metadata, and publication dates where available.
7. Check whether the fetched content actually mentions the intended person or company and supports the proposed claim.
8. Create source-backed claims from the relevant evidence.
9. Record fetch failures, access restrictions, source conflicts, and identity ambiguity.
10. Use only eligible evidence in verification and personalization.

Prioritize official company pages, leadership or team biographies, company-owned technical blogs, product announcements, public interviews, job postings, and reputable reporting.

### Important rules

- Do not label a search snippet as fetched evidence.
- Do not label an HTTP 200 response as verified evidence automatically.
- Do not count duplicate or syndicated content as independent corroboration.
- Do not attach a same-name person's career or projects to the target lead without an adequate identity match.
- Do not bypass login walls, CAPTCHAs, paywalls, or other access restrictions.
- Keep source discovery, page-fetch success, identity matching, claim verification, and research completion as separate states.

Each source should retain its URL, title, source type, retrieval time, useful excerpt, quality assessment, and the claims it supports.

### Acceptance tests

Create mocked tests where:
- A search result exists but fetching its destination fails.
- The destination page is irrelevant to the lead.
- Two people have similar names but different companies.
- The destination page contradicts the input title.
- Duplicate pages refer to the same underlying announcement.

None of these situations may produce a falsely verified claim.

---

# Phase 3 — Fix Icebreakers and Outreach Personalization

**Priority: P0.**

Inspect `icebreaker.py` and the synthesis methods in `research.py`.

## Current problems

Generic keywords such as AI, agent, API, or platform can cause a company page to be classified as a product launch or technical signal. The resulting message can claim to have noticed a public announcement when the inspected page did not establish that one occurred.

A populated source ID does not automatically make an icebreaker factually grounded.

## Required behavior

### 3.1 Separate these concepts

- Public signal discovery.
- Signal verification.
- Relevance to the specific lead.
- Possible SealAPI use case.
- Hypothetical pain point.
- Final icebreaker text.
- Outreach draft readiness.

Never treat a hypothesis as an established customer problem.

### 3.2 Validate the actual statement

Before setting an icebreaker to `ready`:

1. Confirm that the supporting source IDs exist.
2. Confirm that the source refers to the correct company or person.
3. Confirm that the evidence supports the actual factual statement.
4. Do not classify a general company description as a product launch.
5. Do not invent recent activity, personal interests, achievements, internal technology, security problems, or buying intent.
6. Clearly label potential pain points as hypotheses.
7. Generate an honest professional fallback when there is no useful public signal.
8. Mark ambiguous or weakly supported personalization as `needs_review`.

A valid source reference is necessary, but the content of that source must also substantiate the message.

### 3.3 Improve the generated opener

An evidence-backed message should contain:
- A short, accurate observation.
- A natural explanation for why it is relevant.
- One thoughtful question.
- A concise connection to SealAPI when appropriate.
- A low-pressure next step.

Example of the desired style, for a fictional company that has published an article about AI agents calling enterprise APIs:

"I read your team's article about AI agents interacting with enterprise APIs. How are you thinking about controlling which services and data those agents can access?"

Do not insert this example into a real profile as a fact.

Avoid generic statements that falsely imply the sender has followed the person's work. Do not claim prior contact, a mutual connection, a security weakness, or a recent launch unless evidence supports it.

### 3.4 Add deterministic grounding tests

For every icebreaker marked `ready`, test that all factual claims are supported by the attached source evidence. Include negative cases where a company page contains keywords but no announcement or person-specific information.

A generic fallback may be usable for contact even when personalization is unavailable. Keep contact readiness and personalization readiness independent.

---

# Phase 4 — Fix Lead Scoring and Contact Readiness

**Priority: P0.**

Inspect `scoring.py`.

## Current problems

The current scoring logic can combine imported titles, industries, company keywords, and scraped text, then label keyword matches as a verified technical or security need.

It also derives some verification indicators from the presence of fields instead of checking evidence-backed claims.

## Required changes

Maintain three distinct outputs.

### A. Lead-fit score

Measures how relevant a prospect might be to SealAPI.

Consider:
- Role and decision-making authority.
- Company and use-case fit.
- Verified public technical context.
- Relevant public company activity.
- Alignment with SealAPI's actual capabilities.

Imported data can help with initial prospect selection, but must be labeled as supplied input rather than verified evidence.

### B. Verification confidence

Measures reliability of the researched record.

Consider:
- Correct-person evidence.
- Company and title verification.
- Source authority and relevance.
- Source recency.
- Independent corroboration.
- Conflicting evidence.

Do not raise confidence merely because the email field is populated or several unrelated pages were found.

### C. Contact readiness

Determines whether sufficient accurate information exists to contact the lead through a professional channel.

Use explicit readiness blockers such as:
- `identity_not_verified`
- `current_role_not_verified`
- `company_not_verified`
- `no_usable_contact_channel`
- `email_unverified`
- `identity_conflict`
- `personalization_needs_review`

Do not require a personalized icebreaker for every legitimate contact. However, do not label a message as personalized and ready when its factual grounding is insufficient.

### Scoring rules

- Remove the claim that keyword matches alone prove a “verified AI/API security need.”
- Explain which inputs and evidence contributed to each score.
- Make unverified or conflicting claims affect verification and readiness, not automatically the fit score.
- Do not assign maximum priority simply because a person is a senior leader in a target industry.
- Where technical buying intent is unknown, explicitly identify it as unknown.
- Add unit tests for misleading keyword-rich data and low-quality evidence.

---

# Phase 5 — Fix Batch IDs, Storage Isolation, and Failure Accounting

**Priority: P0/P1.**

The required canonical storage location is:

`data/output/batches/{batchID}/`

Each batch should contain appropriate versions of:
- `manifest.json`
- `summary.json`
- `leads_input_snapshot.csv`
- `leads_prioritized.csv`
- `leads_enriched.csv`
- `outreach_ready.csv`
- `needs_review.csv`
- `lead_profiles.jsonl`
- `sources.jsonl`
- `claims.jsonl`
- `errors.csv`
- `errors.jsonl`
- `profiles/`
- `scraping.log`

Preserve existing API-compatible paths or aliases only where necessary.

## 5.1 Guarantee unique batch IDs

Inspect `server.py`, `pipeline.py`, and `fingerprint.py`.

The upload endpoint must not generate batch IDs solely from a second-resolution timestamp and filename. Use the existing `create_batch_id()` helper or an equivalent collision-resistant method.

All workers in the same research run must share one batch ID.

Clearly distinguish:
- Uploading an input file.
- Starting a new research run.
- Resuming an interrupted run.
- Reprocessing previously completed research.

A new research run must receive a new batch ID. An explicit resume may continue an existing incomplete batch when its inputs and configuration are compatible. Do not silently restart or overwrite a completed batch.

If an ID already exists for an unrelated or incompatible batch, return an explicit error or require the creation of a new batch.

## 5.2 Preserve completed history

The exporter must not silently overwrite historical results.

Use safe file-writing practices and ensure the selected `batchID` is propagated into profile metadata, exports, logs, manifests, and API responses.

Update `latest.json` atomically after the batch reaches its intended publishable state.

The manifest should include:
- Batch ID.
- Schema and pipeline versions.
- Start and completion timestamps.
- Input filename and SHA-256 hash.
- Relevant configuration fingerprint.
- Actual processed, completed, partial, failed, and review counts.
- Output file paths.
- Overall outcome.

Do not place secrets in manifests.

## 5.3 Ensure every lead is accounted for

Inspect exception handling in `pipeline.py`.

The current implementation may increment failure counts for worker exceptions without retaining a per-lead failure record in the exported output. It may also label a batch completed despite worker failures.

Correct this.

Every accepted input lead must appear in the run outcome as one of:
- Completed.
- Partial.
- Failed.
- Explicitly skipped, with a reason.

Save structured errors containing the lead ID, stage, error category, and concise diagnostic information. Avoid including secrets or unnecessary personal data.

Pass worker failures into the exporter and include them in `errors.csv` and `errors.jsonl`.

Set overall batch status consistently:
- `completed` only when the batch has completed according to the documented policy.
- `partial` when recoverable failures or incomplete research remain.
- `failed` when the batch cannot complete its essential processing.

Do not claim success merely because export generation finished.

## 5.4 Verify readiness exports

Only include records in `outreach_ready.csv` when they meet the implemented readiness policy.

Place other leads in `needs_review.csv` with understandable blockers.

Confirm that all lead counts reconcile across CSVs, profiles, summary, manifest, and API responses.

Add tests for repeated uploads, duplicate starts, partial runs, worker exceptions, empty results, safe resume, and concurrent batch creation.

---

# Phase 6 — Fix Resume Fingerprints and Stale Profiles

**Priority: P1.**

Inspect `fingerprint.py` and `pipeline.py`.

The current fingerprinting logic may omit lead fields, pipeline settings, and research configuration. The cache may also accept a legacy profile that has no fingerprint.

## Required behavior

The cache fingerprint must cover all research-relevant inputs and configuration, including:

- All relevant imported fields, normalized deterministically.
- Industry, company domain, role, contact details, and other fields actually used by research.
- Pipeline version.
- Schema version.
- Material scraping and research configuration.
- Relevant query or prompt versions when applicable.

Do not depend on an arbitrarily short hard-coded selection of lead columns.

Use a stable serialization and cryptographic hash.

Resume only when the existing result's fingerprint matches. Invalidate or explicitly migrate legacy profiles that lack a fingerprint; do not automatically treat them as compatible.

When resuming:
- Do not duplicate lead rows or counts.
- Preserve the original batch ID.
- Preserve successfully completed compatible work.
- Account for any leads that still need processing.
- Prevent stale or incompatible research from being reused.

Add regression tests demonstrating that changes to industry, title, company domain, configuration, schema, or pipeline version invalidate the cache when relevant.

---

# Phase 7 — Fix URL Safety and Scraper Security

**Priority: P1.**

Inspect `is_safe_url()` and all code paths that use `Fetcher`, browser fetching, redirects, and search-result URLs.

The existing checks need to be reviewed for DNS-based addresses and redirects. Checking only the original URL is insufficient when the client follows redirects automatically.

## Required safeguards

- Accept only HTTP and HTTPS schemes.
- Block loopback, private, link-local, multicast, reserved, and internal destinations.
- Validate resolved IP addresses for hostnames where applicable.
- Revalidate every redirect destination, or disable automatic redirects and handle them safely.
- Prevent a public URL from redirecting to a local or private address.
- Apply the same policy to browser-based navigation.
- Validate URLs obtained from search results before fetching.
- Keep timeouts, bounded retries, and per-domain rate limiting.
- Never bypass access restrictions to obtain protected personal information.
- Log rejected fetches without exposing unnecessary data.

Avoid introducing a fragile URL-checking implementation that breaks legitimate public URLs. Add tests for IPv4, IPv6, encoded addresses, malformed URLs, redirect chains, and private or local targets.

---

# Phase 8 — Fix Schema Versioning

**Priority: P1.**

Inspect `schemas.py`, `research.py`, and `exporter.py`.

Ensure new profiles consistently advertise their actual schema version. The returned `LeadProfile` must not claim to be schema V1 when its metadata and manifest claim V2.

Preserve compatibility with the existing frontend/API. Add or update migrations and validation tests for:
- Legacy V1 profiles.
- New V2 profiles.
- Missing optional fields.
- Invalid claim/source references.
- Profiles with incompatible versions.
- Manifest/profile schema consistency.

Do not perform a breaking schema migration without updating its consumers and tests.

---

# Phase 9 — Protect Real Lead Data in the Public Repository

**Priority: P0 — security and data handling.**

Audit tracked files and Git history for real lead contact data and generated research profiles.

The repository has been public, and lead datasets and generated profiles have appeared in tracked files. The fact that an ignore pattern exists does not remove files that are already tracked or data already present in Git history.

## Required actions

1. Identify real lead datasets, generated profiles, and other personal or commercially sensitive lead records in tracked files.
2. Remove these data artifacts from the repository's current tracked tree.
3. Keep `.gitignore` rules for generated batches, exports, uploads, and real lead datasets.
4. Replace any test dependence on real people with synthetic/anonymized fixtures.
5. Ensure CI tests never require real lead datasets.
6. Check for accidentally committed credentials or tokens. Report any findings without printing secret values.
7. Add a documented data-remediation checklist.

**Do not perform a destructive history rewrite or force-push to `main` without explicit operator approval.** Instead, document the exposed file paths, affected commit range where known, and the recommended history-cleanup steps. Ensure the current branch is cleaned in the authorized scope and tell the operator what remains to be done.

Do not reproduce real people's email addresses or profile contents in the final report.

---

# Phase 10 — Add Regression Tests and Run the Full Suite

**Priority: P0/P1.**

Extend the existing tests, especially:

- `tests/test_identity.py`
- `tests/test_scraper_mocked.py`
- `tests/test_scoring.py`
- `tests/test_exporter.py`
- `tests/test_pipeline_e2e.py`
- `tests/test_v2_pipeline.py`
- `tests/test_api.py`
- `tests/frontend_logic.test.mjs`

Test at minimum:

### Identity and evidence
1. Input-provided facts are not independently verified by default.
2. Company homepage fetch success cannot verify a person's role.
3. Unrelated same-name people are not merged.
4. Search snippets alone cannot verify claims.
5. Destination pages must support the claims made about them.
6. Every verified claim has valid supporting source IDs.
7. Contradictions are retained and surfaced.
8. Duplicate sources do not inflate confidence.

### Icebreakers
9. A generic AI keyword does not create a verified product launch.
10. A ready icebreaker requires sources that support its factual assertions.
11. Weak evidence triggers review or an explicit generic fallback.
12. Unsupported achievements, relationships, or security concerns are never invented.

### Scoring and contact readiness
13. Keywords alone cannot establish an actual buying need.
14. Unverified roles do not count as verified titles.
15. Email format validation is not labeled as email deliverability verification.
16. Fit, verification confidence, and contact readiness remain separate.

### Batches and cache
17. Unique batch IDs do not collide in normal concurrent creation.
18. A new run cannot silently overwrite a completed run.
19. Resume uses the correct fingerprint and avoids double-counting.
20. Failed workers appear in the batch errors and outcome accounting.
21. The overall status reflects real failures.
22. CSV, JSONL, profiles, summary, and manifest counts agree.
23. The `outreach_ready.csv` contains only records accepted by readiness rules.
24. Legacy profiles do not bypass fingerprint validation by default.

### Security and integration
25. Redirects cannot bypass URL restrictions.
26. No real lead dataset is needed for automated tests.
27. The API can read new V2 profiles and required legacy profiles.
28. The frontend remains compatible with the API response models.

## Execute and report the actual checks

Run, at minimum, the project-supported commands:

```bash
pytest tests/ -v
npm test
npm run typecheck
npm run build
```

Run these in the appropriate environment, resolving dependency or environment setup issues where feasible. Add or update CI so the core backend and frontend checks can run on future changes.

If a command fails, diagnose the failure and fix it where it is in scope. Do not report a test as passed if it did not actually run. Clearly distinguish infrastructure or dependency failures from application test failures.

Run integration and Docker checks when the environment supports them, and document any checks that could not be executed.

---

# Phase 11 — Controlled End-to-End Validation

Do not immediately run an unrestricted full live scrape after code changes.

First:
1. Pass the unit tests and mocked integration tests.
2. Run a small, controlled sample using mocked or authorized public sources.
3. Inspect the generated profiles and source-to-claim relationships.
4. Test partial failures and resume behavior.
5. Review the generated icebreakers manually.
6. Verify that one batch is stored under its own ID without altering previous batches.
7. Confirm that the API and dashboard can browse the batch and download its exports.
8. Only after these checks pass, run a controlled live sample if appropriate.
9. Reprocess the broader dataset only once quality and data-handling safeguards are acceptable, using a new batch ID.

Do not claim that the full dataset is accurate based solely on successful scraping or a completed manifest.

---

# Final Acceptance Criteria

The task is complete only when:

- Person identity and employment claims are independently supported by appropriate evidence.
- Search discovery is separated from destination-page fetching and claim verification.
- Icebreakers marked ready are factually grounded and traceable to sources.
- Generic fallback messages are not mislabeled as personalized research.
- Lead fit, evidence confidence, and contact readiness are separate and explainable.
- Batch IDs are collision-resistant and batch history is preserved.
- Resume only reuses compatible cached results.
- All input leads are accounted for, including failed or skipped leads.
- Schema versions are consistent and compatible with the application.
- URL safety covers redirects and resolved addresses.
- Real lead data is removed from the authorized current repository scope and replaced in tests with synthetic fixtures.
- Backend tests, frontend tests, type checking, and production build have been run, with results documented accurately.
- Docker and API behavior remain functional where validated.

# Required Final Report

After implementation, provide:

1. **Verdict:** what is fixed, what remains blocked, and whether the result is ready for controlled use.
2. **Root causes:** what was wrong and how each issue was corrected.
3. **Files changed:** list the major files and the purpose of each change.
4. **Tests:** exact commands and their actual results.
5. **Security/data handling:** current-tree cleanup completed, history remediation status, and any operator actions still required.
6. **Storage:** an example of the new batch layout and its manifest, using synthetic data.
7. **Quality checks:** whether source evidence, identities, claims, icebreakers, and counts meet the new invariants.
8. **Remaining limitations:** unresolved issues, external dependencies, and checks that could not be performed.
9. **Run instructions:** exact commands to start the app, run tests, process a controlled batch, resume it, and export results.

**Execution rule: Do the implementation now, phase by phase. Do not return only recommendations, do not weaken verification criteria to make the tests pass, do not invent successful test results, and do not delete or rewrite unrelated user work.**