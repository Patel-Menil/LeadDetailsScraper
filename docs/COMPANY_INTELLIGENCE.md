# Company Intelligence (Company Details tab)

Researches the company behind each lead, identifies its products, records quoted evidence, derives
**potential** security gaps, maps them to **verified** SealAPI capabilities, classifies product fit and
feeds the strongest verified insight into outreach drafts. It extends the existing pipeline; lead
profiles, scores, CSVs and existing exports are unchanged.

## Where it lives

| Piece | File |
| --- | --- |
| Research engine, analysis, outreach, exports, storage | `src/lead_research/company_intel.py` |
| Verified SealAPI capability registry | `src/lead_research/sealapi_capabilities.py` |
| API endpoints | `src/lead_research/server.py` (section "Company intelligence") |
| Company Details tab + company-informed outreach card | `src/components/CompanyDetails.tsx` |
| Tab order and research-state helpers | `src/lib/companyIntel.mjs` |
| Tests | `tests/test_company_intel.py`, `tests/company_details.test.mjs` |

## How research works

1. **Company key**: the normalized official domain (company record, then lead website, then a non-free
   work-email domain). Leads sharing a domain share one company record. Without a domain the company
   is `needs_review` and nothing is fetched until a domain is set in the tab (`PUT /api/companies/{id}/domain`).
2. **Fetching** (provider `official_site`): pages on the company domain and its subdomains only, through the
   existing SSRF-checked, IP-pinned `fetch_url` (direct, never through Tor). `robots.txt` is honoured
   (4xx = no restrictions; unreachable = disallow-all), 1 request/second per domain, up to 3 attempts with
   exponential backoff on 429/5xx, no CAPTCHA or login bypass.
3. **Page selection**: homepage, then links categorised as products, developer/docs, integrations,
   security/trust, AI, careers, news and about (budget `COMPANY_RESEARCH_MAX_PAGES`). Product links
   (`/products/<name>` etc.) become product records; if none exist the company-level offering is
   analysed and labelled as such.
4. **Findings**: each is one sentence quoted from an official page, with source URL, domain, publication
   date (when the page states one), access time, confidence and review status (`unreviewed` by default).
   Page text is untrusted data and is only pattern-matched, never executed or used as instructions.
5. **Persistence**: progress is saved after every page; successful pages are cached for 24 hours, so a
   retry resumes from the cache and `Refresh` re-fetches. Manual review decisions survive refreshes.

The provider is pluggable (`ResearchProvider` protocol: `fetch(url) -> ScrapeResult`). Adding a search
or news API provider means implementing that protocol and reading its key from an environment variable.

## Analysis rules

- **Gaps** are always `classification: potential_risk`, `verified_vulnerability: false`, each with
  documented context, scenario, consequence, existing documented controls, controls that could not be
  verified, information needed and a validation question.
- **SealAPI mapping** only uses capabilities whose registry status is `implemented`. Company-owned APIs
  and non-AI integrations are reported as **not currently supported** (SealAPI fronts application-to-AI
  traffic only).
- **Fit**: Strong (AI documented + a named provider with a SealAPI adapter), Validation required (AI
  documented, provider/path unknown), Weak (APIs/integrations but no AI), Not currently suitable, or
  Insufficient evidence (failed or fewer than two pages).
- **Product score** (0–100): weighted factors shown in the UI (API, integration and AI evidence, problem
  relevance, capability compatibility, evidence quality) minus an uncertainty penalty for undocumented
  architecture. Industry is not a factor. Override weights with `COMPANY_FIT_WEIGHTS`.
- **Outreach**: Variant A (evidence-led, quotes an official page) and Variant B (problem-led), around
  100–160 words, one question, with a guardrail that flags vulnerability, incident, guarantee,
  certification, customer and hardware-TEE claims. Without an in-scope opportunity a conservative draft is
  produced. Nothing is ever sent.

## Verified SealAPI capabilities (checked in `C:\sealapi\sealapi`, commit `9bfc019`)

| Capability | Status | Evidence |
| --- | --- | --- |
| AI provider credential shielding (BYOK) | implemented | `crates/sealapi-gateway/src/byok.rs`, `crates/sealapi-security/src/vault.rs` |
| Per-service keys with model allowlists | implemented | `crates/sealapi-security/src/api_keys.rs`, `crates/sealapi-usage` |
| Per-key rate limiting | implemented | `crates/sealapi-security/src/rate_limit.rs` |
| Misuse detection + automatic key pause | implemented | `circuit_breaker.rs`, `services/chainguard-api` |
| Fail-closed pre-dispatch security gate | implemented | `crates/sealapi-gateway/src/security_gate.rs` |
| Sealed request payloads (SDKs) | implemented | `docs/wire-format.md`, `sdks/` |
| MCP tool policy + single-use permits | implemented | `crates/sealapi-mcp-kernel`, `mcp_permit.rs` |
| Hardware TEE attestation | partial | live Azure DCasv5 gate still open |
| Prompt content inspection (PII, injection) | not supported | ChainGuard is metadata-only by design |
| Protecting a company's own APIs / non-AI integrations | not supported | SealAPI is an app-to-AI gateway |

"Implemented" means code and unit tests exist in the SealAPI repository; they were not executed as
part of this feature. Provider adapters are locally contract-verified only (0 live-verified providers),
so every compatibility result says "pending validation".

## API

All endpoints use the existing `verify_api_key` dependency (session cookie via the Next.js proxy, or
`X-API-Key`).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/leads/{lead_id}/company?batch_id=` | Company view for a lead (`not_researched` if none) |
| POST | `/api/leads/{lead_id}/company/research?batch_id=` | Start / refresh (`{"refresh": true}`) / retry; 409 if running |
| GET | `/api/leads/{lead_id}/company/outreach?batch_id=` | Company-informed drafts |
| GET | `/api/companies/{company_id}` | Company record |
| POST | `/api/companies/{company_id}/research` | Same as the lead route |
| PUT | `/api/companies/{company_id}/domain` | Manual domain correction |
| POST | `/api/companies/{company_id}/findings/{finding_id}` | `{"status": "verified" \| "rejected" \| "needs_review" \| "unreviewed"}` |
| POST | `/api/companies/{company_id}/analyze` | Regenerate opportunity analysis (no re-fetch) |
| POST | `/api/batches/{batch_id}/companies/research` | Research every distinct company in a batch |
| GET | `/api/batches/{batch_id}/companies` | Batch company list and job progress |
| GET | `/api/batches/{batch_id}/exports/company_intelligence.csv` / `.json` | Exports (also added to the batch ZIP) |
| GET | `/api/sealapi/capabilities` | Capability registry |

## Storage

`data/output/companies/` (inside the existing `DATA_DIR` volume):
`co_<hash>.json` per company, `page_cache/co_<hash>.json` (24-hour page cache) and `lead_index.json`
(lead -> company). Exports contain lead IDs, names and titles but no email addresses, tokens or keys.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `COMPANY_RESEARCH_MAX_PAGES` | 14 | Pages per company, including the homepage and product pages |
| `COMPANY_RESEARCH_MAX_PRODUCTS` | 4 | Product pages per company |
| `COMPANY_RESEARCH_REQUEST_DELAY` | 1.0 | Seconds between requests to one domain |
| `COMPANY_RESEARCH_CONCURRENCY` | 2 | Companies researched in parallel for a batch |
| `COMPANY_FIT_WEIGHTS` | (empty) | JSON object overriding scoring weights |

No research-provider API keys are needed for the default provider.

## Known limitations

- Pattern-based extraction: findings are accurate quotes but can be imperfectly categorised; review them.
- JavaScript-only sites render little text without a browser, and browser fetching is deliberately not
  used here because it cannot honour connection-level IP pinning.
- Job state is in-process: a job interrupted by a restart is reported as failed and can be retried.
- Products are discovered from homepage navigation; products only reachable deeper are missed.
