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

    def is_port_open(self, host: str = "127.0.0.1", port: int = 9050, timeout: float = 1.0) -> bool:
        """Check if SOCKS port is listening on target host."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def find_active_tor_port(self) -> Optional[int]:
        """Find an already-running Tor SOCKS port (9050 or 9150)."""
        hosts = ["tor", "127.0.0.1", "host.docker.internal"]
        for h in hosts:
            if self.is_port_open(h, self.preferred_port):
                return self.preferred_port
            for p in DEFAULT_TOR_PORTS:
                if p != self.preferred_port and self.is_port_open(h, p):
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
        active_port = self.find_active_tor_port()
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
                if self.is_port_open("127.0.0.1", self.preferred_port):
                    logger.info(f"Tor SOCKS proxy established successfully on port {self.preferred_port}")
                    return True, f"Tor started successfully on port {self.preferred_port}", self.preferred_port

            return False, "Tor process launched but SOCKS port did not become ready in time", None

        except Exception as e:
            logger.error(f"Failed to start Tor: {e}")
            return False, f"Failed to start Tor: {str(e)}", None

    def get_proxy_url(self) -> Optional[str]:
        """Get formatted SOCKS5 proxy URL for Scrapling, or None if unavailable."""
        if not self.is_enabled():
            return None

        env_proxy = os.getenv("TOR_PROXY")
        if env_proxy:
            # If explicit proxy configured in env, test reachability or return
            return env_proxy

        active_port = self.find_active_tor_port()
        if active_port:
            return f"socks5://127.0.0.1:{active_port}"

        # If inside container, check Compose tor service or host.docker.internal
        for host in ["tor", "host.docker.internal", "172.17.0.1"]:
            if self.is_port_open(host, 9050):
                return f"socks5://{host}:9050"

        success, _, port = self.ensure_tor_running()
        if success and port:
            return f"socks5://127.0.0.1:{port}"
        return None

    def get_status(self) -> Dict[str, Any]:
        """Return status dictionary for API endpoint."""
        enabled = self.is_enabled()
        port = self.find_active_tor_port() if enabled else None
        proxy_url = self.get_proxy_url() if enabled else None
        tor_exe = self.find_tor_executable()
        return {
            "enabled": enabled,
            "is_running": (proxy_url is not None or port is not None) if enabled else False,
            "port": port or 9050,
            "proxy_url": self.sanitize_proxy_url(proxy_url),
            "compose_service": "tor",
            "executable_found": tor_exe is not None,
            "executable_path": str(tor_exe) if tor_exe else None,
        }
