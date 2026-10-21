"""Tor proxy management and lifecycle controller."""

import logging
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("lead_research.tor")

DEFAULT_TOR_PORTS = [9050, 9150]
DEFAULT_TOR_EXE_PATHS = [
    r"C:\Users\menil\Desktop\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
    r"C:\Program Files\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
    r"C:\Program Files (x86)\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
]


STATE_DISABLED = "disabled"
STATE_CONFIGURED_UNREACHABLE = "proxy_configured_unreachable"
STATE_SOCKS_REACHABLE = "socks_endpoint_reachable"
STATE_ROUTING_VERIFIED = "routing_verified"
STATE_CHECK_FAILED = "check_failed_or_inconclusive"


class TorManager:
    """Detects, tests, and optionally spawns local Tor SOCKS proxy for Scrapling scraping."""

    def __init__(self, preferred_port: int = 9050):
        self.preferred_port = preferred_port
        self._process: Optional[subprocess.Popen] = None

    @staticmethod
    def is_enabled() -> bool:
        """Check if Tor routing is enabled via environment."""
        flag = os.getenv("TOR_ENABLED", "true").strip().lower()
        return flag not in ("false", "0", "no", "disabled")

    @staticmethod
    def sanitize_proxy_url(url: Optional[str]) -> Optional[str]:
        """Safely redact credentials in proxy URLs for logging/status."""
        if not url:
            return None
        return re.sub(r"://([^/]+)@", r"://***:***@", url)

    @staticmethod
    def _parse_host_port(url_or_addr: str) -> Tuple[str, int]:
        """Extract host and port from a proxy URL or host:port string."""
        if not url_or_addr:
            return "127.0.0.1", 9050
        cleaned = url_or_addr.strip()
        if "://" in cleaned:
            parsed = urlparse(cleaned)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 9050
            return host, port
        if ":" in cleaned:
            parts = cleaned.split(":")
            host = parts[0] or "127.0.0.1"
            try:
                port = int(parts[1])
            except ValueError:
                port = 9050
            return host, port
        return cleaned, 9050

    def is_port_open(self, host: str = "127.0.0.1", port: int = 9050, timeout: float = 1.0) -> bool:
        """Check if SOCKS port is listening on target host."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def is_socks5_functional(self, host: str = "127.0.0.1", port: int = 9050, timeout: float = 1.0) -> bool:
        """
        Check if target host:port is a responsive SOCKS5 proxy by performing
        a standard RFC 1928 SOCKS5 handshake (greeting: VER=5, NMETHODS=1, METHOD=0).
        Differentiates a functioning SOCKS5 proxy from an arbitrary open TCP listener (HTTP/echo).
        """
        try:
            with socket.create_connection((host, port), timeout=timeout) as sock:
                sock.settimeout(timeout)
                # Client greeting: VER=0x05, NMETHODS=1, METHOD=0x00 (No authentication)
                sock.sendall(b"\x05\x01\x00")
                resp = sock.recv(2)
                # Valid server response: VER=0x05, METHOD=0x00
                return len(resp) == 2 and resp[0] == 0x05 and resp[1] == 0x00
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def find_active_tor_port(self, require_socks5: bool = True) -> Optional[int]:
        """Find an already-running Tor SOCKS port (9050 or 9150) across candidate hostnames."""
        hosts = ["tor", "127.0.0.1", "host.docker.internal"]
        for h in hosts:
            if self.is_port_open(h, self.preferred_port):
                if not require_socks5 or self.is_socks5_functional(h, self.preferred_port):
                    return self.preferred_port
            for p in DEFAULT_TOR_PORTS:
                if p != self.preferred_port and self.is_port_open(h, p):
                    if not require_socks5 or self.is_socks5_functional(h, p):
                        return p
        return None

    def find_tor_executable(self) -> Optional[Path]:
        """Locate tor.exe in standard paths or PATH environment variable."""
        custom_path = os.getenv("TOR_EXE_PATH")
        if custom_path and Path(custom_path).is_file():
            return Path(custom_path)

        for p in DEFAULT_TOR_EXE_PATHS:
            p_obj = Path(p)
            if p_obj.is_file():
                return p_obj

        # Check shutil.which
        which_tor = shutil.which("tor") if hasattr(os, "shutil") else None
        if which_tor:
            return Path(which_tor)

        return None

    def ensure_tor_running(self) -> Tuple[bool, str, Optional[int]]:
        """
        Verify Tor is running, or launch background tor daemon if tor.exe is available.
        Returns: (success: bool, message: str, port: Optional[int])
        """
        active_port = self.find_active_tor_port(require_socks5=True)
        if active_port:
            return True, f"Tor is running and listening on port {active_port}", active_port

        tor_exe = self.find_tor_executable()
        if not tor_exe:
            return False, "Tor is not running and tor.exe was not found in standard paths", None

        data_dir = Path(os.getenv("TEMP", "/tmp")) / "tor_data"
        data_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(tor_exe),
            "--DisableNetwork", "0",
            "--SocksPort", str(self.preferred_port),
            "--DataDirectory", str(data_dir),
            "--Log", "notice stdout",
        ]

        logger.info(f"Launching Tor background daemon: {' '.join(cmd)}")
        try:
            # Creation flags for detached background process on Windows
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )

            # Wait up to 15 seconds for SOCKS port to open
            for _ in range(30):
                time.sleep(0.5)
                if self.is_port_open("127.0.0.1", self.preferred_port) and self.is_socks5_functional("127.0.0.1", self.preferred_port):
                    logger.info(f"Tor SOCKS proxy established successfully on port {self.preferred_port}")
                    return True, f"Tor started successfully on port {self.preferred_port}", self.preferred_port

            return False, "Tor process launched but SOCKS port did not become ready in time", None

        except Exception as e:
            logger.error(f"Failed to start Tor: {e}")
            return False, f"Failed to start Tor: {str(e)}", None

    def verify_tor_routing(self, proxy_url: Optional[str] = None, target_url: str = "http://checkip.amazonaws.com", timeout: float = 3.0) -> bool:
        """
        Test whether a functioning SOCKS endpoint can actually route traffic to the external internet.
        Uses a lightweight HTTP probe via the configured SOCKS proxy.
        """
        proxy = proxy_url or self.get_proxy_url(require_reachable=True)
        if not proxy:
            return False
        try:
            from curl_cffi import requests
            with requests.Session(proxy=proxy) as session:
                resp = session.get(target_url, timeout=timeout)
                return resp.status_code == 200
        except Exception as exc:
            logger.debug(f"Tor routing verification probe failed: {exc}")
            return False

    def get_proxy_url(self, require_reachable: bool = True) -> Optional[str]:
        """
        Get formatted SOCKS5 proxy URL for Scrapling, or None if unavailable.
        If require_reachable=True, verifies that the target endpoint is actually reachable
        and responsive to SOCKS5 greetings, rather than equating configuration with connectivity.
        """
        if not self.is_enabled():
            return None

        env_proxy = os.getenv("TOR_PROXY")
        if env_proxy:
            if not require_reachable:
                return env_proxy
            host, port = self._parse_host_port(env_proxy)
            if self.is_port_open(host, port) and self.is_socks5_functional(host, port):
                return env_proxy
            logger.warning(
                f"Configured TOR_PROXY '{self.sanitize_proxy_url(env_proxy)}' is unreachable "
                f"or failed SOCKS5 handshake at '{host}:{port}'."
            )
            return None

        active_port = self.find_active_tor_port(require_socks5=require_reachable)
        if active_port:
            return f"socks5://127.0.0.1:{active_port}"

        # If inside container, check Compose tor service or host.docker.internal
        for host in ["tor", "host.docker.internal", "172.17.0.1"]:
            if self.is_port_open(host, 9050):
                if not require_reachable or self.is_socks5_functional(host, 9050):
                    return f"socks5://{host}:9050"

        if require_reachable:
            success, _, port = self.ensure_tor_running()
            if success and port:
                return f"socks5://127.0.0.1:{port}"

        return None

    def get_status(self, verify_routing: bool = False) -> Dict[str, Any]:
        """
        Return comprehensive status dictionary for API endpoint with distinct health states:
        - disabled: Tor is disabled via configuration
        - proxy_configured_unreachable: Proxy URL is configured but port cannot be connected
        - socks_endpoint_reachable: TCP port is open and SOCKS5 handshake succeeds
        - routing_verified: SOCKS5 endpoint verified able to route external internet requests
        - check_failed_or_inconclusive: Port is open but not a functioning SOCKS proxy
        """
        enabled = self.is_enabled()
        tor_exe = self.find_tor_executable()
        raw_env_proxy = os.getenv("TOR_PROXY", "").strip() or None

        if not enabled:
            return {
                "enabled": False,
                "state": STATE_DISABLED,
                "is_running": False,
                "socks_reachable": False,
                "routing_verified": False,
                "port": self.preferred_port,
                "proxy_url": None,
                "compose_service": "tor",
                "executable_found": tor_exe is not None,
                "executable_path": str(tor_exe) if tor_exe else None,
                "details": "Tor proxy is disabled via TOR_ENABLED environment variable.",
            }

        # Check configured proxy or candidate
        candidate_proxy = raw_env_proxy
        if not candidate_proxy:
            active_p = self.find_active_tor_port(require_socks5=False)
            if active_p:
                candidate_proxy = f"socks5://127.0.0.1:{active_p}"
            else:
                candidate_proxy = f"socks5://tor:{self.preferred_port}"

        host, port = self._parse_host_port(candidate_proxy)
        port_open = self.is_port_open(host, port)

        if not port_open:
            return {
                "enabled": True,
                "state": STATE_CONFIGURED_UNREACHABLE,
                "is_running": False,
                "socks_reachable": False,
                "routing_verified": False,
                "port": port,
                "proxy_url": self.sanitize_proxy_url(raw_env_proxy or candidate_proxy),
                "compose_service": "tor",
                "executable_found": tor_exe is not None,
                "executable_path": str(tor_exe) if tor_exe else None,
                "details": f"Proxy configured as '{self.sanitize_proxy_url(candidate_proxy)}', but host '{host}:{port}' is unreachable.",
            }

        socks_valid = self.is_socks5_functional(host, port)
        if not socks_valid:
            return {
                "enabled": True,
                "state": STATE_CHECK_FAILED,
                "is_running": False,
                "socks_reachable": False,
                "routing_verified": False,
                "port": port,
                "proxy_url": self.sanitize_proxy_url(raw_env_proxy or candidate_proxy),
                "compose_service": "tor",
                "executable_found": tor_exe is not None,
                "executable_path": str(tor_exe) if tor_exe else None,
                "details": f"TCP port '{host}:{port}' is open, but SOCKS5 protocol handshake failed (not a valid SOCKS5 proxy).",
            }

        # SOCKS handshake succeeded
        is_routed = False
        if verify_routing:
            is_routed = self.verify_tor_routing(candidate_proxy)

        current_state = STATE_ROUTING_VERIFIED if is_routed else STATE_SOCKS_REACHABLE

        return {
            "enabled": True,
            "state": current_state,
            "is_running": True,
            "socks_reachable": True,
            "routing_verified": is_routed,
            "port": port,
            "proxy_url": self.sanitize_proxy_url(candidate_proxy),
            "compose_service": "tor",
            "executable_found": tor_exe is not None,
            "executable_path": str(tor_exe) if tor_exe else None,
            "details": f"SOCKS5 proxy is listening and responsive on '{host}:{port}'" + (" with verified Tor routing." if is_routed else "."),
        }
