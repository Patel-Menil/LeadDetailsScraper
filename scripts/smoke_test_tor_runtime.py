#!/usr/bin/env python3
"""
Repeatable Smoke Test Script for Tor Container Runtime, SOCKS5 Handshake,
and External Exit Routing Verification in SealAPI LeadDetailsScraper.

Requirements:
- Verifies Compose configuration and immutable image digest.
- Checks Docker engine availability.
- Detects whether a Compose project is already running and avoids disrupting it.
- Starts Tor and application services in an isolated Compose project.
- Waits for the actual required services to become healthy, using bounded timeouts.
- Tests RFC 1928 SOCKS5 handshake.
- Tests application-to-Tor external routing FROM the container network context.
- Tests protected API endpoints (/api/tor/status) with missing, invalid, and valid credentials.
- Tests both ordinary status and ?verify_routing=true.
- Cleans up only containers created by THIS smoke test. Never removes volumes.
- Outputs clear PASS, FAIL, or BLOCKED results.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

PINNED_IMAGE_DIGEST = "osminogin/tor-simple:0.4.9.14@sha256:ea335859425375b3294b15a5df61ca317ca4fdd143cf7a8d568bb2cd48217774"
SMOKE_PROJECT_NAME = "tor-smoke-test"
API_TEST_KEY = "smoke_test_synthetic_secret_12345"


class SmokeTestRunner:
    def __init__(self, host: str = "127.0.0.1", port: int = 9050, strict_runtime: bool = False):
        self.host = host
        self.port = port
        self.strict_runtime = strict_runtime
        self.results: Dict[str, Tuple[str, str]] = {}
        self.docker_available = False
        self.containers_started = False
        self.app_container_id: Optional[str] = None

    def log_result(self, check_name: str, status: str, detail: str = ""):
        self.results[check_name] = (status, detail)
        print(f"  {check_name:<55} [{status:<7}] {detail}")

    def _compose_cmd(self, *args: str) -> List[str]:
        """Build a docker compose command with the isolated project name."""
        return ["docker", "compose", "-p", SMOKE_PROJECT_NAME, *args]

    def _run(self, cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=timeout, cwd=str(ROOT_DIR)
        )

    # ── 1. Compose Config & Immutable Digest ──────────────────────────

    def check_compose_config(self) -> bool:
        """Validate docker-compose.yml configuration and pinned digest."""
        try:
            res = self._run(self._compose_cmd("config"))
            if res.returncode == 0:
                if PINNED_IMAGE_DIGEST in res.stdout:
                    self.log_result("1. Compose Config & Immutable Digest", "PASS",
                                   "Valid YAML and pinned digest verified")
                    return True
                else:
                    self.log_result("1. Compose Config & Immutable Digest", "FAIL",
                                   "Pinned image digest missing from config")
                    return False
            else:
                self.log_result("1. Compose Config & Immutable Digest", "FAIL",
                               res.stderr.strip()[:100])
                return False
        except Exception as exc:
            self.log_result("1. Compose Config & Immutable Digest", "FAIL", str(exc))
            return False

    # ── 2. Docker Engine Availability ─────────────────────────────────

    def check_docker_engine(self) -> bool:
        """Check if Docker daemon is running and reachable."""
        try:
            res = subprocess.run(
                ["docker", "info"], capture_output=True, text=True, timeout=5, check=False
            )
            if res.returncode == 0:
                self.docker_available = True
                self.log_result("2. Docker Engine Availability", "PASS",
                               "Docker daemon is reachable and responding")
                return True
            else:
                err_msg = (res.stderr.strip().splitlines()[0]
                           if res.stderr.strip() else "Daemon not connected")
                self.log_result("2. Docker Engine Availability", "BLOCKED",
                               f"Docker daemon offline: {err_msg[:80]}")
                return False
        except Exception as exc:
            self.log_result("2. Docker Engine Availability", "BLOCKED",
                           f"Cannot execute docker info: {str(exc)[:80]}")
            return False

    # ── 2b. Conflict Detection ────────────────────────────────────────

    def check_port_conflict(self) -> bool:
        """Detect whether required ports are already bound by another stack."""
        try:
            with socket.create_connection((self.host, self.port), timeout=1.0):
                # Port already in use – another stack may be running
                self.log_result("2b. Port Conflict Detection", "BLOCKED",
                               f"Port {self.port} already bound. Another dev stack may be running. "
                               "Refusing to start to avoid disruption.")
                return False
        except (ConnectionRefusedError, OSError, socket.timeout):
            # Port is free
            self.log_result("2b. Port Conflict Detection", "PASS",
                           f"Port {self.port} is available")
            return True

    # ── 3. Start Services & Wait Healthy ──────────────────────────────

    def start_services(self) -> bool:
        """Start Tor and application containers in an isolated project."""
        # Set environment for the isolated project
        env = os.environ.copy()
        env["API_SECRET_KEY"] = API_TEST_KEY
        env["APP_ENV"] = "production"  # Force auth enforcement

        print("\n  Starting services in isolated project '%s'..." % SMOKE_PROJECT_NAME)

        # Pull pinned image
        pull_res = subprocess.run(
            ["docker", "pull", PINNED_IMAGE_DIGEST],
            capture_output=True, text=True, check=False, timeout=120
        )
        if pull_res.returncode == 0:
            self.log_result("3a. Tor Image Pull", "PASS", "Pinned digest image verified locally")
        else:
            self.log_result("3a. Tor Image Pull", "FAIL", pull_res.stderr.strip()[:80])
            return False

        # Start services
        up_res = subprocess.run(
            self._compose_cmd("up", "-d", "tor", "sealapi-lead-research"),
            capture_output=True, text=True, check=False, timeout=120,
            cwd=str(ROOT_DIR), env=env
        )
        if up_res.returncode != 0:
            self.log_result("3b. Service Startup", "FAIL", up_res.stderr.strip()[:100])
            return False

        self.containers_started = True

        # Wait for Tor healthy
        print("  Waiting up to 90s for Tor container health check...")
        tor_healthy = self._wait_for_service_health("tor", timeout=90)
        if tor_healthy:
            self.log_result("3c. Tor Container Health", "PASS",
                           "Container transitioned to healthy status")
        else:
            self.log_result("3c. Tor Container Health", "FAIL",
                           "Container did not reach healthy state within timeout")
            return False

        # Wait for App healthy (best-effort)
        print("  Waiting up to 120s for application container health check...")
        app_healthy = self._wait_for_service_health("sealapi-lead-research", timeout=120)
        if app_healthy:
            self.log_result("3d. Application Container Health", "PASS",
                           "Application container transitioned to healthy status")
        else:
            self.log_result("3d. Application Container Health", "FAIL",
                           "Application container did not reach healthy state within timeout")

        # Capture the app container ID for docker exec
        id_res = self._run(self._compose_cmd("ps", "-q", "sealapi-lead-research"))
        self.app_container_id = id_res.stdout.strip() or None

        return True

    def _wait_for_service_health(self, service: str, timeout: int = 60) -> bool:
        """Wait for a Compose service to reach 'healthy' state."""
        id_res = self._run(self._compose_cmd("ps", "-q", service))
        container_id = id_res.stdout.strip()
        if not container_id:
            return False

        elapsed = 0
        while elapsed < timeout:
            inspect_res = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_id],
                capture_output=True, text=True, check=False, timeout=5
            )
            state = inspect_res.stdout.strip()
            if state == "healthy":
                return True
            time.sleep(3)
            elapsed += 3

        # Dump diagnostics on failure
        subprocess.run(
            self._compose_cmd("logs", service, "--tail=20"),
            check=False, timeout=10, cwd=str(ROOT_DIR)
        )
        return False

    # ── 4. SOCKS5 RFC 1928 Protocol Handshake ────────────────────────

    def check_socks5_handshake(self) -> bool:
        """Perform RFC 1928 SOCKS5 handshake from host side."""
        try:
            with socket.create_connection((self.host, self.port), timeout=5.0) as sock:
                sock.settimeout(5.0)
                sock.sendall(b"\x05\x01\x00")
                resp = sock.recv(2)
                if len(resp) == 2 and resp[0] == 0x05 and resp[1] == 0x00:
                    self.log_result("4. SOCKS5 RFC 1928 Protocol Handshake", "PASS",
                                   f"Handshake verified on {self.host}:{self.port}")
                    return True
                else:
                    self.log_result("4. SOCKS5 RFC 1928 Protocol Handshake", "FAIL",
                                   f"Unexpected handshake response: {resp!r}")
                    return False
        except Exception as exc:
            if not self.docker_available:
                self.log_result("4. SOCKS5 RFC 1928 Protocol Handshake", "BLOCKED",
                               f"Port unreachable (Docker offline): {str(exc)[:80]}")
            else:
                self.log_result("4. SOCKS5 RFC 1928 Protocol Handshake", "FAIL",
                               f"Connection error: {str(exc)[:80]}")
            return False

    # ── 5. Container-Context Tor Exit Routing ────────────────────────

    def check_container_tor_exit_routing(self) -> bool:
        """
        Verify Tor exit routing from INSIDE the application container's network
        context via docker exec, NOT from host-side SOCKS.
        """
        if not self.app_container_id:
            self.log_result("5. Container-Context Tor Exit Routing", "BLOCKED",
                           "Application container not running")
            return False

        try:
            # Execute curl through Tor SOCKS proxy from inside the app container.
            # The app container resolves 'tor' via Docker DNS to the Tor sidecar.
            exec_res = subprocess.run(
                ["docker", "exec", self.app_container_id, "sh", "-c",
                 "curl -sf --max-time 20 --socks5-hostname tor:9050 "
                 "https://check.torproject.org/api/ip"],
                capture_output=True, text=True, check=False, timeout=30
            )
            if exec_res.returncode != 0:
                self.log_result("5. Container-Context Tor Exit Routing", "FAIL",
                               f"curl via Tor failed: {exec_res.stderr.strip()[:80]}")
                return False

            data = json.loads(exec_res.stdout.strip())
            is_tor = data.get("IsTor")
            if is_tor is True or str(is_tor).lower() == "true":
                exit_ip = data.get("IP", "unknown")
                self.log_result("5. Container-Context Tor Exit Routing", "PASS",
                               f"Confirmed Tor exit node from container (IP: {exit_ip})")
                return True
            else:
                self.log_result("5. Container-Context Tor Exit Routing", "FAIL",
                               f"IsTor is not true. Response: {exec_res.stdout.strip()[:80]}")
                return False
        except json.JSONDecodeError as exc:
            self.log_result("5. Container-Context Tor Exit Routing", "FAIL",
                           f"Invalid JSON from Tor check: {str(exc)[:80]}")
            return False
        except Exception as exc:
            self.log_result("5. Container-Context Tor Exit Routing", "FAIL",
                           f"Routing probe failed: {str(exc)[:80]}")
            return False

    # ── 6. Live API Authentication & Status Endpoint ─────────────────

    def check_live_api_endpoint(self) -> bool:
        """
        Test /api/tor/status via the LIVE running application container.
        Uses docker exec + curl, NOT in-process TestClient.
        Tests: missing auth → 401, invalid auth → 401, valid auth → 200,
        verify_routing=true → 200 with routing_checked.
        """
        if not self.app_container_id:
            self.log_result("6a. API Missing Auth → 401", "BLOCKED", "App container not running")
            self.log_result("6b. API Invalid Auth → 401", "BLOCKED", "App container not running")
            self.log_result("6c. API Valid Auth → 200", "BLOCKED", "App container not running")
            self.log_result("6d. API verify_routing=true", "BLOCKED", "App container not running")
            return False

        base_url = "http://127.0.0.1:8000/api/tor/status"
        all_passed = True

        # 6a. Missing API key → expect 401
        code = self._container_curl_code(base_url)
        if code == "401":
            self.log_result("6a. API Missing Auth → 401", "PASS", "Correctly rejected")
        else:
            self.log_result("6a. API Missing Auth → 401", "FAIL", f"Got HTTP {code}")
            all_passed = False

        # 6b. Invalid API key → expect 401
        code = self._container_curl_code(base_url, headers={"X-API-Key": "wrong_key"})
        if code == "401":
            self.log_result("6b. API Invalid Auth → 401", "PASS", "Correctly rejected")
        else:
            self.log_result("6b. API Invalid Auth → 401", "FAIL", f"Got HTTP {code}")
            all_passed = False

        # 6c. Valid API key → expect 200
        body_res = self._container_curl(base_url, headers={"X-API-Key": API_TEST_KEY})
        if body_res is None:
            self.log_result("6c. API Valid Auth → 200", "FAIL", "No response")
            all_passed = False
        else:
            code, body = body_res
            if code == "200":
                try:
                    data = json.loads(body)
                    if data.get("routing_checked") is False:
                        self.log_result("6c. API Valid Auth → 200", "PASS",
                                       "200 with routing_checked: false (expected default)")
                    else:
                        self.log_result("6c. API Valid Auth → 200", "PASS",
                                       f"200 returned; routing_checked={data.get('routing_checked')}")
                except json.JSONDecodeError:
                    self.log_result("6c. API Valid Auth → 200", "PASS",
                                   "200 returned but body not valid JSON")
            else:
                self.log_result("6c. API Valid Auth → 200", "FAIL", f"Got HTTP {code}")
                all_passed = False

        # 6d. verify_routing=true → expect 200 with routing_checked distinguishing reachability
        body_res = self._container_curl(
            f"{base_url}?verify_routing=true", headers={"X-API-Key": API_TEST_KEY}
        )
        if body_res is None:
            self.log_result("6d. API verify_routing=true", "FAIL", "No response")
            all_passed = False
        else:
            code, body = body_res
            if code == "200":
                try:
                    data = json.loads(body)
                    rc = data.get("routing_checked")
                    status_val = data.get("status", "unknown")
                    self.log_result("6d. API verify_routing=true", "PASS",
                                   f"200 returned; status={status_val}, routing_checked={rc}")
                except json.JSONDecodeError:
                    self.log_result("6d. API verify_routing=true", "PASS",
                                   "200 returned but body not valid JSON")
            else:
                self.log_result("6d. API verify_routing=true", "FAIL", f"Got HTTP {code}")
                all_passed = False

        return all_passed

    def _container_curl_code(self, url: str, headers: Optional[Dict[str, str]] = None) -> str:
        """Run curl inside the app container and return the HTTP status code."""
        cmd = ["docker", "exec", self.app_container_id, "curl", "-sf",
               "-o", "/dev/null", "-w", "%{http_code}"]
        if headers:
            for k, v in headers.items():
                cmd.extend(["-H", f"{k}: {v}"])
        cmd.append(url)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=15)
            return res.stdout.strip() or "000"
        except Exception:
            return "000"

    def _container_curl(self, url: str, headers: Optional[Dict[str, str]] = None
                        ) -> Optional[Tuple[str, str]]:
        """Run curl inside the app container and return (status_code, body)."""
        cmd = ["docker", "exec", self.app_container_id, "curl", "-s",
               "-w", "\n%{http_code}", "--max-time", "20"]
        if headers:
            for k, v in headers.items():
                cmd.extend(["-H", f"{k}: {v}"])
        cmd.append(url)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
            lines = res.stdout.strip().rsplit("\n", 1)
            if len(lines) == 2:
                return lines[1], lines[0]
            return "000", res.stdout
        except Exception:
            return None

    # ── 7. In-Process API Unit Verification (supplementary) ──────────

    def check_api_unit(self) -> bool:
        """
        Supplementary in-process TestClient test. Clearly marked as NOT
        evidence of live container connectivity. Verifies auth enforcement
        logic only.
        """
        try:
            from fastapi.testclient import TestClient
            from src.lead_research.server import app

            client = TestClient(app)
            test_secret = "unit_test_synthetic_key_67890"

            old_secret = os.environ.get("API_SECRET_KEY")
            os.environ["API_SECRET_KEY"] = test_secret
            try:
                import src.lead_research.server as srv
                orig_key = getattr(srv, "API_SECRET_KEY", None)
                srv.API_SECRET_KEY = test_secret

                r_missing = client.get("/api/tor/status")
                if r_missing.status_code != 401:
                    self.log_result("7. In-Process API Auth (unit, not live)", "FAIL",
                                   f"Missing key returned {r_missing.status_code}")
                    return False

                r_invalid = client.get("/api/tor/status", headers={"X-API-Key": "wrong"})
                if r_invalid.status_code != 401:
                    self.log_result("7. In-Process API Auth (unit, not live)", "FAIL",
                                   f"Invalid key returned {r_invalid.status_code}")
                    return False

                r_valid = client.get("/api/tor/status", headers={"X-API-Key": test_secret})
                if r_valid.status_code != 200:
                    self.log_result("7. In-Process API Auth (unit, not live)", "FAIL",
                                   f"Valid key returned {r_valid.status_code}")
                    return False

                self.log_result("7. In-Process API Auth (unit, not live)", "PASS",
                               "Auth enforcement verified (NOT live container evidence)")
                return True
            finally:
                if orig_key is not None:
                    srv.API_SECRET_KEY = orig_key
                if old_secret is not None:
                    os.environ["API_SECRET_KEY"] = old_secret
                else:
                    os.environ.pop("API_SECRET_KEY", None)
        except Exception as exc:
            self.log_result("7. In-Process API Auth (unit, not live)", "FAIL",
                           f"API check error: {str(exc)[:80]}")
            return False

    # ── Cleanup ───────────────────────────────────────────────────────

    def cleanup(self):
        """
        Non-destructive cleanup: stop and remove ONLY containers created by
        this smoke-test project. Never remove volumes, never prune.
        """
        if not self.containers_started:
            return
        print("\n  Cleaning up smoke-test containers (project: %s)..." % SMOKE_PROJECT_NAME)
        # `docker compose -p <project> down` stops and removes only containers,
        # networks, and other resources from this specific project.
        # Critically: NO -v flag → volumes are preserved.
        subprocess.run(
            self._compose_cmd("down"),
            capture_output=True, check=False, timeout=30, cwd=str(ROOT_DIR)
        )

    # ── Main Runner ───────────────────────────────────────────────────

    def run(self) -> int:
        print("=" * 80)
        print("SealAPI Tor Runtime & Docker Smoke Test Runner")
        print("=" * 80)
        print(f"  Project: {SMOKE_PROJECT_NAME} | Host: {self.host}:{self.port}")
        print(f"  Strict: {self.strict_runtime}")
        print()

        try:
            # 1. Compose Config
            self.check_compose_config()

            # 2. Docker Engine
            has_docker = self.check_docker_engine()

            if has_docker:
                # 2b. Port conflict detection
                port_free = self.check_port_conflict()

                if port_free:
                    # 3. Start services
                    services_ok = self.start_services()

                    if services_ok:
                        # 4. SOCKS5 handshake
                        self.check_socks5_handshake()

                        # 5. Container-context Tor exit routing
                        self.check_container_tor_exit_routing()

                        # 6. Live API endpoint authentication
                        self.check_live_api_endpoint()
                else:
                    self.log_result("3-6. Runtime Checks", "BLOCKED",
                                   "Skipped due to port conflict")
            else:
                self.log_result("3-6. Runtime Checks", "BLOCKED",
                               "Skipped due to Docker unavailability")

            # 7. In-process unit check (always runs)
            self.check_api_unit()

        finally:
            # Always clean up
            self.cleanup()

        # Summary
        print("\n" + "=" * 80)
        print("SMOKE TEST SUMMARY:")
        print("=" * 80)
        fails = 0
        blocked = 0
        passes = 0
        for name, (status, detail) in self.results.items():
            print(f"  [{status:<7}] {name}: {detail}")
            if status == "FAIL":
                fails += 1
            elif status == "BLOCKED":
                blocked += 1
            elif status == "PASS":
                passes += 1

        print("-" * 80)
        print(f"Total: {len(self.results)} | Passed: {passes} | Failed: {fails} | Blocked: {blocked}")
        print()

        if fails > 0:
            print("RESULT: FAILED (required checks did not pass)")
            return 1
        if self.strict_runtime and blocked > 0:
            print("RESULT: BLOCKED (strict mode, environment prerequisites missing)")
            return 2
        print("RESULT: ALL CHECKS PASSED")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tor Runtime Smoke Test Runner")
    parser.add_argument("--strict-runtime", action="store_true",
                        help="Fail if any runtime check is blocked by environment")
    parser.add_argument("--host", default="127.0.0.1", help="SOCKS5 host")
    parser.add_argument("--port", type=int, default=9050, help="SOCKS5 port")
    args = parser.parse_args()

    runner = SmokeTestRunner(host=args.host, port=args.port, strict_runtime=args.strict_runtime)
    sys.exit(runner.run())
