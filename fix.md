# LeadDetailsScraper — Residual Critical Fixes and Production Hardening

**Repository:** `https://github.com/Patel-Menil/LeadDetailsScraper/`  
**Branch:** `main`  
**Starting commit to inspect:** `46433aae92ce50b53132c275d4382f8b56f4a8a2`  
**Primary objective:** Fix the remaining identity-verification, company verification, evidence-grounding, API authorization, browser SSRF, cache invalidation, and batch-immutability defects in the existing implementation.

This is an implementation task. Inspect the current repository, modify the actual code, add regression tests, run the tests, and report verified results. Do not stop after producing an audit, plan, or list of recommendations.

The previous implementation added meaningful safeguards, and the current GitHub Actions CI passes. However, tests passing does not establish that the research claims are correct or that the production security boundaries are effective. Fix the specific failure modes below and demonstrate the fixes with targeted tests.

## 1. Non-negotiable constraints

### Preserve all existing review data

The files under `data/` were intentionally committed so that the scraped results can be inspected and reviewed.

**Do not delete, untrack, rename, relocate, anonymize, or rewrite any existing files under `data/`. Do not change `.gitignore` rules that intentionally retain this data. Do not rewrite Git history, force-push, or reset the branch.**

Preserve the existing application architecture, useful functionality, frontend workflows, API contracts wherever compatible with the security requirements, and historical research artifacts.

Do not automatically run the full real-lead dataset through the modified research pipeline. Use synthetic fixtures and temporary output directories for tests. Do not print real contact details or full lead records into CI logs.

Do not modify historical output files just to make their schema or manifest appear current. Any new validation run must produce a separate batch in a temporary directory or a new explicitly created batch.

### Working method

1. Fetch and inspect the current branch and working tree.
2. Read the current code, tests, configuration, and the previous implementation commit.
3. Map each defect below to the actual functions responsible for it.
4. Implement the fix in the existing architecture.
5. Add a regression test that fails against the current defective behavior.
6. Run targeted tests, then the full backend and frontend CI checks.
7. Review the final diff for unintended changes to tracked data, secrets, configuration, or unrelated features.

Do not discard unrelated working-tree changes. Do not claim a safeguard works merely because the code contains a corresponding helper function.

---

# 2. P0 — Eliminate false person-identity verification

**Primary file:** `src/lead_research/research.py`  
**Related files:** `src/lead_research/identity.py`, `src/lead_research/schemas.py`, `src/lead_research/scoring.py`

## 2.1 Remove the remaining identity-confidence shortcut

The current research flow contains logic equivalent to:

- Fetch the company's homepage.
- Check whether the person's name appears somewhere in the extracted text.
- If the name appears, set `company_mentions_person`.
- Raise `max_identity_score` to a high value such as `0.85`.

This is an invalid identity-verification shortcut. A name can appear in an acknowledgement, customer testimonial, article, old announcement, footer, unrelated list, or other context that does not establish employment or the person's current role.

Remove this shortcut completely.

A homepage mention must not independently:

- Verify the person's identity.
- Verify the person's employer.
- Verify their current job title.
- Raise a candidate-ranking score into a verified-identity state.
- Enable person-specific icebreaker generation.
- Make the contact outreach-ready.

Keep the actual evidence and its interpretation separate. Do not replace the removed shortcut with another threshold-based shortcut.

## 2.2 Separate three different concepts

Implement and enforce three separate values or concepts throughout the pipeline:

1. **Candidate-match score:** How promising a discovered search result appears and whether it should be inspected further.
2. **Verified-identity state:** Whether appropriate inspected evidence corroborates the specific person and employer.
3. **Claim-level verification:** Whether the evidence supports a particular field, such as current job title, company, or professional email.

These must not be interchangeable.

`identity_match_score()` may continue to rank search candidates using name, company, title, and URL signals. However, its numerical result alone must never establish a verified identity.

Only eligible evidence from an inspected destination page, or another explicitly supported reliable source, may establish identity verification. Search snippets may guide discovery, but they must not independently create verified person claims.

A high candidate-match score must not override absent evidence, identity conflicts, abbreviated-name ambiguity, or a source that does not support the proposed claim.

## 2.3 Verify each person-related claim separately

Implement a clear verification policy for at least:

- Person name.
- Current job title.
- Employer/company association.
- Company identity and official website/domain.
- Professional email.
- LinkedIn or other professional profile.

Use the existing schema and statuses wherever possible. Preserve the distinction among `input_provided`, `unverified`, `partially_verified`, `verified`, `conflicting`, and `needs_review`, depending on the statuses the current models support.

### Name verification

A company page that mentions a name is not sufficient by itself to establish that the target lead is the person described in the imported record.

Use context that establishes the person's identity and, where necessary, their relationship to the target organization. An ambiguous name should remain in review.

Do not expand an abbreviated name such as a first name plus last initial unless reliable evidence corroborates the expansion and the employer association.

### Current-role verification

Do not verify a title merely because:

- The title appears somewhere on the page.
- The page title contains a generic term such as `team`, `about`, or `leadership`.
- The URL contains `/team`, `/about`, `/people`, or similar text.
- The search result has the exact name, employer, and title.
- A company homepage mentions both the person's name and the title without connecting them.
- A fetched page returned HTTP 200.

A current job title must be supported by evidence that actually connects the intended person to the specific role and employer.

Prefer a directly relevant official leadership biography, team profile, or other reliable person-specific source. Check whether the name, role, employer, and page context support the claim. Do not treat substring overlap as an adequate relationship check.

If evidence establishes the person's name but not the current role, verify only what the evidence supports and leave the role unresolved.

### Company verification

A successful request only demonstrates reachability. It does not establish that the fetched domain belongs to the supplied company.

Check the actual page content, title, brand identity, and available domain context. A similar-looking hostname alone is not sufficient proof.

If the supplied company website redirects to a different host, retain the original URL, record the final fetched URL, and assess whether the destination is a legitimate company site. Do not automatically verify the supplied company based on an unrelated redirect destination.

A company page can support facts about company products or capabilities without supporting the identity or job title of any particular person.

### Email and profile verification

Do not mark an email or LinkedIn profile verified just because the imported value looks syntactically correct or the URL matches a familiar pattern.

Do not claim email deliverability unless an actual permitted verification mechanism established it. If no deliverability probe occurs, retain the existing `syntax_valid_unprobed` distinction.

## 2.4 Enforce source provenance

Every verified claim must have traceable supporting evidence.

Use existing models where possible to retain:

- Source ID.
- Source URL and final URL when relevant.
- Source type.
- Retrieval time and available page metadata.
- Relevant excerpt or extracted facts.
- Evidence quality.
- Verification status and explanation.

Enforce consistency in code:

- A claim cannot reference a nonexistent source.
- A source ID cannot be treated as sufficient evidence merely because it exists.
- A `search_snippet` source cannot independently satisfy a verified person or current-role claim.
- A generic `official_company` source is not automatically eligible for every claim.
- Verification must match the claim's meaning, not merely the source type.
- If source content conflicts with the imported field, preserve the disagreement and mark the claim for review rather than silently choosing whichever value improves the score.

Do not fabricate missing metadata or supporting excerpts.

## 2.5 Required identity regression tests

Add or update tests that demonstrate all of the following:

1. A company homepage fetch alone does not verify a person.
2. A homepage containing the intended person's name in an acknowledgement does not verify current employment.
3. A page mentioning the person's name and an unrelated title does not verify the imported role.
4. A URL containing `/leadership` but lacking relevant person-role content does not verify the role.
5. A search result with an exact name, job title, and company does not verify the current role unless eligible destination-page evidence is inspected.
6. A name collision with a different individual is rejected or marked ambiguous.
7. An abbreviated name is not expanded without adequate corroboration.
8. A redirected unrelated website does not verify the supplied company.
9. A verified claim with a missing or invalid source reference is rejected or downgraded.
10. A genuinely corroborating, directly relevant official person profile can pass the verification gate.

Use mocked sources; do not depend on live external websites.

---

# 3. P0 — Make personalization evidence-grounded

**Primary file:** `src/lead_research/icebreaker.py`  
**Related files:** `src/lead_research/research.py`, `src/lead_research/identity.py`, `src/lead_research/schemas.py`

## 3.1 Separate company signals from person-specific signals

The current pipeline can create public signals from broad company-page content and search snippets. These signals may be marked `verified`, after which a ready icebreaker can be generated if the identity-confidence threshold is met.

The identity shortcut described in Section 2 must be removed. Additionally, ensure that company context never becomes person-specific evidence by implication.

Maintain a clear distinction between:

- A fact about the company.
- A fact about the individual.
- A fact about the person's current role.
- A hypothesis about a potential security or infrastructure need.

A company's API platform does not prove that the person personally built it. A company AI announcement does not prove that the person led the launch. A keyword in a search result does not establish that the person owns a technical initiative.

Do not personalize using unverified claims of the person's technical leadership, projects, announcements, responsibilities, or career history.

## 3.2 Tighten product-launch classification

The current launch classifier can use launch-related terms and URL paths such as `/news`, `/press`, `/announcements`, or `/releases`.

A URL path alone is not evidence that an actual product launch occurred.

Implement the following:

- Require inspected source content that substantively describes a real announcement or launch.
- Prefer an actual announcement headline and relevant page content.
- Use a publication or event date only when supported by the source.
- Distinguish a dated product launch from general company positioning, capability descriptions, or static product documentation.
- Do not infer a launch merely because the page contains an AI keyword alongside a launch-related keyword.
- Do not invent recency, launch dates, or event details.

If the evidence establishes that a company offers an AI capability but not that it recently launched one, classify the signal as a capability or company-positioning signal, not a launch.

## 3.3 Tighten professional-background and technical-work signals

Do not convert every sufficiently long biography or search snippet into a partially verified professional-background or technical-work signal.

A few broad keywords such as `engineering`, `platform`, `security`, or `architect` are not enough to establish a person's actual responsibilities.

Require contextual evidence that genuinely supports the proposed description. Keep discovery snippets distinct from inspected page excerpts.

If the source cannot support a sufficiently specific statement, either:

- Use a conservative generic company-level observation, clearly supported by the page; or
- Return `needs_review` or the existing generic fallback.

Do not mark an evidence-grounding failure as `ready` just to generate a usable message.

## 3.4 Make readiness and wording agree

The icebreaker wording must not be more specific than its evidence.

Examples of prohibited behavior include:

- Saying that someone leads an initiative when the source only describes company capabilities.
- Claiming to have read public coverage of an individual's technical leadership when only a search snippet exists.
- Claiming that a company recently launched a product because a static page contains AI keywords.
- Describing a project as the person's work without evidence connecting the person to it.
- Implying an internal vulnerability, security incident, or customer problem that the source does not establish.

A hypothesis about a possible infrastructure or security challenge can remain a clearly labeled hypothesis; do not state it as an established problem at the target company.

A person-targeted icebreaker must not be `ready` unless the necessary identity and evidence gates are satisfied. Ensure that `source_ids` refer to the actual sources supporting the selected signal.

## 3.5 Required personalization regression tests

Add tests for:

1. A `/news` or `/press` URL with no launch content.
2. Generic homepage copy containing AI-related terminology.
3. An API documentation page that does not describe a product launch.
4. A search snippet containing technical keywords but no fetched destination page.
5. A company announcement where no evidence ties the person to the announcement.
6. A non-technical biography that must not be classified as technical leadership.
7. An actual launch announcement supported by the fetched page content.
8. A real, inspected company-level capability source that supports a company-level icebreaker.
9. Missing or conflicting identity evidence that prevents person-specific personalization from becoming ready.
10. Any `ready` icebreaker whose supporting source IDs are missing, invalid, or inappropriate for the claim.

---

# 4. P0 — Enforce strict and auditable outreach-readiness gates

**Primary file:** `src/lead_research/scoring.py`  
**Related files:** `src/lead_research/research.py`, `src/lead_research/schemas.py`, `src/lead_research/exporter.py`, frontend types and readiness UI

The current code has improved role verification, but contact usability and company context can still be derived from mere field presence. A syntactically valid email or plausible profile URL is not automatically an independently verified contact channel.

## 4.1 Create one explicit readiness policy

Review the entire readiness path, from research claims through scoring, profile serialization, CSV export, API response, and frontend display.

Define and document a single policy for `ready`, `ready_with_caveat`, `needs_research`, and `not_ready`, using the existing schema where practical.

At minimum, distinguish:

- Candidate fit score.
- Person identity verification.
- Current-role verification.
- Company and domain verification.
- Contact-channel usability and verification.
- Personalization evidence quality.
- Unresolved conflicts and blockers.

A high fit score must never compensate for an unverified identity, unverified current role, or unsupported company association.

## 4.2 Derive readiness from the actual claims

`has_verified_role` must be derived from a verified current-role claim with appropriate evidence. It must not be derived from a non-empty job-title field or a role score.

Similarly:

- `has_company_context` must not equate to the presence of a company name and URL.
- `has_usable_contact_channel` must not equate to an email string containing `@` or a LinkedIn URL containing `/in/`.
- `has_evidence_based_icebreaker` must reflect source-grounded evidence, not merely non-empty text.
- A status labelled verified must be backed by a claim and eligible evidence.
- A claim-level conflict must not be erased by the aggregate identity score.

If legacy compatibility paths remain, ensure they cannot bypass these gates. Do not use a weaker verification fallback merely because the `claims` list is empty. Missing verification data should trigger a conservative review state.

## 4.3 Define contact-channel outcomes truthfully

Keep email syntax, deliverability, identity association, and outreach permission distinct.

- `syntax_valid_unprobed` must not be described as delivered, deliverable, or verified.
- Do not promote an imported email to verified without a real supported check.
- Do not mark a profile URL verified because of URL structure alone.
- Where no channel has enough evidence to be considered usable under the defined policy, set an appropriate non-ready state.
- If an unprobed email is the only available contact method, do not put the record into the fully `ready` outreach export.
- `ready_with_caveat` must be explained accurately and must not silently become equivalent to `ready` in exports or frontend summaries.

If a supported independent channel is usable while email remains unprobed, represent that distinction accurately. Do not make the record globally unusable solely because one optional channel lacks verification if another supported channel genuinely satisfies the policy.

## 4.4 Ensure all surfaces agree

Verify that:

- `contact_readiness.status` and `contact_readiness.blockers` agree.
- Scoring explanations do not claim a role is verified when it is not.
- Exported `outreach_ready.csv` contains only profiles meeting the fully ready policy.
- `needs_review.csv` includes profiles that do not satisfy it.
- Frontend status badges, counters, filtering, and batch totals use the same policy.
- Legacy profile migration cannot change an unverified claim into a verified one simply to populate a newer field.

## 4.5 Required readiness regression tests

Test combinations including:

- High lead-fit score plus unverified identity.
- Verified identity plus unverified current role.
- Verified role plus unverified company.
- An imported but unprobed email.
- A malformed email.
- A plausible but uncorroborated LinkedIn URL.
- A verified role claim whose source does not actually support the role.
- A ready-looking icebreaker with invalid source evidence.
- A conflicting company or identity claim.
- A complete set of eligible claims with a supported contact channel.
- Export partition correctness for ready versus review profiles.

Use explicit expected statuses and blockers. Do not weaken existing tests to make the suite pass.

---

# 5. P0 — Close production API authorization gaps

**Primary file:** `src/lead_research/server.py`  
**Related files:** `src/lib/api.ts`, Next.js route handlers or middleware where appropriate, `docker-compose.yml`, `Dockerfile`, `.env.example` or configuration documentation, `tests/test_api.py`

## 5.1 Remove fail-open authorization in production

The current `verify_api_key()` implementation returns success when `API_SECRET_KEY` is empty. This makes sensitive mutations unauthenticated by default when the variable is absent.

Change the policy so that:

- Production startup or protected operations fail closed when the required security configuration is missing.
- A missing, empty, malformed, or incorrect production credential cannot silently bypass authorization.
- The authentication path used by the browser frontend actually works with the deployed configuration.
- Local development remains usable through a clearly defined and explicitly development-only mode.
- Development bypasses cannot be accidentally enabled in production just because a variable was not set.

Validate the environment mode and allowed deployment configurations. Document exactly how to configure production and local development.

## 5.2 Do not expose a shared secret in browser JavaScript

The current frontend reads `NEXT_PUBLIC_API_KEY`. A `NEXT_PUBLIC_*` value is exposed to browser code and must not be relied upon to keep a shared secret confidential.

Do not simply rename this variable to another public variable or embed the credential in frontend source code.

Inspect how the Next.js frontend communicates with the FastAPI backend and choose a secure, architecture-compatible arrangement. Prefer a server-side proxy/backend-for-frontend with server-only credentials plus a proper authenticated session or access-control mechanism, or an equivalent supported design.

Requirements:

- The browser must not receive the server's shared API secret.
- Sensitive operations must require an authenticated, authorized caller even through any same-origin frontend proxy.
- Do not leave an unauthenticated proxy that effectively bypasses the backend's new authorization.
- Session cookies, where used, must have appropriate `HttpOnly`, `SameSite`, and production `Secure` settings.
- Handle sign-in, invalid sessions, expiration, and unauthorized responses coherently.
- Do not log credentials or return them in exceptions.
- Configure the Docker deployment and frontend so that ordinary authenticated UI functions still work.
- Keep any development-only shortcut explicit, tested, and limited to local development.

If a complete user-session mechanism already exists, integrate with it instead of introducing a second identity system. If none exists, implement the smallest sound authentication mechanism that secures sensitive UI operations and document its setup. Do not claim a browser-exposed static token is secure authentication.

## 5.3 Protect all relevant operations

Review every endpoint and identify which operations are public, read-only, authenticated, administrative, or destructive.

Protect at least:

- Dataset uploads.
- Research batch starts, restarts, and retries.
- Deleting individual batches.
- Clearing all batch/history records.
- Mutating Tor settings or other privileged runtime configuration.
- Any other endpoint that can incur external requests, change stored data, export sensitive records, or alter runtime state.

Do not assume every read route is harmless: lead and export endpoints can expose personal contact data. Apply authentication and authorization appropriate to the deployed application's user and data-access model.

Validate that the access model applies consistently to direct backend access as well as calls through the frontend. CORS must not be used as an authentication mechanism.

## 5.4 CORS and request validation

Keep explicit allowed CORS origins. Never combine `allow_origins=["*"]` with credentialed access.

Also verify:

- Origins are normalized and configured explicitly.
- Unexpected origins are not allowed by a permissive fallback.
- Credentials are enabled only when needed.
- Batch IDs and request parameters are validated.
- Upload filenames cannot perform path traversal.
- Only supported file types are accepted.
- Upload size limits are enforced before writing unbounded content.
- Invalid or unauthorized requests receive appropriate HTTP codes without stack traces, secrets, or full input data.

Do not overstate what CORS guarantees: same-origin or direct API requests must still be protected by authorization.

## 5.5 Required authorization regression tests

Test:

1. Production mode with no required secret fails closed or refuses startup with an actionable error.
2. Missing credentials return 401 or 403 for sensitive operations.
3. Incorrect credentials return 401 or 403.
4. Correct credentials allow an authorized request.
5. Development-mode behavior is available only under the defined development configuration.
6. No browser bundle exposes a server-only API secret.
7. A same-origin frontend proxy cannot be used to bypass authentication.
8. Unauthorized callers cannot upload, start, delete, clear history, or change protected settings.
9. Valid authenticated UI flows remain functional.
10. Disallowed CORS origins are not granted access.
11. An authenticated but unauthorized user cannot perform administrative actions, if the application's user model supports different roles.
12. Invalid uploads and traversal attempts are rejected safely.

Mock secrets in tests. Never print real environment credentials.

---

# 6. P0 — Apply SSRF protection to every fetching path

**Primary file:** `src/lead_research/scraper.py`  
**Related files:** `tests/test_scraper_mocked.py`, `tests/test_v2_pipeline.py`, fetch configuration and Docker networking

The direct HTTP path now checks redirects before making requests to redirect destinations. However, the browser fallback still uses `StealthyFetcher.fetch()` without demonstrated equivalent enforcement for every redirect and subsequent network request.

Checking only the initial URL does not make browser navigation SSRF-safe.

## 6.1 Establish one shared URL and destination policy

Every fetching mechanism must enforce a consistent policy before connecting to a destination.

At minimum:

- Permit only explicitly supported HTTP/HTTPS schemes.
- Reject embedded URL credentials.
- Reject localhost, private, loopback, link-local, reserved, multicast, and otherwise disallowed IP destinations.
- Reject disallowed internal hostnames and address representations.
- Normalize and validate hostnames, ports, and URLs consistently.
- Validate resolved DNS addresses, including IPv4 and IPv6.
- Handle DNS failures conservatively.
- Bound connection and read times, retries, redirect count, and response size.
- Retain an explicit, auditable reason when a request is blocked.

Ensure that IP classification is complete and correct for the address types supported by the runtime. Do not assume checking only a subset of `ipaddress` properties covers every non-public range.

## 6.2 Validate every redirect before fetching it

For the direct HTTP implementation:

- Continue disabling automatic redirects.
- Parse each redirect's `Location` against the current URL.
- Validate the resulting absolute destination before the next connection.
- Reject redirect loops and excessive redirect chains.
- Revalidate DNS and destination policy for each new host.
- Never issue a request to a blocked redirect target and then report that it was blocked afterward.

Add tests that verify not only the returned error but also that the unsafe destination was never requested.

## 6.3 Secure or disable browser fallback

Inspect the current Scrapling/StealthyFetcher version and determine whether the browser supports reliable pre-request interception for:

- Top-level navigation.
- HTTP redirects.
- Subresource requests.
- Popups and new pages.
- Client-triggered navigations and requests.
- WebSocket or other outbound mechanisms, if supported.

If the available browser stack can enforce the destination policy reliably, implement that enforcement and test it.

If the stack cannot guarantee that every destination is checked before the network request occurs, do not claim that the browser path is safe merely because its initial URL was checked. Use a demonstrably safe network boundary, such as a controlled validating egress proxy, or disable the unsafe browser fallback for production research. Document any retained restriction.

Apply the same policy when Tor, proxies, or alternate transport settings are enabled. Do not assume that using a proxy alone prevents SSRF.

## 6.4 Address DNS rebinding and connection-time validation

Checking DNS and then allowing the HTTP library to resolve the hostname again introduces a potential time-of-check/time-of-use gap.

Inspect whether the current transport can pin or constrain the validated destination addresses while preserving correct TLS hostname verification and HTTP host semantics.

Use a transport-level or egress control that can enforce the required protection. Where the stack cannot reliably guarantee this, fail closed for the unsafe path or document precisely which guarantee is unavailable.

Do not solve DNS rebinding by disabling certificate verification or weakening TLS validation.

## 6.5 Required SSRF regression tests

Use mocks or local test doubles. Do not make real requests to cloud metadata services, internal networks, or other potentially sensitive endpoints.

Test:

1. Public HTTP/HTTPS addresses allowed under policy.
2. Loopback and private IPv4 addresses blocked.
3. IPv6 loopback, private, link-local, and mapped-address cases handled.
4. Malformed URLs, embedded credentials, and disallowed schemes rejected.
5. Internal hostnames and reserved destinations blocked.
6. Hostnames resolving to a public and a private address are blocked.
7. Unsafe redirects are rejected before the next request.
8. Redirect loops and excessive redirects are rejected.
9. DNS failures produce a safe result.
10. Browser top-level redirects and subresource requests are subject to the same policy.
11. Proxy/Tor paths cannot bypass it.
12. A permitted page can still be fetched through each production-enabled method.
13. Any browser path that lacks reliable enforcement is disabled or clearly limited rather than falsely reporting full protection.

---

# 7. P1 — Make cache invalidation reflect actual research configuration

**Primary file:** `src/lead_research/fingerprint.py`  
**Related files:** `src/lead_research/pipeline.py`, `src/lead_research/importer.py`, researcher configuration and tests

The code now normalizes aliases such as `Full Name`, `Company Name`, and `Job Title`. However, the pipeline still constructs the fingerprint using only `{"dry_run": dry_run}` as the research configuration.

Changes to research modes, browser usage, Tor/proxy configuration, enabled evidence sources, or the verification and personalization logic may therefore reuse old research results.

## 7.1 Build one canonical fingerprint input

Normalize data from the canonical `LeadInput` model rather than relying on inconsistent dictionaries wherever possible.

Ensure equivalent headers and values yield the same normalized data, while meaningful changes invalidate the cache.

Include relevant fields such as:

- Name and other person identifiers.
- Company and company website.
- Job title.
- Professional email and profile URL.
- Industry, keywords, and relevant location fields.
- Any additional fields that materially change research or identity matching.

Be careful with alias normalization. Confirm that all declared aliases use the same normalization convention as the lookup table; case, spaces, and underscores must behave consistently.

## 7.2 Include relevant research configuration and implementation versions

Build a stable, centrally defined cache configuration based on the effective research settings.

Include relevant properties such as:

- Dry-run behavior.
- Browser mode.
- Tor/proxy mode and other materially different transport settings.
- Enabled research sources and extraction policies.
- Identity-verification policy version.
- Evidence and claim-extraction policy version.
- Scoring-policy version.
- Personalization-policy version.
- Profile schema version.
- Pipeline implementation version.

Do not store proxy passwords, API keys, credentials, or other secrets in the fingerprint inputs, fingerprint diagnostics, logs, or exported metadata.

Include a stable, non-secret representation of configuration that materially affects results. Do not include volatile timestamps, random IDs, or irrelevant values that would unnecessarily invalidate the cache.

Centralize version definitions and ensure the values passed by the pipeline reflect the actual active configuration. Do not update a default function argument while leaving the real pipeline on its old version.

## 7.3 Cache compatibility and persistence

A cached profile must be reused only when its fingerprint and schema/version compatibility can be established.

Profiles without a fingerprint, profiles with an incompatible schema, and profiles generated under materially different research settings must not be silently treated as current.

Preserve those historical files. Reject reuse or mark them as requiring new research instead of rewriting their metadata to appear current.

## 7.4 Required fingerprint regression tests

Test that:

- Identical canonical data produces identical fingerprints.
- Equivalent header aliases produce the same fingerprint.
- Changes to each meaningful research field change the fingerprint.
- Relevant research configuration changes invalidate the fingerprint.
- Extraction, verification, scoring, and personalization version changes invalidate the fingerprint as designed.
- Secret values are not written into logs or profile metadata.
- Irrelevant volatile values do not invalidate the cache.
- Historical profiles missing fingerprints are handled according to the explicit compatibility policy.

---

# 8. P1 — Enforce batch immutability and consistent exports

**Primary files:** `src/lead_research/exporter.py`, `src/lead_research/pipeline.py`, `src/lead_research/server.py`  
**Related files:** batch schemas, batch UI, export tests

The server blocks some completed-batch restarts, but the exporter can still open an existing directory and overwrite its files. This means a code path such as a resume or repeated export can mutate outputs that users expect to be a stable record of a prior research run.

## 8.1 Define batch lifecycle semantics

Document the exact lifecycle states and which transitions are legal.

Use these principles:

- Each new research run has a unique batch or attempt identity.
- A completed, finalized batch is immutable.
- A retry or re-evaluation must not silently replace its output files or manifest.
- Historical batch summaries, profiles, claims, evidence, CSVs, and manifests remain available.
- A batch ID must not be reused simply because its directory exists.
- A race between two start requests cannot cause both requests to write the same run.

Review the current `resume` behavior and determine whether it can safely resume unfinished work without mutating finalized outputs.

If safe resumption cannot be guaranteed within the existing implementation, reject the resume operation with an actionable message and require the user to start a new batch. Do not silently re-export into the same finalized directory.

If resumption is retained, represent it explicitly as a distinct, auditable attempt or revision. Preserve the earlier snapshot and outputs.

## 8.2 Enforce immutability at every relevant layer

Protect the policy in more than the API endpoint.

Implement checks in the batch reservation/start logic and exporter so that calling the exporter directly cannot overwrite a finalized batch.

Where practical:

- Reserve batch IDs atomically.
- Use locks or an equivalent mechanism to prevent concurrent reservations.
- Reject existing finalized destination directories.
- Write files to temporary paths and atomically publish them.
- Validate temporary outputs before publishing a completed manifest.
- Update the global latest pointer only after the intended outputs and manifest are successfully finalized.
- Do not promote a partially written or failed batch to latest.
- Keep the uploaded input, input hash, profile counts, manifest counts, and summary consistent.

Do not rely solely on a status stored in in-memory state. Reconcile persisted manifests and directory state as needed.

## 8.3 Keep historical review data unchanged

The existing checked-in data and batch outputs must remain untouched.

Do not automatically regenerate `data/output/latest.json`, `data/output/manifest.json`, legacy CSVs, profile JSONs, or other committed artifacts as part of this fix.

Use isolated temporary directories for tests. Demonstrate new output behavior with synthetic fixtures.

When users explicitly start a real batch later, ensure that the new batch receives a distinct identity and that previous outputs remain preserved.

## 8.4 Required batch regression tests

Test:

1. Exporting a new batch succeeds.
2. A second export using the same finalized batch ID is rejected.
3. Starting an already completed batch is rejected without mutating it.
4. Retrying or resuming unfinished work follows the documented policy.
5. Concurrent starts do not both reserve the same batch.
6. Concurrent exports cannot overwrite one another.
7. A failed file write does not update the finalized manifest or latest pointer.
8. A valid new batch updates the correct latest pointer only after successful completion.
9. Manifest counts match generated outputs.
10. Existing historical outputs remain unmodified.
11. The frontend receives an actionable error for an invalid restart rather than a false “started” response.

---

# 9. P1 — Profile and evidence consistency across API, exports, and UI

Inspect the entire data flow between the research engine, schema validation, exporter, API endpoints, and the Next.js frontend.

Ensure that a correct backend decision cannot become misleading due to serialization, legacy migrations, export logic, or frontend presentation.

Requirements:

- New profiles use a consistent schema and pipeline version.
- Their metadata and manifests agree about schema, pipeline, and batch IDs.
- Claim statuses and blockers survive serialization without changing meaning.
- Source IDs and claims remain connected to the correct profile.
- The `outreach_ready.csv`, `needs_review.csv`, JSON profiles, summary, and manifests derive their counts from the same readiness decision.
- Historical schema migration preserves the original uncertainty and does not invent corroboration.
- The latest pointer does not imply that a pre-fix historical batch was generated by the new code.
- Missing or inconsistent historical manifests are surfaced as a warning or validation result, not silently rewritten.
- Frontend status labels reflect what is actually supported by the API.
- A `ready_with_caveat` profile is not represented as a fully ready profile by a UI badge, summary count, or download.

Add tests for these consistency rules using synthetic profile data.

---

# 10. Regression test and CI requirements

Extend the existing test suite instead of replacing it or introducing a separate test framework unnecessarily.

Inspect at least:

- `tests/test_api.py`
- `tests/test_scraper_mocked.py`
- `tests/test_exporter.py`
- `tests/test_scoring.py`
- `tests/test_identity.py`
- `tests/test_v2_pipeline.py`
- Existing frontend logic and API tests

Add tests to the appropriate modules for every regression described above.

The tests must reproduce the real failure mode. A test that merely checks that a helper exists, that a function returns a non-empty value, or that a string appears in the output is insufficient to establish the security or verification property.

### Minimum execution checklist

Run the targeted backend tests first, followed by:

1. The complete pytest suite using the repository's configured Python environment.
2. Frontend unit tests.
3. TypeScript type checking.
4. Next.js production build.
5. Any additional security or integration test commands already configured in CI.

Use the existing command names from `package.json` and `.github/workflows/ci.yml`. Report actual commands and actual results. Investigate and correct regressions introduced by the implementation. Do not skip or weaken existing tests just to achieve a green build.

Where a test cannot be executed, report the exact blocker. Do not claim it passed.

---

# 11. Acceptance criteria

The task is complete only when the following behaviors have been demonstrated with regression tests.

### Research correctness

- A company-page name mention cannot independently raise identity confidence to a verified state.
- Search-result snippets can discover candidates but cannot verify a current title.
- Current roles require appropriate inspected, claim-specific evidence.
- Company verification depends on corroborating company identity, not merely a successful HTTP request.
- Abbreviated names and same-name collisions do not pass verification without adequate evidence.
- Evidence references are valid and relevant to the claims they support.

### Personalization correctness

- Company-level signals cannot be converted into person-specific career claims without evidence.
- A news URL or an AI keyword alone cannot establish a product launch.
- Unverified or unsupported statements cannot produce a ready person-targeted icebreaker.
- Personalization wording matches the strength and scope of its evidence.

### Readiness correctness

- Lead fit cannot substitute for identity, role, or company verification.
- Input values are not automatically verified contact channels.
- Unprobed emails are not labelled deliverable.
- All backend, export, and frontend readiness states agree.

### Security

- Production API authorization fails closed.
- No server-side API secret is shipped to browser code.
- Direct API access and same-origin proxy access both enforce authorization.
- The direct HTTP and browser fetching paths enforce SSRF policy before contacting unsafe destinations.
- Redirects, DNS resolution, and browser subrequests cannot bypass the stated SSRF policy.
- Unsafe network behavior is disabled if the available stack cannot safely enforce the required controls.

### Data and storage integrity

- Relevant research changes invalidate incompatible cached profiles.
- Finalized batches cannot be silently overwritten.
- Failed or concurrent runs cannot corrupt manifests or latest pointers.
- Existing checked-in data and historical review outputs remain unchanged.

### Build and evidence

- New regression tests pass.
- Existing backend and frontend CI checks pass.
- The final diff contains only intentional changes.
- Every claimed fix is backed by code and an appropriate test.

---

# 12. Final implementation report

When finished, provide the following report in your response:

## A. Summary
State which remaining defects were fixed and what behavior changed.

## B. Files changed
List each changed file and explain why the change was necessary.

## C. Root cause and correction
For each major defect, provide:
- The original failure path.
- The concrete correction.
- The regression test proving the correction.

## D. Test evidence
List each exact test/build command and its observed result. Separate passed, failed, and unexecuted checks.

## E. Security limitations
Be explicit about any SSRF, browser isolation, authorization, or transport guarantees that the current libraries cannot fully provide.

## F. Configuration required
Document any environment variables, authentication setup, Docker changes, or migration steps needed to run the updated application correctly.

## G. Data preservation
Confirm that existing files under `data/`, `.gitignore`, and historical review outputs were not changed or deleted.

## H. Remaining work
List anything that remains unfixed with a precise reason and an appropriate follow-up action.

Do not claim production readiness merely because CI is green. Do not claim a security guarantee unless its enforcement mechanism and tests justify that claim. Do not modify the user's existing review data to make the report appear cleaner.

**Start implementation now. Do not return only a plan or ask for confirmation.**