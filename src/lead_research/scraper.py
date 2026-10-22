"""Web extraction with Scrapling: SSRF-safe page fetches and DuckDuckGo person search (optionally via Tor)."""

import ipaddress
import logging
import os
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, unquote, urljoin, urlparse

from curl_cffi import CurlOpt
from curl_cffi.requests import Session
from scrapling import Fetcher
from scrapling.engines.toolbelt.convertor import ResponseFactory
try:
    from scrapling import StealthyFetcher
    HAS_STEALTHY_FETCHER = True
except ImportError:
    HAS_STEALTHY_FETCHER = False

from .tor_manager import TorManager

logger = logging.getLogger("lead_research.scraper")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 SealAPIResearchBot/1.0"
)
MAX_REDIRECTS = 5

# Ranges the ipaddress flags miss: CGNAT (RFC 6598), benchmarking (RFC 2544), IETF assignments, "this network".
_EXTRA_BLOCKED_V4 = [ipaddress.IPv4Network(n) for n in ("100.64.0.0/10", "198.18.0.0/15", "192.0.0.0/24", "0.0.0.0/8")]
_INTERNAL_HOSTS = ("localhost", "metadata.google.internal", "instance-data")
_INTERNAL_SUFFIXES = (".local", ".internal", ".lan", ".localhost", ".home", ".corp")


@dataclass
class ScrapeResult:
    """Outcome of fetching one page."""

    url: str
    status_code: int = 0
    success: bool = False
    title: str = ""
    meta_description: str = ""
    headings: List[str] = field(default_factory=list)
    extracted_text: str = ""
    error: str = ""
    engine: str = "scrapling_fetcher"
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def _parse_ip(value: str) -> Any:
    """Parse an IP address, unwrapping IPv4-mapped IPv6 (::ffff:a.b.c.d)."""
    ip = ipaddress.ip_address(value)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip


def _is_blocked_ip(ip: Any) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or (ip.version == 4 and any(ip in net for net in _EXTRA_BLOCKED_V4))
    )


def resolve_and_validate_destination(
    url: str,
    resolve_dns: bool = True,
) -> Tuple[bool, str, str, int, List[str]]:
    """
    SSRF check for an outbound URL: http(s) only, no credentials, no internal hostnames,
    and every resolved address must be public (mixed public/private DNS answers fail closed).
    Returns (is_safe, reason, hostname, port, approved_ips).
    """
    if not url or not url.startswith(("http://", "https://")):
        return False, "SSRF Protection: Invalid or missing HTTP/HTTPS scheme", "", 0, []

    try:
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            return False, "SSRF Protection: URL credentials are not permitted.", "", 0, []
        hostname = parsed.hostname
        if not hostname:
            return False, "Missing hostname in URL", "", 0, []
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        host = hostname.lower().strip(".")

        try:
            literal = _parse_ip(host)
        except ValueError:
            literal = None
        if literal is not None:
            if _is_blocked_ip(literal):
                return False, f"SSRF Protection: Access to private/reserved IP {hostname} is blocked.", host, port, []
            return True, "", host, port, [str(literal)]

        if host in _INTERNAL_HOSTS or host.endswith(_INTERNAL_SUFFIXES):
            return False, f"SSRF Protection: Access to local/internal host '{hostname}' is blocked.", host, port, []
        if not resolve_dns:
            return True, "", host, port, []

        try:
            addr_info = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
            approved_ips: List[str] = []
            for *_, sockaddr in addr_info:
                resolved = _parse_ip(sockaddr[0])
                if _is_blocked_ip(resolved):
                    return False, f"SSRF Protection: Hostname '{hostname}' resolves to private/reserved IP {sockaddr[0]}.", host, port, []
                approved_ips.append(str(resolved))
        except socket.gaierror as exc:
            return False, f"SSRF Protection: DNS resolution failed for hostname '{hostname}': {exc}", host, port, []
        except Exception as exc:
            return False, f"SSRF Protection: DNS check failed for hostname '{hostname}': {exc}", host, port, []
        if not approved_ips:
            return False, f"SSRF Protection: DNS resolution returned no addresses for hostname '{hostname}'.", host, port, []
        return True, "", host, port, list(dict.fromkeys(approved_ips))
    except Exception as e:
        return False, f"Malformed URL: {e}", "", 0, []


def is_safe_url(url: str, resolve_dns: bool = True) -> Tuple[bool, str]:
    """SSRF check returning only (is_safe, reason)."""
    safe, reason, _, _, _ = resolve_and_validate_destination(url, resolve_dns=resolve_dns)
    return safe, reason


def format_curl_resolve_entry(host: str, port: int, approved_ips: List[str]) -> str:
    """
    Build a libcurl CURLOPT_RESOLVE entry "HOST:PORT:ADDR[,ADDR...]" pinning the connection
    to already-validated addresses. IPv6 addresses are bracketed; all addresses share one entry
    so libcurl keeps every fallback. Raises ValueError on any malformed input (fail closed).
    """
    if not host or not isinstance(host, str):
        raise ValueError(f"Invalid host for resolve entry: {host!r}")
    if not port or not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError(f"Invalid port for resolve entry: {port!r}")
    if not approved_ips:
        raise ValueError(f"No approved IP addresses provided for resolve entry: host={host}, port={port}")

    formatted = []
    for value in approved_ips:
        ip = ipaddress.ip_address(str(value).strip().strip("[]"))
        formatted.append(f"[{ip}]" if ip.version == 6 else str(ip))
    return f"{host.strip('[]').lower()}:{port}:{','.join(formatted)}"


def decode_ddg_url(raw_url: str) -> str:
    """Decode the destination URL from a DuckDuckGo redirect link."""
    if not raw_url:
        return ""
    match = re.search(r"uddg=([^&]+)", raw_url)
    if match:
        return unquote(match.group(1))
    if raw_url.startswith("//"):
        return f"https:{raw_url}"
    return raw_url


def _text(node: Any) -> str:
    """Stripped text of a Scrapling node (including descendants) or of a plain value."""
    if node is None:
        return ""
    if hasattr(node, "get_all_text"):
        return str(node.get_all_text()).strip()
    return str(getattr(node, "text", node)).strip()


class ScraplingScraper:
    """Fetches company pages directly (SSRF-checked, IP-pinned) and searches DuckDuckGo, optionally via Tor."""

    def __init__(
        self,
        timeout: int = 25,
        user_agent: str = DEFAULT_USER_AGENT,
        request_delay: float = 0.5,
        use_browser: bool = True,
        use_tor: bool = True,
        proxy: Optional[str] = None,
        headless: bool = True,
    ):
        self.timeout = timeout
        self.request_delay = request_delay
        self.use_browser = use_browser and HAS_STEALTHY_FETCHER
        self.use_tor = use_tor
        self.headless = headless
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self._last_request_time: Dict[str, float] = {}

        # The proxy (normally Tor) is only used for search; page fetches go direct and pinned.
        self.tor_manager = TorManager()
        self.proxy = proxy or (self.tor_manager.get_proxy_url() if use_tor else None)
        # An unconstrained egress proxy cannot honour IP pinning, so its presence blocks page fetches.
        self.target_proxy = os.getenv("TARGET_EGRESS_PROXY", "").strip() or None

        logger.info(f"ScraplingScraper initialized: browser={self.use_browser}, tor={self.use_tor}, "
                    f"proxy={TorManager.sanitize_proxy_url(self.proxy)}")

    def _respect_rate_limit(self, domain: str) -> None:
        """Wait so each domain gets at most one request per request_delay."""
        if not domain:
            return
        elapsed = time.time() - self._last_request_time.get(domain, 0.0)
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request_time[domain] = time.time()

    def clean_untrusted_text(self, text: str, max_chars: int = 4000) -> str:
        """Strip control characters and collapse whitespace in scraped text."""
        if not text:
            return ""
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n\s*\n+", "\n\n", cleaned)
        return cleaned.strip()[:max_chars]

    def _extract_page_metadata(self, response: Any, url: str) -> ScrapeResult:
        """Extract title, description, headings and text from a Scrapling response."""
        titles = response.css("title")
        metas = response.css("meta[name='description'], meta[property='og:description']")
        headings: List[str] = []
        for node in response.css("h1, h2, h3")[:15]:
            heading = _text(node)
            if heading and len(heading) < 150 and heading not in headings:
                headings.append(heading)

        return ScrapeResult(
            url=url,
            status_code=getattr(response, "status", 200),
            success=True,
            title=_text(titles[0]) if titles else "",
            meta_description=_text(metas[0].attrib.get("content", "")) if metas else "",
            headings=headings,
            extracted_text=self.clean_untrusted_text(_text(response)),
            engine="scrapling_pinned_fetcher",
        )

    def _execute_pinned_get(
        self,
        url: str,
        headers: Dict[str, str],
        timeout: int,
        resolve_entries: List[str],
    ) -> Any:
        """
        GET with the connection pinned to validated IPs via CURLOPT_RESOLVE, so DNS cannot be
        re-resolved to a different address (TLS SNI, Host header and certificate checks unchanged).
        Never follows redirects itself.
        """
        if not resolve_entries:
            raise ValueError(f"SSRF Transport Error: No connection resolve pin provided for {url}")
        with Session(curl_options={CurlOpt.RESOLVE: resolve_entries}, verify=True) as session:
            raw_resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=False)
            return ResponseFactory.from_http_request(raw_resp, {})

    def fetch_url(self, url: str) -> ScrapeResult:
        """
        Fetch a page and extract its content. Every hop, including each redirect target, is
        SSRF-checked and IP-pinned before it is requested. No browser fallback and no retries.
        """
        def fail(status: int, error: str) -> ScrapeResult:
            return ScrapeResult(url=url, status_code=status, success=False, error=error)

        domain = urlparse(url).netloc.lower()
        if "linkedin.com" in domain:
            return fail(403, "LinkedIn profile access is restricted by authentication wall. "
                             "Public domain sources prioritized.")
        if self.target_proxy:
            return fail(400, "Egress security policy: Arbitrary target fetching cannot be routed through "
                             "unconstrained proxy without verified destination IP enforcement.")

        self._respect_rate_limit(domain)
        current_url = url
        visited = {url}
        for hop in range(MAX_REDIRECTS + 1):
            safe, reason, host, port, approved_ips = resolve_and_validate_destination(current_url)
            if not safe:
                return fail(400, reason if hop == 0 else f"Redirect destination blocked by SSRF protection: {reason}")

            try:
                response = self._execute_pinned_get(
                    current_url,
                    headers=self.headers,
                    timeout=min(self.timeout, 10),
                    resolve_entries=[format_curl_resolve_entry(host, port, approved_ips)],
                )
            except Exception as exc:
                return fail(500, f"Request failed: {exc}")

            status = getattr(response, "status", 200)
            if status >= 400:
                return fail(status, f"HTTP {status}")
            if status < 300:
                return self._extract_page_metadata(response, current_url)

            headers = getattr(response, "headers", None) or {}
            location = headers.get("location") or headers.get("Location")
            if not location:
                return fail(502, f"HTTP {status} redirect without Location header")
            current_url = urljoin(current_url, location)
            if current_url in visited:
                return fail(400, f"Redirect loop detected: {current_url}")
            visited.add(current_url)

        return fail(400, f"Too many redirects (exceeded limit of {MAX_REDIRECTS})")

    def search_person(self, name: str, company: str, custom_query: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Search DuckDuckGo for a person. Uses the browser through the proxy (Tor) when available,
        otherwise, or if that finds nothing, DuckDuckGo Lite. Returns [] on failure.
        """
        query = custom_query or f"{name} {company}"
        if not query.strip():
            return []

        if self.use_browser:
            try:
                self._respect_rate_limit("duckduckgo.com")
                logger.info(f"Scrapling StealthyFetcher searching DuckDuckGo: '{query}'")
                fetch_kwargs: Dict[str, Any] = {
                    "headless": self.headless,
                    "timeout": 15000,
                    "disable_resources": True,
                    "block_ads": True,
                    "network_idle": False,
                    "retries": 1,
                }
                if self.proxy:
                    fetch_kwargs["proxy"] = self.proxy
                page = StealthyFetcher.fetch(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}", **fetch_kwargs)

                results = []
                for block in page.css(".result")[:6]:
                    title_elem = block.css(".result__title a")
                    url_elem = block.css(".result__url") or title_elem
                    snippet_elem = block.css(".result__snippet")
                    snippet = self.clean_untrusted_text(_text(snippet_elem[0]) if snippet_elem else "", max_chars=1000)
                    title = _text(title_elem[0]) if title_elem else ""
                    if title and len(snippet) > 20:
                        results.append({
                            "title": title,
                            "url": decode_ddg_url(url_elem[0].attrib.get("href", "") if url_elem else ""),
                            "snippet": snippet,
                            "engine": "scrapling_stealth_browser",
                        })
                if results:
                    return results
            except Exception as e:
                logger.warning(f"Browser DuckDuckGo search failed for '{query}': {e}")

        try:
            self._respect_rate_limit("lite.duckduckgo.com")
            response = Fetcher.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query},
                headers=self.headers,
                timeout=min(self.timeout, 12),
            )
            results = []
            for link, snip in list(zip(response.css(".result-link"), response.css(".result-snippet")))[:5]:
                snippet = self.clean_untrusted_text(_text(snip), max_chars=1000)
                if len(snippet) > 20:
                    results.append({
                        "title": _text(link),
                        "url": link.attrib.get("href", ""),
                        "snippet": snippet,
                        "engine": "scrapling_lite_fallback",
                    })
            return results
        except Exception as e:
            logger.warning(f"DuckDuckGo Lite search failed for '{query}': {e}")
            return []
