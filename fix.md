# LeadDetailsScraper — Final Residual Fixes, Security Hardening, and Verification

**Repository:** https://github.com/Patel-Menil/LeadDetailsScraper/  
**Branch:** `main`  
**Latest reviewed commit:** `4a84a2ed29708fdd032e99e95f0c381a8d2769c8`

## Objective

Implement the remaining fixes identified in the latest repository review. Focus on:

1. Claim-specific person, role, company, and domain verification.
2. Evidence-grounded personalization and truthful outreach readiness.
3. Complete authorization for sensitive API reads and exports.
4. Production authentication and Docker Compose configuration.
5. SSRF protection for browser redirects, subresources, and outbound requests.
6. Race-safe batch immutability and atomic finalization.
7. Regression tests proving each fix.
8. Consistency across profile data, exports, manifests, API responses, and frontend status displays.

**Do not rewrite the application from scratch. Implement the changes in the existing Next.js, FastAPI, Scrapling, and Docker architecture. Do not stop after producing an audit or plan.**

The latest CI passed, but important correctness and security gaps remain. Passing existing tests does not mean those gaps are resolved. Implement code-level corrections and tests that reproduce the identified failure modes.

---

# 1. Non-negotiable constraints

## 1.1 Preserve the historical review datasets

The files under `data/` were intentionally committed to make scraped results easier to inspect.

**Do not delete, untrack, rename, move, anonymize, rewrite, or regenerate existing files under `data/`. Do not change `.gitignore` rules that intentionally retain these review files.**

Also:

- Do not rewrite Git history.
- Do not reset the branch or discard unrelated work.
- Do not force-push.
- Do not run the entire real-lead dataset automatically.
- Do not change historical profile statuses merely to make them appear compatible with the latest code.
- Use synthetic identities and temporary output directories for automated tests.
- Do not expose real names, emails, or complete lead records in test logs.

A new validation run must use a separate temporary location or a newly created batch and must not overwrite the existing review artifacts.

## 1.2 Inspect before implementing

Read the current versions of the relevant source files, tests, deployment configuration, and frontend API routing. Do not assume the previous review or the instructions in this prompt perfectly describe every implementation detail.

Identify the actual execution paths first, then implement each fix where the security or correctness rule must be enforced. Use a consistent policy throughout the system, not just at one endpoint.

---

# 2. P0 — Fix claim-specific identity, role, company, and domain verification

**Primary file:** `src/lead_research/research.py`  
**Related files:** `src/lead_research/identity.py`, `src/lead_research/schemas.py`, `src/lead_research/scoring.py`

The current research logic still uses name occurrence, page-path keywords, page titles, and string matching to determine whether a person or job title has been verified. It also marks company and website claims verified after a successful fetch without adequately establishing the destination's identity.

## 2.1 Remove remaining verification shortcuts

Remove every rule that treats any of the following, by itself, as proof of identity or a current role:

- A person's name appearing anywhere in company-page text.
- A URL containing `/team`, `/leadership`, `/people`, `/about`, or related path segments.
- A page title containing a leadership-related keyword.
- A job-title substring appearing somewhere in an extracted page.
- A high candidate-match score.
- An exact search-result title or snippet.
- A successful HTTP response.
- A plausible LinkedIn URL or professional email format.

Do not replace one shortcut with a different score threshold.

Keep these concepts separate:

1. **Candidate match:** Whether the result is worth investigating.
2. **Person identity:** Whether inspected evidence supports that the source refers to the intended person.
3. **Employment relationship:** Whether the source establishes that the person works for the target organization.
4. **Current role:** Whether the evidence supports the particular role and its current relevance.
5. **Company/domain identity:** Whether the destination actually belongs to the named company.
6. **Contact verification:** Whether the particular contact field has been independently corroborated.

A high match score can prioritize a research candidate, but cannot replace independent verification.

## 2.2 Verify a person and role from actual evidence

Use the existing claim schema and statuses wherever possible, including `input_provided`, `unverified`, `partially_verified`, `verified`, `conflicting`, and `needs_review`, as supported by the models.

For each verified person-related claim, record supporting source IDs and enough source context to explain the decision.

A current-role claim must have source evidence that establishes the intended person's association with the specific role and employer. Prefer inspected official person-specific biographies, leadership/team profiles, or other reliable sources that directly support the claim.

Do not verify a role merely because the title exists on the page without an explicit relationship to the target individual.

A person can have a verified name but an unverified role. A verified company profile does not automatically verify its employees. Keep the statuses independent.

For an abbreviated name such as a first name followed by a last initial:

- Preserve the original imported value.
- Do not expand the name through guesswork.
- Require adequate evidence of the expanded identity and employer relationship.
- Otherwise mark it for review.

## 2.3 Verify company and domain independently

A successful fetch demonstrates reachability, not company identity.

Before marking the company or supplied website verified, inspect available page evidence such as:

- Company name and brand identity.
- Page title and relevant content.
- Domain consistency.
- Any redirect or host change.
- Whether the destination is plausibly an official company site rather than an unrelated or similarly named organization.

Do not automatically trust a redirected destination merely because it was reached from the imported URL. Record the original URL and final URL where supported and assess their relationship.

A company site may support company-level product and capability facts while providing no support for the target person's identity or role.

## 2.4 Validate claim provenance

Ensure each verified claim:

- References existing source IDs.
- Is supported by relevant evidence, rather than merely a source that exists.
- Has a status that matches the actual source content.
- Preserves conflicts and unresolved uncertainty.
- Does not treat `search_snippet` as independent proof of a person's current title.

When a source does not adequately establish a claim, keep the imported value available for review but do not promote its verification status.

Add appropriate validation so an unsupported verified claim is rejected or downgraded before it reaches profile output, scoring, or exports.

## 2.5 Required tests

Add mocked regression tests proving that:

- A company homepage mentioning a person in an acknowledgement does not verify current employment or title.
- A team page containing a name but not the person's supplied role does not verify that role.
- A generic leadership URL does not prove the individual's identity.
- A search snippet with the exact person, company, and title cannot independently verify the role.
- A similarly named individual is not attached to the target record.
- An abbreviated name is not expanded without adequate corroboration.
- An unrelated redirect destination cannot verify the original company.
- A verified claim with missing or irrelevant source evidence is rejected or downgraded.
- A genuinely corroborating person-specific source can satisfy the relevant verification gate.

Use synthetic data and mocked requests; do not depend on current external web pages.

---

# 3. P0 — Align icebreakers and outreach readiness with verified evidence

**Primary files:** `src/lead_research/icebreaker.py`, `src/lead_research/scoring.py`  
**Related files:** `src/lead_research/research.py`, schemas, exporter, frontend profile and dashboard components.

The current personalization and scoring functions still permit company signals and search snippets to produce overly confident messages. The readiness logic continues to accept field presence and plausible contact formats as evidence of usability.

## 3.1 Make the personalization source-aware

Separate signals into at least these categories:

- Company-level capability or positioning.
- Company-level product announcement.
- Person-specific professional background.
- Person-specific current role or work.
- Explicit hypothesis about a potential need.

A signal about the company cannot become a claim about the individual without evidence explicitly connecting the individual to it.

Do not state that the person led, built, announced, designed, or owns an initiative merely because the employer has that initiative.

## 3.2 Correct product-launch classification

A page URL containing `/news`, `/press`, `/announcements`, or `/releases` is not evidence that a launch occurred.

Require inspected source content that actually describes the event. Use dates only when the source supports them. Distinguish among:

- A genuine product launch or announcement.
- A general description of an existing capability.
- Static API or product documentation.
- Generic corporate marketing copy.

A general company page mentioning AI must not become a “recent launch” signal.

## 3.3 Correct biography and technical-work classification

Do not infer technical work from biography length or generic keywords alone.

Only generate a specific person-related signal when the source content supports that specific description and has passed the relevant identity checks.

Search snippets may help discovery but must not independently justify statements about verified work, technical leadership, or current responsibilities.

When evidence is missing or ambiguous, use a conservative generic fallback or mark personalization as `needs_review`.

## 3.4 Enforce truthful readiness gates

Implement a single, documented readiness policy that applies consistently to the backend, serialized profiles, CSV exports, manifests, and frontend.

At minimum, distinguish:

- Candidate fit.
- Person identity verification.
- Current-role verification.
- Company/domain verification.
- Contact-channel state.
- Evidence-backed personalization.
- Outstanding blockers.

Rules:

- Lead-fit score cannot compensate for unverified identity, company, or role.
- A missing claims list must not trigger a weaker verification fallback.
- A non-empty company name and URL must not automatically count as verified company context.
- An email containing `@` is not proof of deliverability.
- An imported LinkedIn URL is not proof of a valid contact channel.
- An unprobed email must remain `syntax_valid_unprobed`, not verified.
- A person-targeted icebreaker must not be marked ready when the required identity evidence is missing.
- `ready_with_caveat` must not silently be treated as fully ready.

Ensure fully ready exports contain only profiles that meet the full readiness policy. Profiles failing any required gate should have actionable blockers and appear in the appropriate review output.

Do not simply mark every lead not ready. Preserve useful prioritization while representing uncertainty honestly.

## 3.5 Required tests

Test:

- Company AI copy without a launch announcement.
- A news URL with no actual launch content.
- An API documentation page.
- A search snippet that describes technical leadership but has not been fetched or corroborated.
- Company-level signals that cannot be attributed to a person.
- A high-fit lead with an unverified role.
- A verified role with an unverified company.
- An unprobed email and a plausible but unverified LinkedIn URL.
- Missing claims or unsupported evidence.
- Readiness statuses and blockers across profiles, CSV exports, and dashboard counts.

All tests must use synthetic data.

---

# 4. P0 — Protect all sensitive API reads, exports, and mutations

**Primary file:** `src/lead_research/server.py`  
**Related files:** `src/middleware.ts`, `src/lib/api.ts`, `src/app/api/auth/`, Next.js route handlers, deployment configuration, `tests/test_api.py`

The latest commit adds production-mode authentication checks and login/session endpoints. However, many FastAPI read endpoints remain unauthenticated, including routes for listing batches, retrieving lead profiles, and downloading exports.

These routes can reveal the contents of uploaded lead files and research profiles.

## 4.1 Inventory every endpoint

Build an explicit inventory of every FastAPI route and any Next.js proxy or rewrite that reaches it.

For each endpoint, determine whether it is:

- Public and safe by design.
- Authenticated read access.
- Authenticated mutation.
- Administrative/destructive.
- Sensitive because it exposes uploaded or enriched contact data.

Do not rely on the route being called through the frontend. A client may call the backend directly if it is reachable.

Public routes should be restricted to the minimum necessary, such as an intentional health check that does not reveal secrets or sensitive operational information.

## 4.2 Protect sensitive read routes

Apply appropriate authorization to endpoints such as:

- Batch listing and details.
- Per-batch leads.
- Individual lead/profile retrieval.
- Latest batch details.
- Manifest and summary downloads.
- Prioritized and outreach-ready CSV downloads.
- Needs-review and error reports.
- Scraping logs.
- Profile JSON files and batch ZIP downloads.

Also protect uploads, batch starts and retries, deletions, clearing history, Tor management, and other operations that change state or initiate externally connected research.

The protection must apply to direct FastAPI access, not only to Next.js requests.

Use consistent authorization dependencies, a verified identity/session mechanism, and appropriate access policies. Do not create one weak path through a different endpoint or export handler.

Keep an explicit distinction between an authenticated operator and an administrator if the application supports those roles.

## 4.3 Do not treat a browser token as a secret

Inspect the current authentication design, especially:

- `src/app/api/auth/login/route.ts`
- `src/app/api/auth/logout/route.ts`
- `src/app/api/auth/status/route.ts`
- `src/middleware.ts`
- `src/lib/api.ts`
- FastAPI's `verify_api_key()`

The current design stores the raw backend API secret in the `sealapi_session` cookie and checks that cookie against the backend secret. `HttpOnly` prevents ordinary client-side JavaScript from reading the cookie, but it does not convert the raw shared secret into a properly scoped session.

Implement a safer, coherent arrangement:

- Keep backend secrets server-only.
- Use an authenticated session that is separate from the raw backend API secret, such as a properly signed session token with expiration.
- Use appropriate cookie properties: `HttpOnly`, `SameSite`, and `Secure` in production.
- Validate authentication and authorization on every protected operation.
- Add CSRF protections for cookie-authenticated state-changing requests as appropriate.
- Invalidate sessions on logout and expiration.
- Handle invalid sessions without leaking credentials.
- Ensure direct backend access is independently protected.
- Do not add a public, unauthenticated proxy to work around the backend authentication.
- Do not treat CORS as authentication.

Use the existing session architecture if it can be safely corrected. Avoid introducing duplicate authentication systems unnecessarily.

## 4.4 Correct production and Docker configuration

`Dockerfile` sets `NODE_ENV=production`, while `docker-compose.yml` does not pass `API_SECRET_KEY`. The backend can therefore fail closed with an unset key, which is correct from a security perspective but leaves the normal container deployment improperly configured.

Implement a complete, documented configuration:

- Require production secrets explicitly.
- Pass them through an appropriate environment or secret mechanism.
- Never bake credentials into the image or commit them to the repository.
- Ensure the Next.js server and FastAPI backend use a compatible auth configuration.
- Make missing production configuration produce a clear, safe error or startup failure.
- Keep permissive development behavior explicitly restricted to local development.
- Ensure a missing variable cannot accidentally activate a production bypass.
- Document required environment variables and how an operator configures them.

Do not weaken production authentication simply to make the container start.

## 4.5 Required API tests

Test every important route category:

- Missing credentials.
- Invalid credentials.
- Valid authenticated request.
- Expired or invalid session.
- Unauthorized reads of contact data and profile exports.
- Unauthorized mutations, batch starts, deletion, clear-history and Tor management.
- Direct backend requests bypassing the frontend.
- A same-origin proxy request without a valid session.
- CSRF protections where relevant.
- Production deployment with required secrets missing.
- Valid authentication and UI workflows.
- Health-check behavior without sensitive disclosures.
- No server API secret shipped in browser bundles or exposed through an API response.

Use mock secrets only. Do not include secret material in logs or test output.

---

# 5. P0 — Close SSRF gaps in browser fetching and outbound requests

**Primary file:** `src/lead_research/scraper.py`  
**Related files:** scraper tests, browser/proxy configuration, Docker networking.

The latest code validates redirects in the direct HTTP fetcher. However, the browser fallback still uses `StealthyFetcher.fetch()` without demonstrated enforcement of the same destination policy for redirects and subresources. Requiring a configured proxy is not sufficient unless that proxy actually enforces destination safety.

## 5.1 Define one mandatory outbound-request policy

Every supported fetching path must apply the same security rules:

- HTTP/HTTPS only.
- No embedded URL credentials.
- Block loopback, private, link-local, unspecified, reserved, multicast, and other non-public destinations not explicitly permitted.
- Handle IPv4, IPv6, IPv4-mapped IPv6, unusual IP encodings, invalid URLs, and disallowed internal hostnames.
- Validate DNS resolutions before connecting.
- Reject hostnames that resolve to a disallowed address.
- Limit connection/read time, redirects, retries, and response size.
- Log only sanitized diagnostics.

Do not rely on a successful initial URL check for subsequent browser or redirect requests.

## 5.2 Validate redirects before the connection

For direct HTTP requests:

- Disable automatic redirects.
- Resolve each `Location` against the current URL.
- Validate the new URL and its destination before making the next request.
- Validate the destination again when the hostname changes.
- Reject redirect loops and excessive redirects.
- Confirm in tests that blocked destinations were never requested.

For hostnames that resolve to multiple addresses, reject the destination if any address violates the configured policy unless the transport provides a stronger, demonstrably safe destination-pinning approach.

## 5.3 Secure browser and proxy paths

Review the actual Scrapling/StealthyFetcher capabilities and the installed versions.

Determine how to enforce policy before the network request for:

- Top-level page navigation.
- Redirect destinations.
- Subresource requests.
- Popups/new pages.
- Client-triggered navigation and requests.
- WebSockets and other outbound mechanisms if supported.

If reliable pre-request interception is available, implement it and test it.

If not, use a validating egress proxy or equivalent network boundary that demonstrably blocks unsafe destinations at connection time. The existing Tor proxy must not be assumed to provide this guarantee.

If the current stack cannot enforce the required policy, disable the unsafe browser fallback for production research and document the limitation. Do not claim full SSRF protection based solely on checking the initial URL.

Address DNS rebinding and the validation-versus-connection time-of-check/time-of-use gap. Use transport or egress controls that prevent a re-resolution from reaching an unapproved destination. Do not disable TLS certificate verification as a workaround.

Apply the same rule to all enabled HTTP, browser, Tor, and proxy execution modes.

## 5.4 Required SSRF tests

Using mocks, controlled local test doubles, or an intentionally restricted test egress environment, verify:

- Private and public IPv4/IPv6 handling.
- IPv4-mapped IPv6 and unspecified addresses.
- Invalid URLs and disallowed schemes.
- Internal hostnames.
- DNS responses containing a private destination.
- DNS failures.
- Unsafe redirects rejected before the next request.
- Redirect loops and redirect limits.
- Browser redirect and subresource policy enforcement.
- Proxy/Tor paths do not bypass the policy.
- Permitted public pages still work through every production-enabled fetch mode.
- Any unsupported browser path is demonstrably disabled or restricted.

Do not make real requests to cloud metadata endpoints or internal services.

---

# 6. P1 — Make finalized batches genuinely immutable

**Primary files:** `src/lead_research/exporter.py`, `src/lead_research/pipeline.py`, `src/lead_research/server.py`

The exporter now refuses to overwrite manifests marked `completed` or `finalized` by default. The remaining work is to make this enforcement atomic and cover other existing batch states.

## 6.1 Create an explicit batch lifecycle

Define states and legal transitions, for example:

- `pending`
- `processing`
- `completed`
- `partial`
- `failed`
- `finalized`

Choose states compatible with the current application, and document exactly when a batch becomes immutable.

Ensure that every new run has a unique batch/attempt identity.

If resume support is retained:

- Resume only genuinely incomplete work.
- Do not silently mutate finalized outputs.
- Preserve the prior input snapshot, evidence, profiles, exports, and manifest.
- Use a distinct attempt/revision identity when prior results must be preserved.

If safe resumption cannot be guaranteed, reject it with an actionable error and require a new batch.

## 6.2 Enforce immutability in the exporter itself

Do not rely solely on the API endpoint or in-memory status.

Implement a safe finalization design:

- Reserve the batch identifier atomically.
- Prevent two concurrent runs from reserving the same ID.
- Reject writes to an existing finalized directory regardless of whether its status is `completed`, `partial`, `failed`, or some other persisted state that should be immutable.
- If a partial batch is explicitly resumable, use the documented attempt policy rather than silently reusing it.
- Write outputs to an isolated staging directory.
- Validate required outputs and internal counts.
- Publish finalized results atomically where supported.
- Ensure a failed write never publishes an incomplete finalized manifest.
- Update latest-batch pointers only after successful finalization.
- Ensure concurrent writers cannot overwrite each other's files.

Distinguish a manifest that does not exist from a corrupted, unreadable, or inconsistent manifest. Do not silently treat an unreadable manifest as permission to overwrite an existing batch directory.

## 6.3 Required batch tests

Test:

1. A new batch succeeds.
2. A finalized batch cannot be overwritten.
3. Existing failed/partial states follow an explicit policy.
4. Resume uses the documented mechanism.
5. Two concurrent start requests cannot reserve the same batch.
6. Two concurrent exporters cannot overwrite one another.
7. Failed staging/finalization does not replace the latest pointer.
8. A new latest pointer references only a finalized valid batch.
9. Output counts, profile counts, summary and manifest agree.
10. Existing historical `data/` files remain unchanged.

Use temporary directories and synthetic profiles.

---

# 7. P1 — Fix cache configuration and data consistency

Inspect `src/lead_research/fingerprint.py` and `src/lead_research/pipeline.py`, along with schema loading, exporter serialization, and UI models.

The latest pipeline now includes more cache configuration and version identifiers, which is a good improvement. Complete the implementation by making it reflect actual effective research behavior.

Ensure the deterministic fingerprint covers all relevant inputs and settings, including:

- Canonical person/company/contact fields.
- Research sources and transport modes.
- Browser/Tor/proxy-enabled mode without secrets.
- Extraction, identity, role-verification, scoring, and personalization policy versions.
- Profile schema and pipeline version.

Use one centrally defined effective configuration so the version passed to the fingerprint matches the code that actually runs.

A cache entry must be reused only when its fingerprint, schema, and pipeline compatibility are established. Preserve incompatible historical profiles instead of relabeling them.

Also ensure:

- Profile schema versions agree with profile metadata.
- Claim/source references remain valid when serialized and reloaded.
- CSV readiness, JSON profiles, summaries, and manifests use the same policy.
- Historical output pointers are not silently updated by tests or migration code.

Add tests for field-by-field invalidation, effective configuration changes, secret exclusion, legacy-profile handling, and output consistency.

---

# 8. Data preservation and validation-run requirements

**Do not modify any existing file under `data/` during implementation or tests.**

After the fixes and regression tests are complete, validate the new code with:

1. Synthetic end-to-end leads.
2. A temporary output directory.
3. A distinct new test batch.
4. Inspection of the resulting claims, evidence, readiness blockers, and exports.

Do not automatically rerun the real lead dataset. Do not modify `data/output/latest.json`, `data/output/manifest.json`, historical profiles, historical CSVs, or stored scraped files as part of this task.

When the application is explicitly run by the operator later, it can create a separate real-data batch through the normal workflow.

---

# 9. CI and regression-test requirements

Review and extend the current test suite, including:

- `tests/test_api.py`
- `tests/test_scraper_mocked.py`
- `tests/test_exporter.py`
- `tests/test_scoring.py`
- `tests/test_identity.py`
- `tests/test_v2_pipeline.py`
- Existing frontend logic and UI tests.

Add tests next to the code responsible for each defect. The tests must reproduce the actual unsafe or incorrect behavior, not just check for the presence of a helper.

Run the existing commands as defined by `package.json` and `.github/workflows/ci.yml`:

1. Targeted Python tests.
2. Full backend pytest suite.
3. Frontend unit tests.
4. TypeScript typecheck.
5. Next.js production build.
6. Any relevant added integration/security tests.

Investigate failures caused by the changes. Do not weaken, skip, or delete existing tests simply to get a passing build. Report exact commands and results. Mark any test that could not run as unexecuted rather than passed.

---

# 10. Definition of done

The task is complete only when all of the following are demonstrated by code and tests:

### Verification and outreach
- A homepage mention does not independently verify identity or role.
- A title substring and leadership-related URL cannot independently verify a current role.
- Company/domain verification is independent of a successful fetch.
- Company-level facts are not falsely attributed to an individual.
- Unsupported launch and technical-leadership signals cannot create a ready icebreaker.
- Readiness is determined by explicit verified-claim gates.
- Exports and the frontend agree with backend readiness.

### Authorization
- Sensitive read endpoints and exports are protected.
- Mutations and administrative operations are protected.
- Direct backend access is secured, not only the frontend route.
- The browser does not receive a server-side shared API secret.
- Sessions have appropriate expiration and secure cookie handling.
- The production Docker configuration works with required secrets supplied and refuses unsafe implicit bypasses.
- Valid authenticated UI workflows remain functional.

### SSRF
- All enabled fetching paths follow the same URL/destination policy.
- Unsafe redirects are blocked before the destination request.
- Browser navigation and subresource requests cannot bypass the policy.
- DNS rebinding risks are addressed by enforceable transport/egress controls, or unsafe paths are disabled.
- Any unfulfilled network-security guarantee is documented precisely.

### Batch integrity
- Finalized batches cannot be overwritten through the API or direct exporter use.
- Concurrent execution/export cannot silently write into the same batch.
- Failed finalization cannot promote incomplete outputs.
- Latest pointers reference a valid finalized batch.

### Validation and preservation
- New regression tests pass.
- Existing backend/frontend checks pass.
- Historical review files and tracking rules remain untouched.
- No full real-data run was triggered automatically.
- The final report is supported by actual code and test evidence.

---

# 11. Final implementation report

After implementation, report:

1. **Summary:** What was fixed.
2. **Changed files:** Each file and its purpose.
3. **Before/after behavior:** The exact failure path and correction.
4. **Regression tests:** Which tests cover each residual issue.
5. **Command results:** Exact test/build commands and pass/fail/unexecuted status.
6. **Security limitations:** Especially browser SSRF, DNS rebinding, session security, and direct backend access.
7. **Deployment configuration:** Required environment variables and Docker instructions.
8. **Data preservation:** Confirmation that no existing `data/` artifacts or `.gitignore` rules were changed.
9. **Remaining issues:** Anything not fixed and why.

Do not claim that production readiness has been achieved just because CI is green. Do not claim a security guarantee without an actual enforcement mechanism and appropriate regression tests.

**Implement the changes now. Do not return only a plan, and do not ask for confirmation.**