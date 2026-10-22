#!/usr/bin/env python3
"""
Standalone runtime acceptance test for the Tor container, SOCKS5 proxy, Tor
exit routing, and the live /api/tor/status endpoint of SealAPI LeadDetailsScraper.

This script owns a complete, isolated lifecycle and is meant for local use:

- Creates a uniquely named Compose project for this invocation, with unique
  container names, a unique application image tag, free ephemeral host ports,
  and a temporary data directory (the repository's data/ is never mounted).
- Refuses to start (BLOCKED) if any resource with those names already exists or
  a chosen port is occupied. It never touches a pre-existing development stack.
- Pulls the pinned Tor image, builds the app image, starts both services, and
  waits for health with bounded timeouts. docker-compose.smoke.yml keeps Tor's
  DataDirectory in tmpfs, so the image's VOLUME creates no persistent volume.
- Verifies the application's configured proxy, the SOCKS5 handshake from the
  application container and from the host, Tor exit routing (IsTor: true) from
  the application container, and the live API's authentication and response
  semantics for both the default status and ?verify_routing=true.
- Cleans up only resources labelled with this invocation's Compose project, even
  after partial startup or an exception. Never removes volumes, never prunes.

The GitHub Actions workflow (.github/workflows/tor-runtime-smoke.yml) runs its own
service lifecycle and does NOT invoke this lifecycle. It only reuses the
``validate-response`` subcommand, which never starts, stops, or removes anything.
"""

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent

PINNED_IMAGE_DIGEST = "osminogin/tor-simple:0.4.9.14@sha256:ea335859425375b3294b15a5df61ca317ca4fdd143cf7a8d568bb2cd48217774"
TOR_SERVICE = "tor"
# Smoke-only override that keeps Tor's DataDirectory (the image's VOLUME) in tmpfs.
SMOKE_OVERRIDE = "docker-compose.smoke.yml"
TOR_DATA_DIR = "/var/lib/tor"
APP_SERVICE = "sealapi-lead-research"
# Proxy URL as seen from inside the Compose network (the app container's context).
CONTAINER_TOR_PROXY = "socks5://tor:9050"
TOR_CHECK_URL = "https://check.torproject.org/api/ip"
STATUS_URL = "http://127.0.0.1:8000/api/tor/status"
VERIFY_URL = STATUS_URL + "?verify_routing=true"
PROJECT_LABEL = "com.docker.compose.project"

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
VALID_STATUSES = (PASS, FAIL, BLOCKED)

EXIT_PASS = 0
EXIT_FAIL = 1
# 2 is reserved for argparse usage errors.
EXIT_BLOCKED = 3
EXIT_INTERNAL_ERROR = 4

EXIT_CODE_HELP = """\
exit codes:
  0  PASS     every required runtime acceptance check executed and passed
  1  FAIL     at least one executed check failed (including cleanup or unit checks)
  2  usage    invalid command-line arguments (argparse)
  3  BLOCKED  a required check could not execute (e.g. Docker unavailable,
              occupied port, existing resource name); nothing failed
  4  ERROR    the runner itself crashed or produced malformed results

Unit-test results are reported separately and never turn a BLOCKED or FAILED
runtime acceptance into success.
"""

# Required runtime acceptance checks, in execution order. A check that is never
# recorded is treated as BLOCKED, so skipping a check can never yield PASS.
CHECK_COMPOSE_CONFIG = "Compose config & pinned Tor digest"
CHECK_DOCKER = "Docker engine availability"
CHECK_ISOLATION = "Isolation preflight (names, ports)"
CHECK_PULL = "Pinned Tor image pull"
CHECK_BUILD = "Application image build"
CHECK_STARTUP = "Service startup"
CHECK_TOR_HEALTH = "Tor container health"
CHECK_TOR_EPHEMERAL = "Tor data dir is tmpfs (no volume)"
CHECK_APP_HEALTH = "Application container health"
CHECK_APP_PROXY = "App proxy configuration"
CHECK_SOCKS_CONTAINER = "SOCKS5 handshake (app container -> tor:9050)"
CHECK_SOCKS_HOST = "SOCKS5 handshake (host -> published port)"
CHECK_EXIT_ROUTING = "Tor exit routing from app container (IsTor)"
CHECK_API_MISSING = "API /tor/status missing key -> 401"
CHECK_API_INVALID = "API /tor/status invalid key -> 401"
CHECK_API_DEFAULT = "API /tor/status valid key (default)"
CHECK_API_VERIFY_MISSING = "API ?verify_routing missing key -> 401"
CHECK_API_VERIFY_INVALID = "API ?verify_routing invalid key -> 401"
CHECK_API_VERIFY = "API ?verify_routing valid key (Tor verified)"
CHECK_CLEANUP = "Cleanup of this invocation's resources"

REQUIRED_RUNTIME_CHECKS: Tuple[str, ...] = (
    CHECK_COMPOSE_CONFIG,
    CHECK_DOCKER,
    CHECK_ISOLATION,
    CHECK_PULL,
    CHECK_BUILD,
    CHECK_STARTUP,
    CHECK_TOR_HEALTH,
    CHECK_TOR_EPHEMERAL,
    CHECK_APP_HEALTH,
    CHECK_APP_PROXY,
    CHECK_SOCKS_CONTAINER,
    CHECK_SOCKS_HOST,
    CHECK_EXIT_ROUTING,
    CHECK_API_MISSING,
    CHECK_API_INVALID,
    CHECK_API_DEFAULT,
    CHECK_API_VERIFY_MISSING,
    CHECK_API_VERIFY_INVALID,
    CHECK_API_VERIFY,
    CHECK_CLEANUP,
)

CHECK_UNIT = "Unit tests (mocked; not runtime evidence)"

UNIT_TEST_TARGETS = (
    "tests/test_smoke_tor_runtime.py",
    "tests/test_api.py::test_tor_status_requires_authorization_and_returns_structured_health",
)


@dataclass
class Outcome:
    status: str
    detail: str = ""
    retryable: bool = False


# ── Pure response validators (shared with the GitHub Actions workflow) ────────


def _parse_json_object(body: str) -> Tuple[Optional[dict], str]:
    try:
        data = json.loads(body)
    except (TypeError, ValueError) as exc:
        return None, f"response body is not valid JSON ({type(exc).__name__})"
    if not isinstance(data, dict):
        return None, f"response JSON is {type(data).__name__}, expected object"
    return data, ""


def _require_bool(data: dict, key: str) -> Optional[str]:
    if key not in data:
        return f"missing field '{key}'"
    if not isinstance(data[key], bool):
        return f"field '{key}' is {data[key]!r}, expected a JSON boolean"
    return None


def validate_auth_rejection(http_code: str) -> Outcome:
    """A request without a valid key must be rejected with exactly HTTP 401."""
    if http_code == "401":
        return Outcome(PASS, "rejected with HTTP 401")
    return Outcome(FAIL, f"expected HTTP 401, got HTTP {http_code or '<none>'}")


def validate_default_status(
    http_code: str,
    body: str,
    handshake_ok: Optional[bool],
    expected_proxy: str = CONTAINER_TOR_PROXY,
) -> Outcome:
    """
    Validate GET /api/tor/status (no verify_routing) against the schema produced
    by TorManager.get_status(). ``handshake_ok`` is the independently observed
    SOCKS5 handshake result from the same network context as the application.
    """
    if http_code != "200":
        return Outcome(FAIL, f"expected HTTP 200, got HTTP {http_code or '<none>'}")
    data, err = _parse_json_object(body)
    if data is None:
        return Outcome(FAIL, err)
    for key in ("enabled", "socks_reachable", "routing_checked", "routing_verified"):
        err = _require_bool(data, key)
        if err:
            return Outcome(FAIL, err)
    if data["enabled"] is not True:
        return Outcome(FAIL, "enabled is false; TOR_ENABLED must be true for acceptance")
    if data["routing_checked"] is not False:
        return Outcome(FAIL, "routing_checked must be false when verify_routing is not requested")
    if data["routing_verified"] is not False:
        return Outcome(FAIL, "routing_verified claims verification although routing was not checked")
    state = data.get("state")
    if state == "routing_verified":
        return Outcome(FAIL, "state claims routing_verified although routing was not checked")
    if handshake_ok is None:
        return Outcome(BLOCKED, "independent SOCKS5 handshake result unavailable; cannot cross-check socks_reachable")
    if data["socks_reachable"] is not handshake_ok:
        return Outcome(
            FAIL,
            f"socks_reachable={data['socks_reachable']} contradicts observed handshake result {handshake_ok}",
        )
    if not handshake_ok:
        return Outcome(FAIL, "SOCKS5 proxy is unreachable (consistent with API, but acceptance requires it)")
    if state != "socks_endpoint_reachable":
        return Outcome(FAIL, f"state is {state!r}, expected 'socks_endpoint_reachable'")
    if data.get("proxy_url") != expected_proxy:
        return Outcome(FAIL, f"proxy_url is {data.get('proxy_url')!r}, expected {expected_proxy!r}")
    return Outcome(PASS, "200; socks_reachable=true, routing_checked=false, routing_verified=false")


def validate_verify_routing(
    http_code: str,
    body: str,
    expected_proxy: str = CONTAINER_TOR_PROXY,
) -> Outcome:
    """
    Validate GET /api/tor/status?verify_routing=true. Only an explicit positive
    Tor verification (routing_verified=true, state=routing_verified) passes.
    """
    if http_code != "200":
        return Outcome(FAIL, f"expected HTTP 200, got HTTP {http_code or '<none>'}")
    data, err = _parse_json_object(body)
    if data is None:
        return Outcome(FAIL, err)
    for key in ("enabled", "socks_reachable", "routing_checked", "routing_verified"):
        err = _require_bool(data, key)
        if err:
            return Outcome(FAIL, err)
    if data["routing_checked"] is not True:
        return Outcome(FAIL, "routing_checked must be true when verify_routing=true")
    if data["socks_reachable"] is not True:
        return Outcome(FAIL, "socks_reachable is false; proxy unreachable from the application")
    state = data.get("state")
    if data["routing_verified"] is not True:
        if state == "routing_verified":
            return Outcome(FAIL, "inconsistent: state=routing_verified but routing_verified=false")
        return Outcome(
            FAIL,
            f"external Tor verification failed or inconclusive (routing_verified=false, state={state!r})",
            retryable=True,
        )
    if state != "routing_verified":
        return Outcome(FAIL, f"inconsistent: routing_verified=true but state={state!r}")
    if data.get("proxy_url") != expected_proxy:
        return Outcome(FAIL, f"proxy_url is {data.get('proxy_url')!r}, expected {expected_proxy!r}")
    return Outcome(PASS, "200; routing_checked=true, routing_verified=true, state=routing_verified")


def validate_tor_check_response(body: str) -> Outcome:
    """Validate the check.torproject.org/api/ip response: IsTor must be JSON true."""
    data, err = _parse_json_object(body)
    if data is None:
        return Outcome(FAIL, f"Tor check endpoint: {err}", retryable=True)
    if data.get("IsTor") is not True:
        return Outcome(FAIL, f"IsTor is {data.get('IsTor')!r}, expected true", retryable=True)
    return Outcome(PASS, "IsTor=true")


def classify(results: Dict[str, Outcome], unit: Optional[Outcome]) -> Tuple[str, int]:
    """
    Combine results into (label, exit_code). Precedence: FAIL > BLOCKED > PASS.
    Any required check that is missing or has an unknown status is never PASS.
    """
    if not isinstance(results, dict):
        return "ERROR", EXIT_INTERNAL_ERROR
    for name, outcome in results.items():
        if not isinstance(outcome, Outcome) or outcome.status not in VALID_STATUSES:
            return "ERROR", EXIT_INTERNAL_ERROR
    statuses = [results[name].status if name in results else BLOCKED for name in REQUIRED_RUNTIME_CHECKS]
    statuses += [outcome.status for name, outcome in results.items() if name not in REQUIRED_RUNTIME_CHECKS]
    if unit is not None:
        if not isinstance(unit, Outcome) or unit.status not in VALID_STATUSES:
            return "ERROR", EXIT_INTERNAL_ERROR
        statuses.append(unit.status)
    if FAIL in statuses:
        return FAIL, EXIT_FAIL
    if BLOCKED in statuses:
        return BLOCKED, EXIT_BLOCKED
    return PASS, EXIT_PASS


# ── Runner ────────────────────────────────────────────────────────────────────

Executor = Callable[..., subprocess.CompletedProcess]


def _default_executor(cmd: Sequence[str], timeout: float, env: Optional[Dict[str, str]] = None
                      ) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd), capture_output=True, text=True, check=False, timeout=timeout,
        cwd=str(ROOT_DIR), env=env, stdin=subprocess.DEVNULL,
    )


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def host_socks5_handshake(port: int, timeout: float = 5.0) -> Tuple[bool, str]:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"\x05\x01\x00")
            resp = sock.recv(2)
    except OSError as exc:
        return False, f"connection error: {type(exc).__name__}"
    if resp == b"\x05\x00":
        return True, f"VER=5 METHOD=0 on 127.0.0.1:{port}"
    return False, f"unexpected handshake response {resp!r}"


class SmokeTestRunner:
    """Runs the full isolated lifecycle. All external effects go through ``executor``."""

    def __init__(
        self,
        executor: Executor = _default_executor,
        sleep: Callable[[float], None] = time.sleep,
        run_unit_tests: bool = True,
        routing_attempts: int = 3,
    ):
        self._exec_fn = executor
        self._sleep = sleep
        self.run_unit_tests = run_unit_tests
        self.routing_attempts = max(1, routing_attempts)

        suffix = uuid.uuid4().hex[:10]
        self.project = f"tor-smoke-{suffix}"
        self.tor_container_name = f"{self.project}-tor"
        self.app_container_name = f"{self.project}-app"
        self.app_image = f"sealapi-lead-research:{self.project}"
        self.api_key = secrets.token_hex(24)
        self.session_secret = secrets.token_hex(32)
        self.ports: Dict[str, int] = {}
        self.data_dir: Optional[str] = None

        self.results: Dict[str, Outcome] = {}
        self.unit_result: Optional[Outcome] = None
        self.startup_attempted = False
        self.image_created = False
        self.app_container_id: Optional[str] = None
        self.handshake_ok: Optional[bool] = None

    # ── helpers ──

    def _redact(self, text: str) -> str:
        text = text or ""
        for secret in (self.api_key, self.session_secret):
            if secret:
                text = text.replace(secret, "***")
        return text

    def record(self, name: str, status: str, detail: str = "") -> None:
        detail = self._redact(detail).replace("\n", " ").strip()
        self.results[name] = Outcome(status, detail)
        print(f"  [{status:<7}] {name}: {detail}", flush=True)

    def _exec(self, cmd: Sequence[str], timeout: float = 30, env: Optional[Dict[str, str]] = None
              ) -> subprocess.CompletedProcess:
        """Run a command; a timeout becomes a failed result (exit 124) instead of an exception."""
        try:
            return self._exec_fn(cmd, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(list(cmd), 124, "", f"timed out after {int(timeout)}s")

    def compose_env(self) -> Dict[str, str]:
        """Environment for every compose call. Overrides any host or .env values."""
        if not self.data_dir or set(self.ports) != {"tor", "backend", "frontend"}:
            # Without these, compose would fall back to ./data and the fixed dev ports.
            raise RuntimeError("isolated resources not allocated; refusing to run docker compose")
        env = os.environ.copy()
        env.update({
            "TOR_CONTAINER_NAME": self.tor_container_name,
            "APP_CONTAINER_NAME": self.app_container_name,
            "APP_IMAGE": self.app_image,
            "HOST_IP": "127.0.0.1",
            "TOR_HOST_PORT": str(self.ports["tor"]),
            "BACKEND_PORT": str(self.ports["backend"]),
            "FRONTEND_PORT": str(self.ports["frontend"]),
            "DATA_MOUNT_DIR": self.data_dir,
            "APP_ENV": "production",
            "API_SECRET_KEY": self.api_key,
            "SESSION_SECRET": self.session_secret,
            "TOR_ENABLED": "true",
            "TOR_PROXY": CONTAINER_TOR_PROXY,
        })
        env.pop("COMPOSE_PROJECT_NAME", None)
        env.pop("COMPOSE_FILE", None)
        return env

    def compose(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
        return self._exec(
            ["docker", "compose", "-p", self.project, "-f", str(ROOT_DIR / "docker-compose.yml"),
             "-f", str(ROOT_DIR / SMOKE_OVERRIDE), *args],
            timeout=timeout, env=self.compose_env(),
        )

    @staticmethod
    def _last_line(res: subprocess.CompletedProcess) -> str:
        text = (res.stderr or "").strip() or (res.stdout or "").strip()
        return text.splitlines()[-1][:160] if text else f"exit {res.returncode}"

    def list_containers(self) -> List[Tuple[str, str, str]]:
        """Return (id, name, compose project label) for all containers, or raise."""
        res = self._exec(
            ["docker", "ps", "-a", "--no-trunc", "--format",
             '{{.ID}}\t{{.Names}}\t{{.Label "%s"}}' % PROJECT_LABEL],
            timeout=20,
        )
        if res.returncode != 0:
            raise RuntimeError(f"docker ps failed: {self._last_line(res)}")
        rows = []
        for line in (res.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                rows.append((parts[0], parts[1], parts[2]))
        return rows

    def owned_containers(self) -> List[Tuple[str, str, str]]:
        return [row for row in self.list_containers() if row[2] == self.project]

    def image_exists(self, ref: str) -> bool:
        return self._exec(["docker", "image", "inspect", ref], timeout=20).returncode == 0

    def app_exec(self, *args: str, timeout: float = 30) -> subprocess.CompletedProcess:
        return self._exec(["docker", "exec", self.app_container_id or "", *args], timeout=timeout)

    def _block_remaining(self, reason: str) -> None:
        for name in REQUIRED_RUNTIME_CHECKS:
            if name != CHECK_CLEANUP and name not in self.results:
                self.record(name, BLOCKED, f"not executed: {reason}")

    # ── checks ──

    def check_docker_engine(self) -> bool:
        try:
            res = self._exec(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=15)
        except (OSError, subprocess.SubprocessError) as exc:
            self.record(CHECK_DOCKER, BLOCKED, f"cannot execute docker: {type(exc).__name__}: {exc}")
            return False
        if res.returncode != 0:
            self.record(CHECK_DOCKER, BLOCKED, f"Docker daemon unavailable: {self._last_line(res)}")
            return False
        self.record(CHECK_DOCKER, PASS, f"server version {res.stdout.strip()}")
        return True

    def allocate_resources(self) -> None:
        self.ports = {"tor": find_free_port(), "backend": find_free_port(), "frontend": find_free_port()}
        self.data_dir = tempfile.mkdtemp(prefix=f"{self.project}-data-")

    def check_compose_config(self) -> bool:
        try:
            res = self.compose("config", timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            self.record(CHECK_COMPOSE_CONFIG, BLOCKED, f"cannot execute docker compose: {type(exc).__name__}")
            return False
        if res.returncode != 0:
            self.record(CHECK_COMPOSE_CONFIG, FAIL, self._last_line(res))
            return False
        out = res.stdout or ""
        missing = [s for s in (PINNED_IMAGE_DIGEST, self.tor_container_name, self.app_container_name,
                               self.app_image, f"- {TOR_DATA_DIR}:") if s not in out]
        if missing:
            self.record(CHECK_COMPOSE_CONFIG, FAIL, f"resolved config missing: {', '.join(missing)}")
            return False
        self.record(CHECK_COMPOSE_CONFIG, PASS, "valid; pinned digest, per-invocation names, Tor tmpfs resolved")
        return True

    def check_isolation(self) -> bool:
        problems = []
        try:
            for _, name, label in self.list_containers():
                if name in (self.tor_container_name, self.app_container_name):
                    problems.append(f"container name '{name}' already exists")
                if label == self.project:
                    problems.append(f"container '{name}' already belongs to project {self.project}")
            if self.image_exists(self.app_image):
                problems.append(f"image tag {self.app_image} already exists")
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            self.record(CHECK_ISOLATION, BLOCKED, f"cannot inspect existing resources: {exc}")
            return False
        for role, port in self.ports.items():
            if not is_port_free(port):
                problems.append(f"{role} host port {port} is occupied")
        if problems:
            self.record(CHECK_ISOLATION, BLOCKED, "; ".join(problems) + " (nothing was started)")
            return False
        self.record(CHECK_ISOLATION, PASS,
                    f"project {self.project}; ports tor={self.ports['tor']} backend={self.ports['backend']} "
                    f"frontend={self.ports['frontend']}; temp data dir")
        return True

    def pull_tor_image(self) -> bool:
        res = self._exec(["docker", "pull", PINNED_IMAGE_DIGEST], timeout=300)
        if res.returncode != 0:
            self.record(CHECK_PULL, FAIL, self._last_line(res))
            return False
        self.record(CHECK_PULL, PASS, "pinned digest pulled")
        return True

    def build_app_image(self) -> bool:
        # The tag is unique to this invocation and was verified absent, so any
        # image present under it afterwards was created here.
        self.startup_attempted = True
        try:
            res = self.compose("build", APP_SERVICE, timeout=3600)
        finally:
            try:
                self.image_created = self.image_exists(self.app_image)
            except (OSError, subprocess.SubprocessError):
                pass
        if res.returncode != 0:
            self.record(CHECK_BUILD, FAIL, self._last_line(res))
            return False
        self.record(CHECK_BUILD, PASS, f"built {self.app_image}")
        return True

    def start_services(self) -> bool:
        self.startup_attempted = True
        res = self.compose("up", "-d", "--no-build", TOR_SERVICE, APP_SERVICE, timeout=300)
        if res.returncode != 0:
            msg = self._last_line(res)
            if "port is already allocated" in msg or "address already in use" in msg:
                self.record(CHECK_STARTUP, BLOCKED, f"host port conflict during startup: {msg}")
            else:
                self.record(CHECK_STARTUP, FAIL, msg)
            return False
        self.record(CHECK_STARTUP, PASS, "compose up -d succeeded")
        return True

    def _container_id(self, service: str) -> Optional[str]:
        res = self.compose("ps", "-a", "-q", service, timeout=30)
        cid = (res.stdout or "").strip().splitlines()
        return cid[0].strip() if res.returncode == 0 and cid else None

    def wait_healthy(self, check_name: str, service: str, timeout: float, interval: float = 3.0) -> bool:
        cid = self._container_id(service)
        if not cid:
            self.record(check_name, FAIL, f"no container found for service {service}")
            return False
        waited = 0.0
        state = "unknown"
        while waited < timeout:
            res = self._exec(["docker", "inspect", "--format",
                              "{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{end}}", cid],
                             timeout=15)
            state = (res.stdout or "").strip() or "unknown"
            if state.endswith("/healthy"):
                self.record(check_name, PASS, f"healthy after ~{int(waited)}s")
                return True
            if state.startswith(("exited", "dead")):
                break
            self._sleep(interval)
            waited += interval
        self.record(check_name, FAIL, f"not healthy within {int(timeout)}s (last state {state})")
        self.print_logs(service)
        return False

    def check_tor_ephemeral(self) -> bool:
        """The Tor DataDirectory must be tmpfs and the image's VOLUME must not have produced a volume."""
        cid = self._container_id(TOR_SERVICE)
        res = self._exec(["docker", "inspect", "--format", "{{json .HostConfig.Tmpfs}}|{{json .Mounts}}", cid or ""],
                         timeout=15)
        try:
            tmpfs_json, mounts_json = (res.stdout or "").strip().split("|", 1)
            tmpfs, mounts = json.loads(tmpfs_json) or {}, json.loads(mounts_json) or []
        except ValueError:
            self.record(CHECK_TOR_EPHEMERAL, FAIL, f"could not inspect Tor mounts: {self._last_line(res)}")
            return False
        volumes = [f"{m.get('Name')} at {m.get('Destination')}" for m in mounts if m.get("Type") == "volume"]
        if TOR_DATA_DIR not in tmpfs:
            self.record(CHECK_TOR_EPHEMERAL, FAIL, f"no tmpfs at {TOR_DATA_DIR}; mounts: {volumes or 'none'}")
            return False
        if volumes:
            self.record(CHECK_TOR_EPHEMERAL, FAIL, f"Tor container has volume mount(s): {', '.join(volumes)}")
            return False
        self.record(CHECK_TOR_EPHEMERAL, PASS, f"tmpfs at {TOR_DATA_DIR} ({tmpfs[TOR_DATA_DIR]}); no volume mounts")
        return True

    def check_app_proxy_config(self) -> bool:
        res = self.app_exec("printenv", "TOR_PROXY", "TOR_ENABLED", timeout=15)
        values = (res.stdout or "").strip().splitlines()
        if res.returncode != 0 or len(values) != 2:
            self.record(CHECK_APP_PROXY, FAIL, f"could not read app proxy env: {self._last_line(res)}")
            return False
        proxy, enabled = values[0].strip(), values[1].strip().lower()
        if proxy != CONTAINER_TOR_PROXY or enabled != "true":
            self.record(CHECK_APP_PROXY, FAIL,
                        f"app has TOR_PROXY={proxy!r} TOR_ENABLED={enabled!r}; expected {CONTAINER_TOR_PROXY!r}/true")
            return False
        self.record(CHECK_APP_PROXY, PASS, f"TOR_PROXY={proxy} TOR_ENABLED=true")
        return True

    def check_container_socks5(self) -> bool:
        probe = (
            "import socket\n"
            "s=socket.create_connection(('tor',9050),timeout=5)\n"
            "s.settimeout(5)\n"
            "s.sendall(b'\\x05\\x01\\x00')\n"
            "print(s.recv(2).hex())\n"
        )
        res = self.app_exec("python3", "-c", probe, timeout=20)
        reply = (res.stdout or "").strip()
        self.handshake_ok = res.returncode == 0 and reply == "0500"
        if self.handshake_ok:
            self.record(CHECK_SOCKS_CONTAINER, PASS, "VER=5 METHOD=0 from app container")
            return True
        self.record(CHECK_SOCKS_CONTAINER, FAIL, f"reply={reply or '<none>'} {self._last_line(res)}")
        return False

    def check_host_socks5(self) -> bool:
        ok, detail = host_socks5_handshake(self.ports["tor"])
        self.record(CHECK_SOCKS_HOST, PASS if ok else FAIL, detail)
        return ok

    def check_exit_routing(self) -> bool:
        outcome = Outcome(FAIL, "not attempted")
        for attempt in range(1, self.routing_attempts + 1):
            res = self.app_exec("curl", "-s", "--max-time", "30", "--socks5-hostname", "tor:9050",
                                TOR_CHECK_URL, timeout=45)
            if res.returncode != 0:
                outcome = Outcome(FAIL, f"curl via Tor failed: {self._last_line(res)}", retryable=True)
            else:
                outcome = validate_tor_check_response(res.stdout or "")
            if outcome.status == PASS or not outcome.retryable:
                break
            if attempt < self.routing_attempts:
                self._sleep(10)
        self.record(CHECK_EXIT_ROUTING, outcome.status, f"{outcome.detail} (attempt {attempt}/{self.routing_attempts})")
        return outcome.status == PASS

    def container_http(self, url: str, api_key: Optional[str]) -> Tuple[str, str]:
        """Request ``url`` from inside the app container; returns (http_code, body)."""
        cmd = ["curl", "-s", "--max-time", "60", "-w", "\n%{http_code}"]
        if api_key is not None:
            cmd += ["-H", f"X-API-Key: {api_key}"]
        res = self.app_exec(*cmd, url, timeout=75)
        out = res.stdout or ""
        if "\n" not in out:
            return "000", out
        body, code = out.rsplit("\n", 1)
        return code.strip() or "000", body

    def check_live_api(self) -> None:
        bad_key = "invalid-" + secrets.token_hex(8)
        for name, url, key in (
            (CHECK_API_MISSING, STATUS_URL, None),
            (CHECK_API_INVALID, STATUS_URL, bad_key),
            (CHECK_API_VERIFY_MISSING, VERIFY_URL, None),
            (CHECK_API_VERIFY_INVALID, VERIFY_URL, bad_key),
        ):
            code, _ = self.container_http(url, key)
            outcome = validate_auth_rejection(code)
            self.record(name, outcome.status, outcome.detail)

        code, body = self.container_http(STATUS_URL, self.api_key)
        outcome = validate_default_status(code, body, self.handshake_ok)
        self.record(CHECK_API_DEFAULT, outcome.status, outcome.detail)

        for attempt in range(1, self.routing_attempts + 1):
            code, body = self.container_http(VERIFY_URL, self.api_key)
            outcome = validate_verify_routing(code, body)
            if outcome.status == PASS or not outcome.retryable:
                break
            if attempt < self.routing_attempts:
                self._sleep(10)
        self.record(CHECK_API_VERIFY, outcome.status, f"{outcome.detail} (attempt {attempt}/{self.routing_attempts})")

    def print_logs(self, service: Optional[str] = None) -> None:
        args = ["logs", "--no-color", "--tail=40"] + ([service] if service else [])
        try:
            res = self.compose(*args, timeout=30)
            print(self._redact((res.stdout or "") + (res.stderr or "")), flush=True)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"  (could not collect logs: {type(exc).__name__})", flush=True)

    def check_unit_tests(self) -> None:
        try:
            res = self._exec([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *UNIT_TEST_TARGETS],
                             timeout=600)
        except (OSError, subprocess.SubprocessError) as exc:
            self.unit_result = Outcome(BLOCKED, f"could not run pytest: {type(exc).__name__}")
        else:
            summary = self._last_line(res)
            self.unit_result = Outcome(PASS if res.returncode == 0 else FAIL, summary)
        print(f"  [{self.unit_result.status:<7}] {CHECK_UNIT}: {self.unit_result.detail}", flush=True)

    # ── cleanup ──

    def cleanup(self) -> None:
        """
        Remove only what this invocation created. Ownership is established by the
        Compose project label, whose name is unique to this invocation and was
        verified unused before startup. Never uses -v, prune, or name patterns.
        """
        problems: List[str] = []
        removed = 0
        kept_volumes: List[str] = []  # "<volume> at <destination> on <container>"
        if self.startup_attempted:
            try:
                owned = self.owned_containers()
                removed = len(owned)
                if owned:
                    self.print_logs()
                    # Any volume on an owned container is unexpected (Tor's is tmpfs); report, never remove.
                    res = self._exec(["docker", "inspect", "--format",
                                      '{{.Name}}|{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}}@{{.Destination}} '
                                      '{{end}}{{end}}', *[row[0] for row in owned]], timeout=20)
                    for line in (res.stdout or "").splitlines() if res.returncode == 0 else []:
                        container, _, vols = line.partition("|")
                        for vol in vols.split():
                            name, _, dest = vol.partition("@")
                            kept_volumes.append(f"{name} at {dest} on {container.lstrip('/')}")
                res = self.compose("down", "--remove-orphans", "--timeout", "20", timeout=180)
                if res.returncode != 0:
                    problems.append(f"compose down failed: {self._last_line(res)}")
                leftover = self.owned_containers()
                if leftover:
                    problems.append("containers still present: " + ", ".join(r[1] for r in leftover))
            except Exception as exc:  # cleanup must never mask the primary result
                problems.append(f"container cleanup error: {type(exc).__name__}: {exc}")
            if self.image_created:
                try:
                    res = self._exec(["docker", "image", "rm", self.app_image], timeout=120)
                    if res.returncode != 0:
                        problems.append(f"could not remove image {self.app_image}: {self._last_line(res)}")
                except Exception as exc:
                    problems.append(f"image cleanup error: {type(exc).__name__}")
        if self.data_dir:
            shutil.rmtree(self.data_dir, ignore_errors=True)
            if os.path.exists(self.data_dir):
                print(f"  note: temporary data dir not fully removed: {self.data_dir}", flush=True)
        kept = ""
        if kept_volumes:
            kept = (f"; UNEXPECTED volume(s) kept, not removed: {'; '.join(kept_volumes)} "
                    f"(attached to containers labelled {PROJECT_LABEL}={self.project}, created during this run)")
            print(f"  warning: {kept[2:]}", flush=True)
        if problems:
            self.record(CHECK_CLEANUP, FAIL, "; ".join(problems) + kept)
        elif self.startup_attempted:
            self.record(CHECK_CLEANUP, PASS,
                        f"removed {removed} owned container(s) and project network; no volumes removed{kept}")
        elif CHECK_CLEANUP not in self.results:
            self.record(CHECK_CLEANUP, BLOCKED, "nothing was started; cleanup not exercised")

    # ── orchestration ──

    def _run_runtime(self) -> None:
        self.allocate_resources()
        config_ok = self.check_compose_config()
        if not self.check_docker_engine():
            self._block_remaining("Docker engine unavailable")
            return
        if not config_ok:
            self._block_remaining("Compose configuration check did not pass")
            return
        if not self.check_isolation():
            self._block_remaining("isolation preflight did not pass")
            return
        if not self.pull_tor_image():
            self._block_remaining("Tor image pull failed")
            return
        if not self.build_app_image():
            self._block_remaining("application image build failed")
            return
        if not self.start_services():
            self._block_remaining("service startup did not complete")
            return
        if not self.wait_healthy(CHECK_TOR_HEALTH, TOR_SERVICE, timeout=120):
            self._block_remaining("Tor container unhealthy")
            return
        self.check_tor_ephemeral()
        if not self.wait_healthy(CHECK_APP_HEALTH, APP_SERVICE, timeout=180, interval=5.0):
            self._block_remaining("application container unhealthy")
            return
        self.app_container_id = self._container_id(APP_SERVICE)
        if not self.app_container_id:
            self._block_remaining("application container id unavailable")
            return
        self.check_app_proxy_config()
        self.check_container_socks5()
        self.check_host_socks5()
        self.check_exit_routing()
        self.check_live_api()

    def run(self) -> int:
        print("=" * 80)
        print("SealAPI Tor Runtime Acceptance Test (standalone lifecycle)")
        print("=" * 80)
        print(f"  Project: {self.project}  (app proxy: {CONTAINER_TOR_PROXY})\n", flush=True)

        try:
            try:
                self._run_runtime()
            except Exception as exc:
                self.record("Runner internal error", FAIL, f"{type(exc).__name__}: {exc}")
                self._block_remaining("runner error")
            finally:
                try:
                    self.cleanup()
                except Exception as exc:
                    self.record(CHECK_CLEANUP, FAIL, f"cleanup crashed: {type(exc).__name__}")
            if self.run_unit_tests:
                try:
                    self.check_unit_tests()
                except Exception as exc:
                    self.unit_result = Outcome(FAIL, f"unit runner crashed: {type(exc).__name__}")
            return self.report()
        except Exception as exc:
            print(f"RESULT: ERROR (runner failure: {type(exc).__name__})")
            return EXIT_INTERNAL_ERROR

    def report(self) -> int:
        label, code = classify(self.results, self.unit_result)
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        counts = {PASS: 0, FAIL: 0, BLOCKED: 0}
        for name in REQUIRED_RUNTIME_CHECKS:
            outcome = self.results.get(name, Outcome(BLOCKED, "not executed"))
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            print(f"  [{outcome.status:<7}] {name}: {outcome.detail}")
        for name, outcome in self.results.items():
            if name not in REQUIRED_RUNTIME_CHECKS:
                print(f"  [{outcome.status:<7}] {name}: {outcome.detail}")
        print("-" * 80)
        runtime_label, _ = classify(self.results, None)
        print(f"Runtime acceptance: {runtime_label}  "
              f"(required {len(REQUIRED_RUNTIME_CHECKS)}: passed {counts[PASS]}, "
              f"failed {counts[FAIL]}, blocked {counts[BLOCKED]})")
        unit = self.unit_result
        print(f"Unit tests: {unit.status + ' - ' + unit.detail if unit else 'NOT RUN'}")
        if label == PASS and unit is not None:
            print("RESULT: ALL CHECKS PASSED")
        elif label == PASS:
            print("RESULT: ALL REQUIRED RUNTIME CHECKS PASSED (unit tests not run)")
        elif label == BLOCKED:
            print("RESULT: BLOCKED (required runtime checks could not execute; not a success)")
        elif label == FAIL:
            print("RESULT: FAILED")
        else:
            print("RESULT: ERROR (malformed results)")
        print(f"Exit code: {code}")
        return code


# ── CLI ───────────────────────────────────────────────────────────────────────


def _validate_cli(args: argparse.Namespace) -> int:
    body = ""
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8", errors="replace")
    if args.kind == "auth-rejection":
        outcome = validate_auth_rejection(args.http_code)
    elif args.kind == "default-status":
        outcome = validate_default_status(args.http_code, body, True if args.socks_handshake_ok else None,
                                          args.expected_proxy)
    else:
        outcome = validate_verify_routing(args.http_code, body, args.expected_proxy)
    print(f"[{outcome.status}] {args.kind}: {outcome.detail}")
    return {PASS: EXIT_PASS, FAIL: EXIT_FAIL, BLOCKED: EXIT_BLOCKED}[outcome.status]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standalone Tor runtime acceptance test. Without a subcommand, runs the full "
                    "isolated lifecycle (start, verify, clean up). Always strict: blocked checks never pass.",
        epilog=EXIT_CODE_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--skip-unit-tests", action="store_true",
                        help="do not run the mocked unit tests after the runtime checks")
    sub = parser.add_subparsers(dest="command")
    val = sub.add_parser(
        "validate-response",
        help="validate one /api/tor/status response (verification only; never touches Docker)",
        epilog="exit codes: 0 PASS, 1 FAIL, 3 BLOCKED",
    )
    val.add_argument("kind", choices=["auth-rejection", "default-status", "verify-routing"])
    val.add_argument("--http-code", required=True)
    val.add_argument("--body-file", help="file containing the response body")
    val.add_argument("--expected-proxy", default=CONTAINER_TOR_PROXY)
    val.add_argument("--socks-handshake-ok", action="store_true",
                     help="the SOCKS5 handshake from the app's network context was independently verified")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate-response":
        return _validate_cli(args)
    try:
        return SmokeTestRunner(run_unit_tests=not args.skip_unit_tests).run()
    except Exception as exc:
        print(f"RESULT: ERROR (runner failure: {type(exc).__name__})")
        return EXIT_INTERNAL_ERROR


if __name__ == "__main__":
    sys.exit(main())
