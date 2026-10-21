# LeadDetailsScraper — Final Tor Runtime Verification and Health-State Correction

Workspace: `C:\sealapi\dataScrap\Combine`
Repository: https://github.com/Patel-Menil/LeadDetailsScraper/

The latest commit on GitHub is `f5fefd4580381ae8ca638b708e5432052ff3f14e`, and its GitHub Actions CI passed. Continue from the current local state; do not reimplement or overwrite completed work.

## 1. Inspect the current implementation

Review the current diffs, `docker-compose.yml`, `src/lead_research/tor_manager.py`, `src/lead_research/scraper.py`, and the related tests.

Preserve all existing changes. Read the relevant requirements in `fix.md`.

## 2. Correct inaccurate Tor status reporting

Inspect `TorManager.get_proxy_url()`, `find_active_tor_port()`, `is_port_open()`, and `get_status()`.

Currently, an explicitly configured `TOR_PROXY` can be returned without checking whether the endpoint is reachable. Ensure the status API does not equate configuration with successful connectivity.

Implement clear, separate states for:
- Tor disabled.
- Proxy configured but unreachable.
- SOCKS endpoint reachable.
- Tor successfully able to route a request, when that state has actually been verified.
- Connectivity check failed or is inconclusive.

Do not report Tor as running solely because an environment variable is non-empty. Do not leak credentials while reporting proxy status.

Add deterministic tests for a configured but unreachable proxy, a reachable TCP port that is not a functioning SOCKS proxy, disabled Tor, a functioning mocked SOCKS endpoint, and safe status output.

## 3. Strengthen Tor health checks

Inspect the exact pinned Tor image and verify which health-check utilities are actually present in the selected image.

The current `nc -z` health check tests only whether a TCP listener accepts connections. It does not prove that Tor has bootstrapped or can route a request.

Implement a bounded, reliable check appropriate for the selected image that tests SOCKS functionality and Tor readiness. Avoid fragile shell commands that are not present in the image. Avoid making health depend on uncontrolled test endpoints when a deterministic local check can establish basic SOCKS protocol operation.

Where full network readiness needs a separate external smoke test, report that distinction honestly.

Retain the verified immutable image digest and `depends_on: condition: service_healthy` unless a demonstrated issue requires a change.

## 4. Execute a Docker runtime smoke test when Docker is available

Use the existing documented configuration and synthetic validation only.

1. Inspect `docker compose config` and confirm the application and Tor service configuration.
2. Pull the pinned Tor image.
3. Start the relevant services.
4. Inspect `docker compose ps` and the health status of both containers.
5. Check application-to-Tor SOCKS connectivity using a fixed public test destination.
6. Verify the API health endpoint and protected-endpoint behavior.
7. Inspect relevant logs for startup failures, credential leakage, and unsafe fallback behavior.
8. Stop services cleanly.

Do not run the scraper against real leads.

If Docker runtime is unavailable, run the configuration tests and explain that container startup and Tor connectivity remain unverified. Do not claim runtime success based solely on `docker compose config`.

## 5. Regression tests and final validation

Run focused Tor manager tests, SSRF/network-hardening tests, and API tests. Then run the full backend suite, frontend unit tests, TypeScript typecheck, production build, `docker compose config`, and `git diff --check`.

Capture actual command exit codes. Do not suppress exceptions or weaken security assertions.

## Preservation constraints

Do not delete, rewrite, regenerate, rename, relocate, anonymize, or untrack existing files under `data/`. Do not modify `.gitignore` to exclude them. Use synthetic data and temporary directories.

Do not reset, stash, discard, or overwrite existing work. Do not rewrite Git history or force-push.

## Final report

Report the actual Tor image reference, health-check logic, container runtime results, tests and exit codes, files changed, and remaining limitations. Distinguish a reachable SOCKS port from confirmed Tor routing. Do not claim production readiness until every required validation has either passed or been explicitly documented as unverified.