# Fix: Make Tor Runtime Smoke Testing Safe and End-to-End

Act as a senior DevOps, Python, and application-security engineer working on the existing LeadDetailsScraper repository.

Latest commit to inspect: `b5784c07b77b6edcdb96bc2a7ef22ca822602dc8`

The recent implementation added explicit Tor exit verification, `/api/tor/status?verify_routing=true`, a runtime smoke-test script, a manually triggered GitHub Actions workflow, and the restored security master specification. Review the actual code before making changes.

## 1. Fix the workflow health-check wait

File: `.github/workflows/tor-runtime-smoke.yml`

The health-check wait command currently uses `$$` instead of `$` for command substitution.

- Correct the shell expression so `docker inspect` actually returns the container health state.
- Compare the returned state against `healthy` correctly.
- Retain a bounded timeout and print useful diagnostic output when the container fails to become healthy.
- Validate the exact shell command independently before relying on it in GitHub Actions.
- Do not mark the health check as successful merely because the command executes without a syntax error.

## 2. Test the complete application-to-Tor path

The existing workflow starts only the Tor container, and the smoke test checks routing from the host. That does not prove the application container can reach the internet through Tor.

Implement a safe, repeatable acceptance test that:

1. Validates the resolved Compose configuration and pinned Tor image digest.
2. Starts the required Tor and application services in an isolated test environment.
3. Waits for the actual required services to become healthy, using bounded timeouts.
4. Tests the SOCKS5 handshake.
5. Makes an external routing-verification request through the proxy from the application container's network context, or through an authenticated live API operation that executes the same routing check inside the running application.
6. Requires an explicit `IsTor: true` result from the Tor Project verification endpoint before reporting verified Tor routing.
7. Tests the live `/api/tor/status` endpoint using missing, invalid, and valid credentials.
8. Tests both the ordinary status request and `?verify_routing=true`, verifying that the response accurately distinguishes proxy reachability from verified routing.
9. Reports individual checks as PASS, FAIL, or BLOCKED and exits nonzero when required acceptance checks fail.

Keep unit tests independent of external websites by mocking network calls. Run live routing verification only in the dedicated runtime acceptance workflow.

Do not treat an in-process `TestClient` test or a host-side SOCKS request as evidence of live application-container connectivity.

## 3. Make cleanup non-destructive

Review both `scripts/smoke_test_tor_runtime.py` and `.github/workflows/tor-runtime-smoke.yml`.

- Remove the unnecessary `docker compose down -v` behavior.
- Never remove Docker volumes as part of this smoke test.
- Do not stop or remove pre-existing application services or containers.
- Do not run broad cleanup commands such as `docker system prune`.
- Ensure cleanup only affects resources that this smoke test created.
- Account for the existing hard-coded `container_name` and published host ports when designing isolation. Avoid interfering with another running development stack.
- If isolation cannot be made safe with the current Compose configuration, fail with a clear explanation instead of disrupting existing services.

Use a unique Compose project where appropriate, and change configuration only as needed to make this safe and reliable.

## 4. Preserve repository and data integrity

These constraints are mandatory:

- Do not delete, overwrite, regenerate, move, or untrack any existing file under `data/`.
- Do not change `.gitignore` to hide files or bypass failures.
- Do not run the lead-research pipeline against the existing review dataset.
- Use synthetic data and temporary test output only.
- Preserve the pinned Tor image digest unless a verified technical issue requires a justified change.
- Keep API authentication, SSRF safeguards, and existing security requirements intact.
- Preserve `docs/SECURITY_MASTER_SPEC.md` and the current `fix.md` checklist. Do not shorten, replace, or regenerate either document.
- Do not discard unrelated changes, reset the branch, rewrite history, force-push, commit, or push unless explicitly requested.

## 5. CI and runtime validation

Inspect the workflow triggers and ensure the dedicated runtime smoke test is clearly documented as manually triggered if that is the intended design.

Then:

- Validate the YAML and shell commands.
- Run the existing backend tests.
- Run frontend tests, TypeScript typecheck, and the Next.js production build.
- Execute the actual Docker runtime workflow in an available Docker environment.
- Inspect container health and logs, application-to-Tor routing, live API authentication, and cleanup results.
- Confirm whether the workflow was actually executed and inspect its result. Do not infer a successful run merely from a successful configuration check.

If Docker, permissions, network access, or the external verification endpoint is unavailable, report the exact blocker. Never claim the full stack passed unless it was actually exercised.

## Definition of done

The fix is complete only when the workflow detects container health correctly, application-to-Tor routing is tested from the correct execution context, protected live API endpoints are verified, cleanup is non-destructive, and all available automated and runtime checks have evidence-based results.

## Final report

Provide:

1. Root causes and the changes made.
2. Files changed.
3. Exact tests and their pass/fail counts.
4. Actual Docker, health-check, SOCKS5, Tor exit-routing, and API authentication results.
5. CI run link and result, if a run was completed.
6. Remaining blockers and risks.
7. Git branch and final working-tree status.

Clearly distinguish automated unit-test success from actual Docker runtime acceptance. Do not report unexecuted checks as passing.