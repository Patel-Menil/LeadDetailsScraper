# LeadDetailsScraper — Comprehensive Pipeline & Dataset Audit

**Audit Date:** 2026-10-20  
**Repository:** `Patel-Menil/LeadDetailsScraper` (`c:\sealapi\dataScrap\Combine`)  
**Target Environment:** Python 3.14 (Win32), Node.js (Next.js 14.2.23), Docker  
**Status:** Completed Baseline Audit (Phase A)

---

## 1. Executive Summary

An in-depth inspection of the active codebase, baseline automated tests, and the existing 144-lead dataset (`newlead.csv` and batch `batch_1791659938_newlead`) was performed. 

The audit reveals that while the baseline architecture contains working foundational components (FastAPI backend, Next.js frontend, Scrapling scrapers, importer, exporter), the research pipeline suffers from fundamental data-quality, identity-resolution, and evidence-verification flaws:
1. **Search Snippet Misattribution:** Search engine snippets from DuckDuckGo are treated directly as "Verified Career & Background" facts without page-level fetching or validation.
2. **Identity Confusion & Contamination:** Abbreviated names (e.g. `Andrew R`, `Jon B`) match random public individuals or marketplace freelancers (e.g. 5 random Upwork freelancers attached to Upwork's CTO profile).
3. **Severe Score & Status Inflation:** 104 out of 144 leads (72.2%) are classified as Priority 0 ("Highest Fit"), and 100% (144/144) are marked as `research_status: completed` regardless of scrape timeouts or lack of verified evidence.
4. **Boilerplate & Hallucinated Outreach:** Icebreakers and professional contexts rely on hardcoded keyword rules (e.g., claiming "Architecting and directing AI strategy" purely based on job title) and fixed CTA strings ("next Tuesday").
5. **Storage & Batch Structure Discrepancies:** Deliverables are mirrored across `output/profiles` and `data/output/profiles` due to duplicate exporter code, while missing an immutable `data/output/batches/{batchID}/` layout with cryptographic provenance.
6. **Baseline Test Failure:** Baseline pytest suite failed with 1 test failure (`tests/test_scraper_mocked.py`: unmocked browser fallback attempting live network connection and returning HTTP 504 instead of 500).

---

## 2. Codebase & Environment Inspection

### 2.1 Git & Working Tree
- **Branch:** `main` (clean working tree).
- **Recent Commit:** `39d7b14 Initial commit` (committed both `output/` and `data/output/` directories).
- **.gitignore:** Ignores `data/batches/` and `data/uploads/`, but omitted `output/` and `data/output/`, causing duplicate files to be tracked in git.

### 2.2 Baseline Test Execution
- **Python Test Suite (`pytest` with `PYTHONPATH=.`):**
  - Total tests: 21
  - **Passed:** 20
  - **Failed:** 1 (`tests/test_scraper_mocked.py::test_mocked_scrapling_fetch_retry_and_failure`)
    - *Root Cause:* In `src/lead_research/scraper.py:fetch_url()`, when `Fetcher.get` failed, the code fell back to `StealthyFetcher.fetch()` (which attempted a real network connection to `https://nonexistent-domain-404.example.com`, timed out, and returned status 504 instead of mocked 500).
- **Frontend Test Suite (`npm test`):**
  - Total tests: 6 passed (0 failures).
- **TypeScript Typecheck (`npm run typecheck`):**
  - Passed cleanly with 0 type errors.

---

## 3. Detailed Audit of the 144-Lead Dataset

The dataset was analyzed from `newlead.csv` (144 rows) and the latest batch output `data/batches/batch_1791659938_newlead/profiles/`.

### 3.1 Field Completeness
- **Total Leads:** 144
- **Professional Email Present:** 144 (100%)
  - *Observation:* Imported records include an `Email Status: verified` column from external provider data. The existing pipeline trusted this without distinguishing syntax validation, provider claim, or deliverability probe.
- **LinkedIn URL Present:** 100 (69.4%)
- **LinkedIn URL Missing:** 44 (30.6%)
- **Abbreviated Surnames:** Exactly 44 leads (30.6%) have single-letter surnames (e.g., `Andrew R`, `Jon B`, `Haixun W`, `Jimit M`, `Marty S`, `Vincent C`, `Sundu R`, `Dinanath G`, `Henry S`, `Rahul P`, `Matt F`).

### 3.2 Identity Resolution & Contamination Analysis
When searching DuckDuckGo for `name + company`, the scraper grabbed the top 6 search snippets without checking domain ownership, employment dates, or name consistency:
- **Case 1: Andrew R (CTO & Head of AI at Upwork)**
  - *Actual Profile:* CTO of Upwork (`andrewrabinovich@upwork.com`).
  - *Scraped Sources attached as "Verified Career & Background":*
    1. `Andrew R. - Expert Blue Prism RPA Developer - Upwork` (Freelancer on platform)
    2. `Andrew R. - Devops and python engineer, lifelong tech tinkerer - Upwork` (Freelancer on platform)
    3. `Andrew R. - Senior Developer - Upwork` (Freelancer on platform)
    4. `Andrew R. - Professional Copywriter and Editor - Upwork` (Freelancer on platform)
    5. `Book a Development & IT Consultation with Andrew R. | Upwork` (Freelancer consultation)
    6. `Andrew Rabinovich - Upwork | LinkedIn`
  - *Defect:* Contaminated the executive profile with 5 unrelated freelance contractor profiles from the company's own product marketplace.
- **Case 2: Jon B (CEO at oneAI Consulting)**
  - *Actual Profile:* CEO at `oneAI Consulting` (`http://www.oneaiconsulting.com`).
  - *Scraped Sources attached:*
    1. `Jon B. - Principal, JMB Consulting Group LLC | LinkedIn` (Unrelated company)
    2. `B One Consulting – Strategy, Product, AI & Data` (Unrelated entity `boneconsulting.com`)
  - *Defect:* Search snippet matching on substring "B" and "Consulting" attached completely separate businesses as verified background facts.

### 3.3 Metric & Distribution Skew
- **Priority Distribution:**
  - Priority 0 ("Highest Fit"): **104 (72.2%)**
  - Priority 1 ("Medium Fit"): **40 (27.8%)**
  - Priority 2 ("Lowest Fit"): **0 (0.0%)**
  - *Issue:* Thresholds in `scoring.py` combined raw input keywords, email presence (+5), website presence (+5), and superficial title keywords, pushing nearly 3 out of 4 leads into Priority 0.
- **Research Status:**
  - Completed: **144 (100.0%)**
  - Partial: **0 (0.0%)**
  - Failed: **0 (0.0%)**
  - *Issue:* If *any* search snippet or HTTP request executed, the system flagged `research_status="completed"`, masking blocked sites, DNS failures, and unverified data.

### 3.4 Outreach & Cold Email Synthesis
In `research.py:335-339`:
```python
cta = (
    f"Would you be open to a 10-minute technical exchange next Tuesday to explore how "
    f"SealAPI shields AI and API endpoints for teams like {comp}?"
)
```
- **Defects:**
  - Hardcoded "next Tuesday" date in every single generated profile.
  - Value propositions do not cite source IDs.
  - Personalization is composed of template sentences rather than evidence-grounded icebreakers.

---

## 4. Architectural & Storage Issues

1. **Dual Mirroring (`LeadExporter`):**
   - In `src/lead_research/exporter.py:134-175`, batch artifacts are copied to both `self.output_base_dir.parent / "output"` (`data/output/`) and `Path("output")` (`output/`).
   - This duplication confuses consumers, bloats git, and obscures the real source of truth (`data/batches/`).
2. **Missing Canonical Layout:**
   - As specified in `fix.md`, runs should output to `data/output/batches/{batchID}/` with:
     - `manifest.json` (containing schema version, pipeline version, input sha256, breakdown counts)
     - `leads_input_snapshot.csv`
     - `lead_profiles.jsonl`
     - `leads_enriched.csv`
     - `outreach_ready.csv` (only strictly verified leads with valid channels & icebreakers)
     - `needs_review.csv` (leads with ambiguous identity, conflicts, or missing channels)
     - `sources.jsonl`
     - `claims.jsonl`
     - `errors.jsonl`
     - `summary.json`
     - `profiles/*.json`
     - `data/output/latest.json` (atomic pointer to latest completed batch)
3. **Resume Caching Flaw:**
   - In `pipeline.py:81-95`, caching matches solely on `lead.lead_id in existing_profiles`.
   - If scraper logic, prompts, schema version, or scoring rules change, stale or corrupted profiles are reused unconditionally.
4. **Security & SSRF:**
   - `fetch_url()` accepts any URL scheme without restricting private IP subnets (`127.0.0.0/8`, `10.0.0.0/8`, `192.168.0.0/16`, `172.16.0.0/12`, `169.254.169.254`).

---

## 5. Phase-by-Phase Remediation Plan

To fulfill the requirements of `fix.md`, the following implementation phases are scheduled:

- [x] **Phase A — Audit and Baseline:** Document existing state, failures, and dataset metrics (`docs/lead_research_audit.md`).
- [ ] **Phase B — Schema and Provenance:**
  - Implement versioned `LeadProfileV2`, `SourceEvidence` (with `source_id`, `evidence_quality`), `LeadClaim`, `ContactReadiness`, `Icebreaker`, and `ResearchMetadata`.
  - Maintain backwards-compatible fields/converters for V1 endpoints and frontend.
- [ ] **Phase C — Search, Fetch, Identity Resolution & SSRF Protection:**
  - Implement targeted search query generator (`build_queries`).
  - Separate candidate discovery from page fetching and evidence extraction.
  - Add SSRF blocking for localhost and private subnets.
  - Implement `identity_match_score()` with rejection of incompatible names, companies, and roles.
  - Fix test failure in `tests/test_scraper_mocked.py`.
- [ ] **Phase D — Research Synthesis & Icebreakers:**
  - Replace generic biography synthesis with claim-linked observations.
  - Implement icebreaker ranking and generation based on public signals (product launches, technical interviews, etc.).
  - Add validation preventing unsupported claims, removing hardcoded CTA dates, and marking insufficient evidence as `generic_fallback`.
- [ ] **Phase E — Scoring & Contact Readiness:**
  - Decouple Lead-Fit score (0-100), Verification Confidence (0.0-1.0), and Contact Readiness (`ready`, `ready_with_caveat`, `needs_research`, `not_ready`).
  - Provide human-readable, evidence-backed scoring explanations.
- [ ] **Phase F — Batch Storage, Fingerprinting & Resume:**
  - Implement `create_batch_id()` with UTC timestamp + random suffix.
  - Store runs in `data/output/batches/{batchID}/` with all required CSV/JSONL/JSON artifacts.
  - Implement `research_fingerprint()` to prevent stale resume cache reuse.
  - Atomically update `data/output/latest.json`.
- [ ] **Phase G — Frontend & API Integration:**
  - Update `server.py` and `src/lib/api.ts` to surface batch manifests, contact readiness, claim provenance, and icebreaker inspection.
  - Maintain compatibility with legacy batch view routes.
- [ ] **Phase H — Testing, Benchmarking & Dataset Migration:**
  - Implement unit and integration tests covering identity matching, SSRF filtering, claim verification, and batch isolation.
  - Reprocess the 144-lead dataset into a clean, new batch ID under `data/output/batches/`.
  - Benchmark quality metrics (correct-person precision, claim provenance coverage, outreach readiness).
