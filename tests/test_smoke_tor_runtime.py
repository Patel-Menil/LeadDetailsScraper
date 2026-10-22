"""Regression tests for the Tor runtime acceptance runner's classification and lifecycle.

All Docker, network, and Tor interactions are simulated; nothing here needs a
Docker daemon, a Tor exit, or an external verification website.
"""

import importlib.util
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "smoke_test_tor_runtime", ROOT / "scripts" / "smoke_test_tor_runtime.py"
)
smoke = importlib.util.module_from_spec(_spec)
sys.modules["smoke_test_tor_runtime"] = smoke
_spec.loader.exec_module(smoke)

DEFAULT_BODY = {
    "enabled": True,
    "state": "socks_endpoint_reachable",
    "is_running": True,
    "socks_reachable": True,
    "routing_checked": False,
    "routing_verified": False,
    "port": 9050,
    "proxy_url": "socks5://tor:9050",
}
VERIFIED_BODY = dict(DEFAULT_BODY, state="routing_verified", routing_checked=True, routing_verified=True)
UNVERIFIED_BODY = dict(DEFAULT_BODY, routing_checked=True, routing_verified=False)

# A pre-existing development stack that must never be touched.
DEV_STACK = [
    ("devtor000001", "sealapi_tor_proxy", "combine"),
    ("devapp000001", "sealapi_lead_research_app", "combine"),
]


def _cp(cmd, rc=0, out="", err=""):
    return subprocess.CompletedProcess(list(cmd), rc, out, err)


class FakeDocker:
    """Simulates the docker CLI as called by SmokeTestRunner."""

    def __init__(self, *, docker_up=True, existing=(), images=(), up_rc=0, up_creates=("tor", "app"),
                 up_stderr="", up_timeout=False, health=None, torcheck='{"IsTor": true, "IP": "203.0.113.9"}',
                 verify_bodies=None, default_body=None, down_rc=0, down_removes=True, ps_fail_on_cleanup=False,
                 unit_rc=0, exec_error=None, tor_tmpfs=None, volumes=None):
        self.docker_up = docker_up
        self.containers = list(existing)
        self.images = set(images)
        self.up_rc = up_rc
        self.up_creates = up_creates
        self.up_stderr = up_stderr
        self.up_timeout = up_timeout
        self.health = health or {"tor": "running/healthy", "app": "running/healthy"}
        self.torcheck = torcheck
        self.verify_bodies = list(verify_bodies or [(200, json.dumps(VERIFIED_BODY))])
        self.default_body = default_body or (200, json.dumps(DEFAULT_BODY))
        self.down_rc = down_rc
        self.down_removes = down_removes
        self.ps_fail_on_cleanup = ps_fail_on_cleanup
        self.unit_rc = unit_rc
        self.exec_error = exec_error
        # Default mirrors the real daemon with docker-compose.smoke.yml applied.
        self.tor_tmpfs = {"/var/lib/tor": "uid=100,gid=101,mode=0700,size=64m"} if tor_tmpfs is None else tor_tmpfs
        self.volumes = volumes or {}  # role -> [(volume name, destination)]
        self.calls = []
        self.envs = []
        self.down_called = False
        self.verify_calls = 0

    def _id(self, project, role):
        return f"{project}-{role}-id"

    def __call__(self, cmd, timeout=30, env=None):
        cmd = list(cmd)
        self.calls.append(cmd)
        if env is not None:
            self.envs.append(env)
        if cmd[:3] == [sys.executable, "-m", "pytest"]:
            return _cp(cmd, self.unit_rc, "3 passed in 0.1s" if self.unit_rc == 0 else "1 failed in 0.1s")
        assert cmd[0] == "docker", cmd
        if cmd[1] == "info":
            if not self.docker_up:
                return _cp(cmd, 1, err="Cannot connect to the Docker daemon. Is the docker daemon running?")
            return _cp(cmd, 0, "27.0.0\n")
        if cmd[1] == "compose":
            i = 4
            while cmd[i] == "-f":
                i += 2
            return self._compose(cmd, cmd[3], cmd[i], cmd[i + 1:], env)
        if cmd[1] == "ps":
            if self.ps_fail_on_cleanup and self.down_called:
                raise RuntimeError("simulated docker ps crash during cleanup")
            return _cp(cmd, 0, "".join(f"{i}\t{n}\t{p}\n" for i, n, p in self.containers))
        if cmd[1:3] == ["image", "inspect"]:
            return _cp(cmd, 0 if cmd[3] in self.images else 1)
        if cmd[1:3] == ["image", "rm"]:
            self.images.discard(cmd[3])
            return _cp(cmd, 0)
        if cmd[1] == "pull":
            return _cp(cmd, 0)
        if cmd[1] == "inspect" and ".HostConfig.Tmpfs" in cmd[3]:
            mounts = [{"Type": "volume", "Name": n, "Destination": d} for n, d in self.volumes.get("tor", [])]
            return _cp(cmd, 0, json.dumps(self.tor_tmpfs or None) + "|" + json.dumps(mounts))
        if cmd[1] == "inspect" and ".Mounts" in cmd[3]:
            lines = []
            for cid in cmd[4:]:
                role = "tor" if cid.endswith("-tor-id") else "app"
                vols = "".join(f"{n}@{d} " for n, d in self.volumes.get(role, []))
                lines.append(f"/{cid[:-3]}|{vols}")
            return _cp(cmd, 0, "\n".join(lines))
        if cmd[1] == "inspect":
            role = "tor" if cmd[-1].endswith("-tor-id") else "app"
            return _cp(cmd, 0, self.health[role] + "\n")
        if cmd[1] == "exec":
            return self._exec(cmd[3:])
        raise AssertionError(f"unexpected command {cmd}")

    def _compose(self, cmd, project, sub, args, env):
        if sub == "config":
            parts = [smoke.PINNED_IMAGE_DIGEST, env["TOR_CONTAINER_NAME"], env["APP_CONTAINER_NAME"], env["APP_IMAGE"]]
            if any(c.endswith(smoke.SMOKE_OVERRIDE) for c in cmd):
                parts.append("    tmpfs:\n      - /var/lib/tor:uid=100,gid=101,mode=0700,size=64m")
            text = "\n".join(parts)
            return _cp(cmd, 0, text)
        if sub == "build":
            self.images.add(env["APP_IMAGE"])
            return _cp(cmd, 0)
        if sub == "up":
            for role in self.up_creates:
                self.containers.append((self._id(project, role), f"{project}-{role}", project))
            if self.up_timeout:
                raise subprocess.TimeoutExpired(cmd, 300)
            return _cp(cmd, self.up_rc, err=self.up_stderr)
        if sub == "ps":
            role = "tor" if args[-1] == "tor" else "app"
            cid = self._id(project, role)
            present = any(c[0] == cid for c in self.containers)
            return _cp(cmd, 0, cid + "\n" if present else "")
        if sub == "logs":
            return _cp(cmd, 0, "log line\n")
        if sub == "down":
            self.down_called = True
            if self.down_removes:
                self.containers = [c for c in self.containers if c[2] != project]
            return _cp(cmd, self.down_rc, err="simulated down failure" if self.down_rc else "")
        raise AssertionError(f"unexpected compose subcommand {sub}")

    def _exec(self, args):
        if self.exec_error:
            raise self.exec_error
        if args[0] == "printenv":
            return _cp(args, 0, "socks5://tor:9050\ntrue\n")
        if args[0] == "python3":
            return _cp(args, 0, "0500\n")
        if args[0] == "curl" and smoke.TOR_CHECK_URL in args:
            return _cp(args, 0, self.torcheck)
        if args[0] == "curl":
            url = args[-1]
            key = next((a.split(": ", 1)[1] for a in args if a.startswith("X-API-Key: ")), None)
            expected = self.envs[-1]["API_SECRET_KEY"]
            if key != expected:
                return _cp(args, 0, '{"detail":"Unauthorized"}\n401')
            if "verify_routing=true" in url:
                idx = min(self.verify_calls, len(self.verify_bodies) - 1)
                self.verify_calls += 1
                code, body = self.verify_bodies[idx]
            else:
                code, body = self.default_body
            return _cp(args, 0, f"{body}\n{code}")
        raise AssertionError(f"unexpected exec {args}")

    def compose_subcommands(self):
        # Subcommand follows: docker compose -p <project> -f <base> -f <override>
        return [c[8] for c in self.calls if c[:2] == ["docker", "compose"]]


@pytest.fixture(autouse=True)
def _host_network(monkeypatch):
    ports = itertools.count(41000)
    monkeypatch.setattr(smoke, "find_free_port", lambda: next(ports))
    monkeypatch.setattr(smoke, "is_port_free", lambda port: True)
    monkeypatch.setattr(smoke, "host_socks5_handshake", lambda port, timeout=5.0: (True, "VER=5 METHOD=0"))


def make_runner(fake, **kwargs):
    return smoke.SmokeTestRunner(executor=fake, sleep=lambda s: None, **kwargs)


def assert_never_destructive(fake):
    for cmd in fake.calls:
        joined = " ".join(cmd)
        assert "prune" not in joined
        assert " -v" not in joined and "--volumes" not in joined
        assert "sealapi_tor_proxy" not in joined and "sealapi_lead_research_app" not in joined
        if cmd[:3] == ["docker", "image", "rm"]:
            assert "tor-smoke-" in cmd[3]
        assert cmd[:2] != ["docker", "rm"] and cmd[:2] != ["docker", "stop"]
        assert cmd[:2] != ["docker", "volume"], cmd  # no volume rm/prune of any kind


# ── 1. All required checks pass ──────────────────────────────────────────────


def test_all_required_checks_pass_returns_zero(capsys):
    fake = FakeDocker(existing=DEV_STACK)
    runner = make_runner(fake)
    code = runner.run()
    out = capsys.readouterr().out

    assert code == smoke.EXIT_PASS
    assert all(runner.results[name].status == smoke.PASS for name in smoke.REQUIRED_RUNTIME_CHECKS)
    assert "RESULT: ALL CHECKS PASSED" in out
    # Cleanup removed this invocation's containers and image, and nothing else.
    assert fake.containers == DEV_STACK
    assert runner.app_image not in fake.images
    assert_never_destructive(fake)
    assert runner.api_key not in out and runner.session_secret not in out
    # With Tor's data dir in tmpfs nothing is kept, so no volume warning or removal command.
    assert runner.results[smoke.CHECK_TOR_EPHEMERAL].status == smoke.PASS
    assert "UNEXPECTED" not in out and "volume rm" not in out


def test_compose_env_is_isolated_and_overrides_host_values(monkeypatch):
    monkeypatch.setenv("TOR_PROXY", "socks5://127.0.0.1:9150")
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "combine")
    monkeypatch.setenv("API_SECRET_KEY", "host-real-key")
    fake = FakeDocker()
    runner = make_runner(fake)
    assert runner.run() == smoke.EXIT_PASS

    for env in fake.envs:
        assert env["TOR_PROXY"] == "socks5://tor:9050"
        assert env["TOR_ENABLED"] == "true"
        assert env["APP_ENV"] == "production"
        assert env["API_SECRET_KEY"] == runner.api_key != "host-real-key"
        assert env["DATA_MOUNT_DIR"] and "data" != env["DATA_MOUNT_DIR"].strip("./")
        assert env["TOR_HOST_PORT"] != "9050"
        assert "COMPOSE_PROJECT_NAME" not in env
    assert all(c[3] == runner.project for c in fake.calls if c[:2] == ["docker", "compose"])


def test_compose_refuses_to_run_without_isolated_resources():
    runner = make_runner(FakeDocker())
    with pytest.raises(RuntimeError):
        runner.compose_env()


# ── 2. A required check fails ────────────────────────────────────────────────


def test_failed_exit_routing_returns_fail_and_still_cleans_up(capsys):
    fake = FakeDocker(torcheck='{"IsTor": false, "IP": "198.51.100.1"}')
    runner = make_runner(fake)
    code = runner.run()
    out = capsys.readouterr().out

    assert code == smoke.EXIT_FAIL
    assert runner.results[smoke.CHECK_EXIT_ROUTING].status == smoke.FAIL
    assert "ALL CHECKS PASSED" not in out
    assert fake.containers == []
    assert runner.results[smoke.CHECK_CLEANUP].status == smoke.PASS


def test_failed_unit_tests_fail_overall_even_if_runtime_passes():
    runner = make_runner(FakeDocker(unit_rc=1))
    assert runner.run() == smoke.EXIT_FAIL
    assert runner.unit_result.status == smoke.FAIL


# ── 3. Docker unavailable ────────────────────────────────────────────────────


def test_docker_unavailable_is_blocked_with_unit_result_reported_separately(capsys):
    fake = FakeDocker(docker_up=False)
    runner = make_runner(fake)
    code = runner.run()
    out = capsys.readouterr().out

    assert code == smoke.EXIT_BLOCKED
    assert runner.results[smoke.CHECK_DOCKER].status == smoke.BLOCKED
    assert runner.results[smoke.CHECK_TOR_HEALTH].status == smoke.BLOCKED
    assert runner.results[smoke.CHECK_API_VERIFY].status == smoke.BLOCKED
    assert runner.unit_result.status == smoke.PASS
    assert "Runtime acceptance: BLOCKED" in out
    assert "Unit tests: PASS" in out
    assert "ALL CHECKS PASSED" not in out
    assert "up" not in fake.compose_subcommands()
    assert "down" not in fake.compose_subcommands()


# ── 4. Blocked by an occupied port or existing resource ─────────────────────


def test_occupied_port_blocks_without_starting_anything(monkeypatch):
    monkeypatch.setattr(smoke, "is_port_free", lambda port: False)
    fake = FakeDocker(existing=DEV_STACK)
    runner = make_runner(fake)

    assert runner.run() == smoke.EXIT_BLOCKED
    assert runner.results[smoke.CHECK_ISOLATION].status == smoke.BLOCKED
    assert "occupied" in runner.results[smoke.CHECK_ISOLATION].detail
    assert not {"build", "up", "down"} & set(fake.compose_subcommands())
    assert not any(c[:2] == ["docker", "pull"] for c in fake.calls)
    assert fake.containers == DEV_STACK


def test_existing_container_name_blocks(monkeypatch):
    fake = FakeDocker()
    runner = make_runner(fake)
    fake.containers.append(("x1", runner.app_container_name, "someone-else"))

    assert runner.run() == smoke.EXIT_BLOCKED
    assert runner.results[smoke.CHECK_ISOLATION].status == smoke.BLOCKED
    assert ("x1", runner.app_container_name, "someone-else") in fake.containers
    assert "down" not in fake.compose_subcommands()


def test_port_conflict_during_startup_is_blocked_and_cleaned_up():
    fake = FakeDocker(up_rc=1, up_creates=("tor",),
                      up_stderr="Bind for 127.0.0.1:41000 failed: port is already allocated")
    runner = make_runner(fake)
    assert runner.run() == smoke.EXIT_BLOCKED
    assert runner.results[smoke.CHECK_STARTUP].status == smoke.BLOCKED
    assert fake.containers == []


# ── 5-7. Live API response validation ────────────────────────────────────────


def test_verify_routing_malformed_json_fails():
    outcome = smoke.validate_verify_routing("200", "<html>not json</html>")
    assert outcome.status == smoke.FAIL and "not valid JSON" in outcome.detail
    assert smoke.validate_verify_routing("200", "[1, 2]").status == smoke.FAIL


def test_verify_routing_200_with_routing_verified_false_fails():
    outcome = smoke.validate_verify_routing("200", json.dumps(UNVERIFIED_BODY))
    assert outcome.status == smoke.FAIL
    assert outcome.retryable
    assert "failed or inconclusive" in outcome.detail


@pytest.mark.parametrize("body, reason", [
    ({k: v for k, v in VERIFIED_BODY.items() if k != "routing_verified"}, "missing field 'routing_verified'"),
    ({k: v for k, v in VERIFIED_BODY.items() if k != "routing_checked"}, "missing field 'routing_checked'"),
    (dict(VERIFIED_BODY, routing_verified="true"), "expected a JSON boolean"),
    (dict(VERIFIED_BODY, state="socks_endpoint_reachable"), "inconsistent"),
    (dict(VERIFIED_BODY, state=None), "inconsistent"),
    (dict(UNVERIFIED_BODY, state="routing_verified"), "inconsistent"),
    (dict(VERIFIED_BODY, routing_checked=False), "routing_checked must be true"),
    (dict(VERIFIED_BODY, socks_reachable=False), "socks_reachable is false"),
    (dict(VERIFIED_BODY, proxy_url="socks5://127.0.0.1:9050"), "proxy_url"),
    (dict(VERIFIED_BODY, status="routing_verified", state="socks_endpoint_reachable"), "inconsistent"),
])
def test_verify_routing_rejects_missing_or_inconsistent_fields(body, reason):
    outcome = smoke.validate_verify_routing("200", json.dumps(body))
    assert outcome.status == smoke.FAIL
    assert reason in outcome.detail


def test_verify_routing_requires_http_200():
    assert smoke.validate_verify_routing("500", json.dumps(VERIFIED_BODY)).status == smoke.FAIL
    assert smoke.validate_verify_routing("000", "").status == smoke.FAIL
    assert smoke.validate_verify_routing("200", json.dumps(VERIFIED_BODY)).status == smoke.PASS


@pytest.mark.parametrize("body, handshake, reason", [
    ("not json", True, "not valid JSON"),
    ({k: v for k, v in DEFAULT_BODY.items() if k != "routing_checked"}, True, "missing field 'routing_checked'"),
    (dict(DEFAULT_BODY, routing_checked=True), True, "routing_checked must be false"),
    (dict(DEFAULT_BODY, routing_verified=True), True, "routing_verified claims"),
    (dict(DEFAULT_BODY, state="routing_verified"), True, "state claims routing_verified"),
    (dict(DEFAULT_BODY, socks_reachable=False), True, "contradicts"),
    (dict(DEFAULT_BODY, socks_reachable=True), False, "contradicts"),
    (dict(DEFAULT_BODY, enabled=False), True, "enabled is false"),
    (dict(DEFAULT_BODY, state="check_failed_or_inconclusive"), True, "expected 'socks_endpoint_reachable'"),
    (dict(DEFAULT_BODY, proxy_url="socks5://host.docker.internal:9050"), True, "proxy_url"),
])
def test_default_status_rejects_malformed_or_inconsistent_state(body, handshake, reason):
    raw = body if isinstance(body, str) else json.dumps(body)
    outcome = smoke.validate_default_status("200", raw, handshake)
    assert outcome.status == smoke.FAIL
    assert reason in outcome.detail


def test_default_status_passes_only_with_matching_handshake():
    body = json.dumps(DEFAULT_BODY)
    assert smoke.validate_default_status("200", body, True).status == smoke.PASS
    assert smoke.validate_default_status("200", body, None).status == smoke.BLOCKED
    assert smoke.validate_default_status("401", body, True).status == smoke.FAIL


def test_auth_rejection_requires_exactly_401():
    assert smoke.validate_auth_rejection("401").status == smoke.PASS
    for code in ("200", "403", "500", "000", ""):
        assert smoke.validate_auth_rejection(code).status == smoke.FAIL


def test_runner_fails_when_live_verify_endpoint_returns_malformed_json():
    fake = FakeDocker(verify_bodies=[(200, "{broken")])
    runner = make_runner(fake)
    assert runner.run() == smoke.EXIT_FAIL
    assert runner.results[smoke.CHECK_API_VERIFY].status == smoke.FAIL
    assert fake.verify_calls == 1  # schema errors are not retried


def test_runner_retries_unverified_routing_then_fails():
    fake = FakeDocker(verify_bodies=[(200, json.dumps(UNVERIFIED_BODY))])
    runner = make_runner(fake, routing_attempts=3)
    assert runner.run() == smoke.EXIT_FAIL
    assert fake.verify_calls == 3
    assert runner.results[smoke.CHECK_API_VERIFY].status == smoke.FAIL


def test_runner_accepts_verification_on_retry():
    fake = FakeDocker(verify_bodies=[(200, json.dumps(UNVERIFIED_BODY)), (200, json.dumps(VERIFIED_BODY))])
    runner = make_runner(fake)
    assert runner.run() == smoke.EXIT_PASS
    assert fake.verify_calls == 2


def test_runner_fails_when_default_status_is_inconsistent():
    fake = FakeDocker(default_body=(200, json.dumps(dict(DEFAULT_BODY, routing_verified=True))))
    runner = make_runner(fake)
    assert runner.run() == smoke.EXIT_FAIL
    assert runner.results[smoke.CHECK_API_DEFAULT].status == smoke.FAIL


# ── 8-10. Partial startup and cleanup ────────────────────────────────────────


def test_partial_compose_startup_then_error_cleans_up_owned_containers():
    fake = FakeDocker(existing=DEV_STACK, up_rc=1, up_creates=("tor",),
                      up_stderr="dependency failed to start: container tor is unhealthy")
    runner = make_runner(fake)
    code = runner.run()

    assert code == smoke.EXIT_FAIL
    assert runner.results[smoke.CHECK_STARTUP].status == smoke.FAIL
    assert runner.results[smoke.CHECK_TOR_HEALTH].status == smoke.BLOCKED
    assert "down" in fake.compose_subcommands()
    assert fake.containers == DEV_STACK
    assert runner.results[smoke.CHECK_CLEANUP].status == smoke.PASS
    assert runner.app_image not in fake.images
    assert_never_destructive(fake)


def test_startup_timeout_after_partial_creation_is_cleaned_up():
    fake = FakeDocker(existing=DEV_STACK, up_timeout=True)
    runner = make_runner(fake)
    assert runner.run() == smoke.EXIT_FAIL
    assert "timed out" in runner.results[smoke.CHECK_STARTUP].detail
    assert fake.containers == DEV_STACK


def test_exception_mid_run_still_cleans_up_and_fails():
    fake = FakeDocker(existing=DEV_STACK, exec_error=ValueError("boom"))
    runner = make_runner(fake)
    assert runner.run() == smoke.EXIT_FAIL
    assert runner.results["Runner internal error"].status == smoke.FAIL
    assert fake.containers == DEV_STACK


def test_cleanup_failure_keeps_original_failure():
    fake = FakeDocker(torcheck='{"IsTor": false}', down_rc=1, down_removes=False)
    runner = make_runner(fake)
    code = runner.run()

    assert code == smoke.EXIT_FAIL
    assert runner.results[smoke.CHECK_EXIT_ROUTING].status == smoke.FAIL
    assert "IsTor" in runner.results[smoke.CHECK_EXIT_ROUTING].detail
    assert runner.results[smoke.CHECK_CLEANUP].status == smoke.FAIL
    assert "still present" in runner.results[smoke.CHECK_CLEANUP].detail


def test_cleanup_crash_keeps_original_failure():
    fake = FakeDocker(torcheck='{"IsTor": false}', ps_fail_on_cleanup=True)
    runner = make_runner(fake)
    assert runner.run() == smoke.EXIT_FAIL
    assert runner.results[smoke.CHECK_EXIT_ROUTING].status == smoke.FAIL
    assert runner.results[smoke.CHECK_CLEANUP].status == smoke.FAIL


def test_cleanup_failure_alone_fails_an_otherwise_passing_run():
    fake = FakeDocker(down_rc=1, down_removes=False)
    runner = make_runner(fake)
    assert runner.run() == smoke.EXIT_FAIL
    assert runner.results[smoke.CHECK_CLEANUP].status == smoke.FAIL


# ── 11. Strict mode removed; always strict ───────────────────────────────────


def test_strict_runtime_flag_is_removed_and_help_documents_exit_codes(capsys):
    with pytest.raises(SystemExit) as exc:
        smoke.build_parser().parse_args(["--strict-runtime"])
    assert exc.value.code == 2
    help_text = smoke.build_parser().format_help()
    for fragment in ("0  PASS", "1  FAIL", "3  BLOCKED", "4  ERROR"):
        assert fragment in help_text


def test_skipping_unit_tests_never_claims_all_checks_passed(capsys):
    runner = make_runner(FakeDocker(), run_unit_tests=False)
    assert runner.run() == smoke.EXIT_PASS
    out = capsys.readouterr().out
    assert "RESULT: ALL CHECKS PASSED" not in out
    assert "ALL REQUIRED RUNTIME CHECKS PASSED (unit tests not run)" in out


# ── 12. Blocked can never yield exit 0 ───────────────────────────────────────


def test_blocked_or_missing_required_check_never_exits_zero():
    all_pass = {name: smoke.Outcome(smoke.PASS) for name in smoke.REQUIRED_RUNTIME_CHECKS}
    assert smoke.classify(all_pass, smoke.Outcome(smoke.PASS)) == (smoke.PASS, 0)
    for name in smoke.REQUIRED_RUNTIME_CHECKS:
        blocked = dict(all_pass, **{name: smoke.Outcome(smoke.BLOCKED)})
        assert smoke.classify(blocked, smoke.Outcome(smoke.PASS))[1] == smoke.EXIT_BLOCKED
        missing = {k: v for k, v in all_pass.items() if k != name}
        assert smoke.classify(missing, smoke.Outcome(smoke.PASS))[1] == smoke.EXIT_BLOCKED
        failed = dict(blocked, **{smoke.CHECK_COMPOSE_CONFIG: smoke.Outcome(smoke.FAIL)})
        assert smoke.classify(failed, None)[1] == smoke.EXIT_FAIL
    assert smoke.classify(all_pass, smoke.Outcome(smoke.BLOCKED))[1] == smoke.EXIT_BLOCKED
    assert smoke.classify({}, None)[1] == smoke.EXIT_BLOCKED


def test_malformed_results_are_an_error_not_success():
    all_pass = {name: smoke.Outcome(smoke.PASS) for name in smoke.REQUIRED_RUNTIME_CHECKS}
    assert smoke.classify(dict(all_pass, extra=smoke.Outcome("SKIPPED")), None)[1] == smoke.EXIT_INTERNAL_ERROR
    assert smoke.classify(dict(all_pass, extra=("PASS", "")), None)[1] == smoke.EXIT_INTERNAL_ERROR
    assert smoke.classify(None, None)[1] == smoke.EXIT_INTERNAL_ERROR


def test_main_returns_error_code_when_runner_crashes(monkeypatch):
    def explode(self):
        raise RuntimeError("crash")

    monkeypatch.setattr(smoke.SmokeTestRunner, "run", explode)
    assert smoke.main([]) == smoke.EXIT_INTERNAL_ERROR


# ── validate-response CLI used by the GitHub Actions workflow ───────────────


def test_validate_response_cli_exit_codes(tmp_path):
    verified = tmp_path / "verified.json"
    verified.write_text(json.dumps(VERIFIED_BODY))
    unverified = tmp_path / "unverified.json"
    unverified.write_text(json.dumps(UNVERIFIED_BODY))
    default = tmp_path / "default.json"
    default.write_text(json.dumps(DEFAULT_BODY))

    assert smoke.main(["validate-response", "verify-routing", "--http-code", "200",
                       "--body-file", str(verified)]) == 0
    assert smoke.main(["validate-response", "verify-routing", "--http-code", "200",
                       "--body-file", str(unverified)]) == 1
    assert smoke.main(["validate-response", "default-status", "--http-code", "200",
                       "--body-file", str(default), "--socks-handshake-ok"]) == 0
    assert smoke.main(["validate-response", "default-status", "--http-code", "200",
                       "--body-file", str(default)]) == smoke.EXIT_BLOCKED
    assert smoke.main(["validate-response", "auth-rejection", "--http-code", "401"]) == 0
    assert smoke.main(["validate-response", "auth-rejection", "--http-code", "200"]) == 1


# ── Ephemeral Tor DataDirectory (no anonymous volume per run) ────────────────


def test_smoke_override_mounts_tor_data_dir_as_tmpfs_only():
    override = yaml.safe_load((ROOT / smoke.SMOKE_OVERRIDE).read_text())
    assert set(override["services"]) == {"tor"}
    tor = override["services"]["tor"]
    assert set(tor) == {"tmpfs"}  # no image, ports, volumes or data mounts changed
    assert tor["tmpfs"] == ["/var/lib/tor:uid=100,gid=101,mode=0700,size=64m"]
    assert tor["tmpfs"][0].split(":", 1)[0] == smoke.TOR_DATA_DIR


def test_pinned_tor_digest_unchanged_and_base_storage_untouched():
    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert base["services"]["tor"]["image"] == smoke.PINNED_IMAGE_DIGEST
    assert smoke.PINNED_IMAGE_DIGEST.endswith(
        "@sha256:ea335859425375b3294b15a5df61ca317ca4fdd143cf7a8d568bb2cd48217774")
    # Only the smoke override adds tmpfs; the dev stack's storage is unchanged.
    assert "tmpfs" not in base["services"]["tor"]
    assert base["services"]["sealapi-lead-research"]["volumes"] == ["${DATA_MOUNT_DIR:-./data}:/app/data"]


def test_every_compose_call_applies_the_smoke_override():
    fake = FakeDocker()
    runner = make_runner(fake)
    assert runner.run() == smoke.EXIT_PASS
    compose_calls = [c for c in fake.calls if c[:2] == ["docker", "compose"]]
    assert compose_calls
    for cmd in compose_calls:
        files = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-f"]
        assert [Path(f).name for f in files] == ["docker-compose.yml", smoke.SMOKE_OVERRIDE]


def test_missing_tmpfs_fails_the_ephemeral_check():
    fake = FakeDocker(tor_tmpfs={})
    runner = make_runner(fake)
    assert runner.run() == smoke.EXIT_FAIL
    assert runner.results[smoke.CHECK_TOR_EPHEMERAL].status == smoke.FAIL
    assert "no tmpfs at /var/lib/tor" in runner.results[smoke.CHECK_TOR_EPHEMERAL].detail


def test_unexpected_anonymous_volume_is_reported_with_evidence_and_never_removed(capsys):
    vol = "a" * 64
    fake = FakeDocker(existing=DEV_STACK, volumes={"tor": [(vol, "/var/lib/tor")]})
    runner = make_runner(fake)
    code = runner.run()
    out = capsys.readouterr().out

    assert code == smoke.EXIT_FAIL
    assert f"{vol} at /var/lib/tor" in runner.results[smoke.CHECK_TOR_EPHEMERAL].detail
    cleanup = runner.results[smoke.CHECK_CLEANUP]
    assert cleanup.status == smoke.PASS  # containers/network removed; the volume is only reported
    assert (f"UNEXPECTED volume(s) kept, not removed: {vol} at /var/lib/tor on {runner.tor_container_name}"
            in cleanup.detail)
    assert f"com.docker.compose.project={runner.project}" in cleanup.detail
    assert "volume rm" not in out
    assert fake.containers == DEV_STACK
    assert_never_destructive(fake)


def test_workflow_passes_both_compose_files_to_every_compose_call():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "tor-runtime-smoke.yml").read_text())
    assert "COMPOSE_FILE" not in workflow["env"]  # path-list separator differs between Linux and Windows
    runs = [step["run"] for step in workflow["jobs"]["tor-smoke-test"]["steps"] if "run" in step]
    calls = [run[i:i + 80] for run in runs for i in range(len(run)) if run.startswith("docker compose", i)]
    assert len(calls) >= 10  # config, build, up, ps, logs, down
    for call in calls:
        assert call.startswith(f"docker compose -f docker-compose.yml -f {smoke.SMOKE_OVERRIDE} "), call


def test_workflow_waits_for_tor_bootstrap_before_routing_and_keeps_diagnostics():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "tor-runtime-smoke.yml").read_text())
    steps = workflow["jobs"]["tor-smoke-test"]["steps"]
    names = [step["name"] for step in steps]
    wait = names.index("Wait for Tor Bootstrap")
    routing = names.index("Container-Context Tor Exit Routing Verification")
    assert wait < routing
    assert "Bootstrapped 100%" in steps[wait]["run"] and "/var/log/tor/notices.log" in steps[wait]["run"]
    assert "curl -sS" in steps[routing]["run"] and "torcheck.err" in steps[routing]["run"]
    logs = next(step["run"] for step in steps if step["name"] == "Collect Container Logs")
    assert "/var/log/tor/notices.log" in logs
