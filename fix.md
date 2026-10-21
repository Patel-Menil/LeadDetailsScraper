LeadDetailsScraper — Final Deployment Acceptance and Security Verification
Workspace: C:\sealapi\dataScrap\Combine
Repository: [https://github.com/Patel-Menil/LeadDetailsScraper/](https://github.com/Patel-Menil/LeadDetailsScraper/)
Specification: fix.md
The previous phase reported 108 backend tests passing, 17 frontend tests passing, successful TypeScript checking and production build, valid Docker Compose configuration, and implementation of transport-level SSRF pinning, Tor service configuration, email corroboration, and API security.
Continue from the current implementation. Do not rewrite completed functionality or repeat earlier work without a specific defect.
1. Recover and preserve the current state
Before editing:
Run git status --short, git diff --stat, and inspect the relevant existing diffs.
Read the complete current fix.md.
Verify which results from the previous report can be reproduced.
Preserve existing uncommitted changes.
Do not reset, stash, discard, overwrite, or replace the local workspace with remote main.
Do not modify existing files under data/. Do not change .gitignore to exclude historical review data. Do not run the scraper on the existing real-lead dataset.
2. Verify actual cURL DNS-pinning semantics
Inspect src/lead_research/scraper.py and the installed versions of curl_cffi, libcurl, and Scrapling.
Specifically verify construction of CurlOpt.RESOLVE entries.
For multiple approved addresses for the same hostname and port, use the exact format supported by the installed transport.
Verify that multiple IP addresses are represented correctly and are not accidentally replaced by successive entries for the same hostname and port.
Ensure IPv6 addresses use the format required by libcurl, including brackets where required.
Handle IPv4, IPv6, mixed address families, non-default ports, and redirects.
Ensure every address placed into a pin entry has passed the destination policy.
Preserve URL hostname, HTTP Host header, TLS SNI, certificate verification, and request semantics.
If the transport cannot apply the required pin safely, fail closed.
Add deterministic regression tests for multiple approved IPv4 addresses, IPv6 address formatting, multiple same-host entries, malformed pin entries, and redirect re-pinning.
Do not use successful requests to a public website as the only proof of the pinning behavior. Test the actual transport option and verify the connection target in a controlled local test.
Keep the ordinary SSRF policy intact. Test that the normal application path still rejects loopback and prohibited addresses.
3. Harden Tor deployment configuration
Inspect docker-compose.yml and the actual Tor image metadata.
Immutable image reference
Replace a mutable osminogin/tor-simple:latest reference with a verified immutable multi-platform manifest digest or another explicitly versioned and verifiable image reference.
Determine the digest from authoritative image metadata. Do not invent a digest or select one without checking its image/platform compatibility.
Document how the pinned image is updated safely, including when the digest should be refreshed.
Health-aware startup
Inspect the health check configured for the Tor service and verify that the check command actually exists in the selected image and reliably confirms that the SOCKS5 service is listening.
If the application requires a functioning Tor service when TOR_ENABLED=true, use a health-aware Compose dependency (service_healthy) rather than merely waiting for the container to start.
Ensure the health check does not falsely report readiness when Tor is still bootstrapping.
Handle service restart, unavailability, and recovery. Do not silently switch to an unsafe network-fetching path if Tor is unavailable.
Runtime smoke test
If Docker is available:
Review the effective docker compose config.
Inspect bind mounts and ensure the startup test cannot alter historical review data under data/.
Pull the verified pinned image.
Start the relevant services with the documented configuration.
Inspect docker compose ps and verify actual health status.
Confirm that the application can reach the Tor SOCKS5 endpoint using an approved, fixed public test destination.
Verify the required API health and authentication behavior.
Inspect logs for startup errors, credential leaks, and unexpected fetch fallback.
Stop the services cleanly.
Do not launch a real-lead research batch as a deployment test.
If Docker runtime is unavailable, execute the configuration-level checks and report that actual container startup and connectivity remain unverified.
4. Validate egress security assumptions
Re-audit all enabled outbound requests in scraper.py and related code.
Document the distinct security boundaries for:
Direct HTTP with connection pinning.
Tor-proxied fixed-endpoint search.
Arbitrary target URLs discovered from search.
Any browser or subresource fetching that remains enabled.
Confirm that proxy configuration cannot bypass target-fetch restrictions. If an outbound path cannot guarantee destination enforcement, disable that path or fail closed.
Evaluate defense-in-depth egress restrictions without assuming that the application container and Tor container can share identical outbound firewall rules. Ensure restrictions do not accidentally break Tor's own connectivity.
Do not claim connection-level SSRF prevention based solely on preflight DNS validation or a mocked transport argument.
5. Recheck API and email verification integration
Do a concise regression review of the implemented rules without redesigning working components.
Verify that:
Direct backend calls cannot bypass authentication.
Protected reads, exports, and mutations continue to require authorization.
Missing production secrets fail safely.
Session cookies, expiration, logout, and CSRF behavior remain consistent.
Backend secrets never appear in client-visible responses.
An email is not marked verified merely because its syntax or domain is plausible.
Exact email corroboration requires evidence for that actual address.
Missing or insufficient claims remain unverified or require review.
Run the relevant existing API, scoring, research, and email-hardening tests.
6. Final validation
Run the affected test suites first, then the complete project validation:
Scraper and network/email hardening tests.
API authorization tests.
Scoring, exporter, and pipeline regressions.
Full backend test suite using the existing Python environment.
Frontend unit tests.
TypeScript typecheck.
Next.js production build.
docker compose config.
Runtime container smoke tests if Docker is available.
git diff --check.
Final git status --short and review of the changed files.
Capture real command exit codes. If a process receives KeyboardInterrupt, treat that run as interrupted, not successful. If necessary, execute tests in a separate process with output redirected.
Do not weaken security assertions or suppress failures to achieve green results.
7. Preservation and final report
All existing files under data/ must remain unchanged. Do not delete, regenerate, rewrite, rename, relocate, anonymize, or untrack them. Do not modify .gitignore to exclude them.
Use synthetic fixtures and temporary output directories for tests.
Report:
Files changed and the reason for each change.
Exact DNS-pinning format and evidence from transport tests.
Tor image reference, health-check behavior, and runtime status.
API and email-verification regression results.
Exact commands, test counts, warnings, and exit codes.
Whether Docker runtime validation was actually completed.
Confirmation that historical data/ files are unchanged.
Remaining security assumptions or production prerequisites.
Final Git status and commit hash if a commit was created.
Do not push, rewrite Git history, or discard local changes. Do not claim production readiness while any required verification remains untested.
Continue implementing any confirmed defects you find; do not stop after producing an audit.