 # Fix Prompt: SealAPI Tor Runtime Verification, Docker Smoke Testing, and Specification Recovery

Act as a senior backend, security, and DevOps engineer working on the existing SealAPI / LeadDetailsScraper repository.

## Objective

Address these three outstanding issues with a narrowly scoped, verifiable implementation:

1. Tor's SOCKS5 health check does not prove that Tor has completed bootstrap or can route traffic through a Tor exit node.
2. The complete Docker Compose stack has not yet been verified through a real runtime smoke test, including application-to-Tor connectivity and protected API endpoints.
3. `fix.md` has lost a substantial portion of the previous security specification. Recover the original requirements without losing the current Tor-specific checklist.

**Do not start a broad refactor. Investigate the existing implementation first, fix the identified gaps, perform the available runtime checks, and report the actual results.**

> **Specification Pointer:** The historical master security specification (`fix.md` from commit `4a84a2ed29708fdd032e99e95f0c381a8d2769c8`) has been fully recovered and preserved in [`docs/SECURITY_MASTER_SPEC.md`](docs/SECURITY_MASTER_SPEC.md).

---

## Phase 1 — Inspect the Existing Repository

Before changing anything:

1. Check the current Git branch, working-tree status, uncommitted changes, and latest commits.
2. Inspect the current versions of:
   - `docker-compose.yml`
   - `.github/workflows/ci.yml`
   - `src/lead_research/tor_manager.py`
   - `server.py` and the implementation of `/api/tor/status`
   - `tests/test_api.py`
   - `tests/test_network_and_email_hardening.py`
   - `fix.md`
   - Relevant dependency files and Docker configuration.
3. Trace how the application selects the Tor proxy, checks SOCKS5 connectivity, verifies external routing, and reports the resulting status to API clients.
4. Inspect the Compose services, exposed ports, environment variables, health checks, authentication requirements, and currently running containers before starting or stopping anything.
5. Inspect Git history for the previous, fuller `fix.md` specification.

Use the repository's actual structure and existing conventions. Do not assume file paths, endpoints, dependency availability, or container capabilities without checking them.

## Phase 2 — Correct Tor Health and Status Semantics

### A. Separate liveness, proxy readiness, and verified routing

Implement or refine distinct status concepts:

- **SOCKS endpoint reachable:** The SOCKS5 handshake succeeds.
- **Routing verified:** A bounded external request succeeds through the configured SOCKS proxy and confirms that the traffic exits through the Tor network.
- **Routing unverified or failed:** A route check has not been performed, times out, fails, or cannot confirm a Tor exit.

Never represent a successful TCP connection or SOCKS5 handshake as proof of Tor routing.

Preserve the existing state names and response structure where practical. If a response schema must change, maintain backward compatibility where feasible and document any unavoidable change.

### B. Verify actual Tor routing

Inspect the existing `verify_tor_routing()` implementation.

Where appropriate, use an external verification endpoint such as:

`https://check.torproject.org/api/ip`

Verify the response structure and require its Tor-verification field to be explicitly true. An ordinary HTTP 200 response or successful IP lookup alone is insufficient to prove Tor routing.

Requirements:

- Route the request through the configured SOCKS proxy, not the application's direct internet connection.
- Apply strict connection and total-request timeouts.
- Handle DNS, TLS, connection, HTTP, and response-parsing errors safely.
- Do not log credentials, authorization headers, API keys, or other secrets.
- Do not describe an arbitrary SOCKS proxy as Tor merely because it accepts connections.
- Keep external routing verification separate from ordinary unit tests by mocking external requests.
- Fail closed when Tor routing cannot be verified.

If the existing dependency stack uses `requests`, `httpx`, or `curl_cffi`, follow the repository's established approach and verify that SOCKS support is actually available.

### C. Correct `/api/tor/status`

The current endpoint calls `manager.get_status()` without enabling the optional routing check.

Correct the behavior so API consumers can reliably distinguish endpoint reachability from verified routing.

For example, support an explicit routing-verification option if needed, such as `?verify_routing=true`, while preserving the existing response contract where practical.

The default response must clearly indicate whether routing was actually checked. Do not silently imply that routing is verified when the code only performs a SOCKS5 handshake.

Keep API-key authorization enforced on this endpoint. Do not weaken authentication or expose secrets in the status response.

### D. Keep the Docker health check honest

Inspect the health check in `docker-compose.yml`.

The existing SOCKS5 handshake can remain a basic container/proxy liveness check. Document its scope clearly and do not use its passing state as a substitute for end-to-end Tor routing verification.

If the pinned image exposes a reliable bootstrap-status mechanism, assess whether it can be used safely. Do not assume a Tor control port or command exists without checking the actual image.

Avoid adding unnecessary privileges, exposing an unauthenticated control port, or introducing fragile assumptions about utilities installed inside the image.

Keep these concepts separate:

- Container health.
- Application readiness.
- End-to-end Tor routing verification.

Do not make routine container health dependent on an unreliable public endpoint unless there is a clear, justified design decision and appropriate timeout and failure behavior.

---

## Phase 3 — Perform a Real Docker Runtime Smoke Test

Do not treat passing unit tests as evidence that the Docker deployment works.

### A. Validate and start the actual stack

1. Confirm Docker and the Docker Compose plugin are available.
2. Validate the Compose configuration, including interpolation and service dependencies.
3. Pull the exact pinned Tor image specified in the repository.
4. Verify that the image digest remains pinned. Do not replace it with an unpinned tag.
5. Start the required Compose services using the repository's actual configuration.
6. Wait for startup with bounded timeouts.
7. Inspect container status, health status, startup logs, and application logs.

Before startup, inspect existing containers and port usage. Avoid disrupting unrelated development services. If an isolated smoke-test project is necessary, account for hard-coded container names and ports before creating it.

Do not run `docker system prune`, delete existing volumes, or stop unrelated services.

### B. Verify application-to-Tor connectivity

Test the actual network path from the application container, or through an equivalent request handled by the running application, to the configured Tor SOCKS endpoint.

Verify all of the following separately:

1. The Tor container starts successfully.
2. The SOCKS5 handshake succeeds.
3. The application can connect to the configured proxy using the hostname and port available inside its Compose network.
4. A real external request can traverse that proxy.
5. The external verification response confirms a Tor exit rather than merely returning HTTP 200.

A test executed from the host directly is not sufficient evidence of application-to-Tor connectivity.

Use bounded retries and timeouts. If outbound network access, DNS, TLS, the external verification endpoint, or Docker permissions prevent the test from completing, report the exact failure and identify which checks remain unverified.

Never claim routing verification succeeded unless the external result explicitly confirms it.

### C. Test protected API endpoints

Determine the correct base URL, port, API-key configuration, and endpoint behavior from the existing implementation.

Test `/api/tor/status` and the routing-verification option, if implemented:

- Request without an API key: authentication must be rejected.
- Request with an invalid API key: authentication must be rejected.
- Request with a valid test key: the endpoint should return the appropriate status.
- Request without routing verification enabled: the response must not claim that routing has been verified.
- Request with routing verification enabled: the response must reflect the actual verification outcome, including failures and timeouts.

Use a temporary synthetic test key or the existing test authentication configuration. Never expose production keys in logs or reports.

Use only non-destructive endpoints and synthetic data. **Do not run the lead-research pipeline against the existing review dataset.**

### D. Make the smoke test repeatable

Add a narrowly scoped smoke-test script or equivalent integration-test mechanism if needed.

It should:

- Verify the relevant runtime checks in a reproducible sequence.
- Use explicit timeouts and bounded retries.
- Return a nonzero exit status for failed required checks.
- Print clear PASS, FAIL, or BLOCKED outcomes for individual checks.
- Avoid printing secrets.
- Avoid invoking the production research workflow.
- Clean up only containers and temporary resources it created, without deleting volumes or existing data.

Consider adding a manually triggered GitHub Actions workflow for live Docker/Tor runtime acceptance if it fits the current project. Keep ordinary CI deterministic; do not make every pull request depend on an external Tor verification endpoint unless justified.

Do not create a workflow that merely reports success after a SOCKS handshake.

---

## Phase 4 — Recover the Full Security Specification

The current `fix.md` has been shortened significantly, and its earlier detailed security requirements must not be lost.

1. Inspect `git log` and identify the prior full version of `fix.md`, using the known history as a starting point if available:
   - `4a84a2ed29708fdd032e99e95f0c381a8d2769c8`
   - `e610b29` if it exists in the repository history.
2. Confirm which historical version contains the original comprehensive requirements.
3. Restore the complete, original text into a separate permanent document, for example:
   `docs/SECURITY_MASTER_SPEC.md`
4. Preserve the existing Tor-runtime checklist in `fix.md`. Do not overwrite the current checklist with the historical document.
5. Preserve the original requirements and wording wherever possible. Do not invent missing sections, silently remove requirements, or substitute a newly written shorter summary.
6. Add a concise pointer between the two documents only if appropriate.
7. If the historical content cannot be recovered, report the blocker clearly and leave the current files intact rather than fabricating the missing specification.

The recovered requirements should remain available for future implementation and regression reviews.

---

## Phase 5 — Automated Tests and Regression Protection

Add or update focused tests for:

- SOCKS5 handshake success and failure.
- External route verification returning an explicitly verified Tor result.
- External responses that are successful HTTP requests but do not confirm Tor routing.
- Timeouts, connection errors, invalid responses, and malformed JSON.
- Accurate state reporting before and after a routing check.
- API-key enforcement for `/api/tor/status`.
- API responses that distinguish reachable SOCKS endpoints from verified Tor routing.
- Existing Tor-disabled and proxy-unreachable behavior.
- Any new smoke-test script's failure and cleanup behavior, where practical.

Mock external calls in unit tests so ordinary CI does not depend on Tor availability or external websites.

Run the existing backend and frontend tests, TypeScript typecheck, and production build using the repository's established commands. Run Compose configuration validation and the actual runtime smoke test separately.

Do not remove, weaken, or rewrite existing tests merely to make the new implementation pass.

---

## Non-Negotiable Safety and Repository Constraints

- **Do not delete, overwrite, regenerate, move, or untrack any existing files under `data/`.**
- Do not edit `.gitignore` to conceal existing data or test failures.
- Treat the existing review dataset as read-only.
- Use synthetic fixtures and temporary directories for testing.
- Do not reset the branch, discard unrelated local modifications, rewrite Git history, or force-push.
- Do not overwrite existing uncommitted user work.
- Do not modify unrelated components or perform a broad refactor.
- Do not change the pinned Tor image digest without an explicit technical justification and verification.
- Do not remove authentication or weaken SSRF and network security controls.
- Do not claim Docker runtime success or Tor routing verification without actual successful evidence.
- Do not commit or push changes unless explicitly requested.

If a required runtime check cannot run because a tool or environment is unavailable, explain the limitation and complete all remaining checks that can run safely.

## Definition of Done

The task is complete only when:

1. SOCKS endpoint health and actual Tor routing verification are distinct and accurately reported.
2. `/api/tor/status` does not imply verified routing without evidence.
3. The real Docker stack has been tested to the extent the available environment permits.
4. Application-to-Tor external routing has been confirmed, or the precise blocker is documented without claiming success.
5. Protected API endpoints have been tested with missing, invalid, and valid credentials.
6. A repeatable runtime smoke-test procedure exists.
7. The previous comprehensive security specification is preserved separately from the current Tor checklist, or the recovery blocker is explicitly reported.
8. Existing backend/frontend tests, typechecking, and production build have been run and their outcomes recorded.
9. Existing user data and unrelated work remain untouched.

## Required Final Report

Provide a concise, evidence-based report containing:

**1. Root causes:** What was wrong and why.

**2. Files changed:** Each file and the reason it changed.

**3. Runtime verification results:** Include Docker/Compose validation, image pull, container health, SOCKS handshake, application-to-Tor connectivity, verified Tor exit, and protected API endpoint tests. Mark each as PASS, FAIL, or BLOCKED.

**4. Automated validation:** Exact test commands and pass/fail counts for backend, frontend, typecheck, build, and any new tests.

**5. Specification recovery:** The historical version used and the location of the preserved full specification, or the exact blocker.

**6. Remaining risks:** Any failures, environmental limitations, or checks not completed.

**7. Git status:** Branch name, whether the working tree has changes, and a list of changed files. Do not commit or push.

Be precise about what was actually executed versus what was merely added to the repository. A passing unit-test suite is not proof of a functioning Docker deployment, and a successful SOCKS5 handshake is not proof of Tor routing.