#!/usr/bin/env python3
"""
Repeatable Smoke Test Script for Tor Container Runtime, SOCKS5 Handshake,
and External Exit Routing Verification in SealAPI LeadDetailsScraper.

Requirements:
- Verifies Compose configuration and immutable image digest.
- Checks Docker engine availability.
- Starts Tor container and waits for container health.
- Tests RFC 1928 SOCKS5 handshake.
- Tests application-to-Tor external routing against check.torproject.org.
- Tests protected API endpoints (/api/tor/status).
- Cleans up containers cleanly without touching volumes or review data.
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
from typing import Dict, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

PINNED_IMAGE_DIGEST = "osminogin/tor-simple:0.4.9.14@sha256:ea335859425375b3294b15a5df61ca317ca4fdd143cf7a8d568bb2cd48217774"


class SmokeTestRunner:
    def __init__(self, host: str = "127.0.0.1", port: int = 9050, strict_runtime: bool = False):
        self.host = host
        self.port = port
        self.strict_runtime = strict_runtime
        self.results: Dict[str, Tuple[str, str]] = {}
        self.docker_available = False
        self.containers_started = False

    def log_result(self, check_name: str, status: str, detail: str = ""):
        self.results[check_name] = (status, detail)
        status_colored = f"[{status}]"
        print(f"  {check_name:<45} {status_colored:<10} {detail}")

    def check_compose_config(self) -> bool:
        """Validate docker-compose.yml configuration."""
        try:
            res = subprocess.run(
                ["docker", "compose", "config"],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                # Confirm image digest in config
                if PINNED_IMAGE_DIGEST in res.stdout:
                    self.log_result("1. Compose Config & Immutable Digest", "PASS", "Valid YAML and pinned digest verified")
                    return True
                else:
                    self.log_result("1. Compose Config & Immutable Digest", "FAIL", "Pinned image digest missing from config")
                    return False
            else:
                self.log_result("1. Compose Config & Immutable Digest", "FAIL", res.stderr.strip()[:100])
                return False
        except Exception as exc:
            self.log_result("1. Compose Config & Immutable Digest", "FAIL", str(exc))
            return False

    def check_docker_engine(self) -> bool:
        """Check if Docker daemon is running and reachable."""
        try:
            res = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if res.returncode == 0:
                self.docker_available = True
                self.log_result("2. Docker Engine Availability", "PASS", "Docker daemon is reachable and responding")
                return True
            else:
                err_msg = res.stderr.strip().splitlines()[0] if res.stderr.strip() else "Daemon not connected"
                self.log_result("2. Docker Engine Availability", "BLOCKED", f"Docker daemon offline: {err_msg[:80]}")
                return False
        except Exception as exc:
            self.log_result("2. Docker Engine Availability", "BLOCKED", f"Cannot execute docker info: {str(exc)[:80]}")
            return False

    def check_socks5_handshake(self) -> bool:
        """Perform RFC 1928 SOCKS5 handshake."""
        try:
            with socket.create_connection((self.host, self.port), timeout=3.0) as sock:
                sock.settimeout(3.0)
                sock.sendall(b"\x05\x01\x00")
                resp = sock.recv(2)
                if len(resp) == 2 and resp[0] == 0x05 and resp[1] == 0x00:
                    self.log_result("3. SOCKS5 RFC 1928 Protocol Handshake", "PASS", f"Handshake verified on {self.host}:{self.port}")
                    return True
                else:
                    self.log_result("3. SOCKS5 RFC 1928 Protocol Handshake", "FAIL", f"Unexpected handshake response: {resp!r}")
                    return False
        except Exception as exc:
            if not self.docker_available:
                self.log_result("3. SOCKS5 RFC 1928 Protocol Handshake", "BLOCKED", f"Port unreachable (Docker offline): {str(exc)[:80]}")
            else:
                self.log_result("3. SOCKS5 RFC 1928 Protocol Handshake", "FAIL", f"Connection error: {str(exc)[:80]}")
            return False

    def check_tor_exit_routing(self) -> bool:
        """Perform external Tor routing check via check.torproject.org."""
        try:
            from curl_cffi import requests
            proxy_url = f"socks5://{self.host}:{self.port}"
            with requests.Session(proxy=proxy_url) as session:
                resp = session.get("https://check.torproject.org/api/ip", timeout=12.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict) and (data.get("IsTor") is True or str(data.get("IsTor")).lower() == "true"):
                        exit_ip = data.get("IP", "unknown")
                        self.log_result("4. Verified Tor Exit Routing", "PASS", f"Confirmed Tor exit node (IP: {exit_ip})")
                        return True
                    else:
                        self.log_result("4. Verified Tor Exit Routing", "FAIL", "Response received but IsTor is not true")
                        return False
                else:
                    self.log_result("4. Verified Tor Exit Routing", "FAIL", f"HTTP status {resp.status_code}")
                    return False
        except Exception as exc:
            if not self.docker_available:
                self.log_result("4. Verified Tor Exit Routing", "BLOCKED", f"Cannot route (Docker offline): {str(exc)[:80]}")
            else:
                self.log_result("4. Verified Tor Exit Routing", "FAIL", f"Routing probe failed: {str(exc)[:80]}")
            return False

    def check_protected_api_endpoint(self) -> bool:
        """Test /api/tor/status with missing, invalid, and valid authentication."""
        try:
            from fastapi.testclient import TestClient
            from src.lead_research.server import app

            client = TestClient(app)
            test_secret = "smoke_test_synthetic_secret_12345"

            # Monkeypatch secret safely
            old_secret = os.environ.get("API_SECRET_KEY")
            os.environ["API_SECRET_KEY"] = test_secret
            try:
                import src.lead_research.server as srv
                orig_key = getattr(srv, "API_SECRET_KEY", None)
                srv.API_SECRET_KEY = test_secret

                # 1. Missing auth
                r_missing = client.get("/api/tor/status")
                if r_missing.status_code != 401:
                    self.log_result("5. Protected API Authentication", "FAIL", f"Missing key returned {r_missing.status_code}")
                    return False

                # 2. Invalid auth
                r_invalid = client.get("/api/tor/status", headers={"X-API-Key": "wrong_key"})
                if r_invalid.status_code != 401:
                    self.log_result("5. Protected API Authentication", "FAIL", f"Invalid key returned {r_invalid.status_code}")
                    return False

                # 3. Valid auth without routing
                r_valid = client.get("/api/tor/status", headers={"X-API-Key": test_secret})
                if r_valid.status_code != 200:
                    self.log_result("5. Protected API Authentication", "FAIL", f"Valid key returned {r_valid.status_code}")
                    return False
                body = r_valid.json()
                if "routing_checked" not in body or body.get("routing_checked") is not False:
                    self.log_result("5. Protected API Authentication", "FAIL", "Default call failed to indicate routing_checked: False")
                    return False

                self.log_result("5. Protected API Authentication", "PASS", "Rejected 401 on missing/bad key, accepted 200 with structured status on valid key")
                return True
            finally:
                if orig_key is not None:
                    srv.API_SECRET_KEY = orig_key
                if old_secret is not None:
                    os.environ["API_SECRET_KEY"] = old_secret
                else:
                    os.environ.pop("API_SECRET_KEY", None)
        except Exception as exc:
            self.log_result("5. Protected API Authentication", "FAIL", f"API check error: {str(exc)[:80]}")
            return False

    def run(self) -> int:
        print("=" * 80)
        print("SealAPI Tor Runtime & Docker Smoke Test Runner")
        print("=" * 80)

        # 1. Compose Config
        self.check_compose_config()

        # 2. Docker Engine
        has_docker = self.check_docker_engine()

        if has_docker:
            # Pull pinned image and start container
            print("\nStarting Tor container in background...")
            pull_res = subprocess.run(
                ["docker", "pull", PINNED_IMAGE_DIGEST],
                capture_output=True,
                text=True,
                check=False,
            )
            if pull_res.returncode == 0:
                self.log_result("Tor Image Pull", "PASS", "Pinned digest image verified locally")
            else:
                self.log_result("Tor Image Pull", "FAIL", pull_res.stderr.strip()[:80])

            up_res = subprocess.run(
                ["docker", "compose", "up", "-d", "tor"],
                capture_output=True,
                text=True,
                check=False,
            )
            if up_res.returncode == 0:
                self.containers_started = True
                # Wait for container healthy
                print("Waiting up to 30s for Tor container health check...")
                healthy = False
                for _ in range(15):
                    time.sleep(2)
                    ps_res = subprocess.run(
                        ["docker", "compose", "ps", "--format", "json", "tor"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if "healthy" in ps_res.stdout.lower():
                        healthy = True
                        break
                if healthy:
                    self.log_result("Tor Container Health", "PASS", "Container transitioned to healthy status")
                else:
                    self.log_result("Tor Container Health", "FAIL", "Container did not reach healthy state in 30s")
            else:
                self.log_result("Tor Container Startup", "FAIL", up_res.stderr.strip()[:80])

        # 3. SOCKS5 handshake
        self.check_socks5_handshake()

        # 4. Tor exit routing
        self.check_tor_exit_routing()

        # 5. Protected API endpoint
        self.check_protected_api_endpoint()

        # Cleanup if started
        if self.containers_started:
            print("\nCleaning up smoke-test containers cleanly...")
            subprocess.run(["docker", "compose", "down"], capture_output=True, check=False)

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

        if fails > 0:
            return 1
        if self.strict_runtime and blocked > 0:
            return 2
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tor Runtime Smoke Test Runner")
    parser.add_argument("--strict-runtime", action="store_true", help="Fail if any runtime check is blocked by environment")
    parser.add_argument("--host", default="127.0.0.1", help="SOCKS5 host")
    parser.add_argument("--port", type=int, default=9050, help="SOCKS5 port")
    args = parser.parse_args()

    runner = SmokeTestRunner(host=args.host, port=args.port, strict_runtime=args.strict_runtime)
    sys.exit(runner.run())
