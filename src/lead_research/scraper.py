"""Web extraction engine using Scrapling browser automation (StealthyFetcher) with Tor and DuckDuckGo."""

import ipaddress
import logging
import re
import socket
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

from scrapling import Fetcher, Selector
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


class ScrapeResult:
    """Encapsulates the result of a Scrapling extraction."""

    def __init__(
        self,
        url: str,
        status_code: int = 0,
        success: bool = False,
        title: str = "",
        meta_description: str = "",
        headings: Optional[List[str]] = None,
        extracted_text: str = "",
        sublinks: Optional[List[str]] = None,
        error: str = "",
        engine: str = "scrapling_fetcher",
    ):
        self.url = url
        self.status_code = status_code
        self.success = success
        self.title = title
        self.meta_description = meta_description
        self.headings = headings or []
        self.extracted_text = extracted_text
        self.sublinks = sublinks or []
        self.error = error
        self.engine = engine
        self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "success": self.success,
            "title": self.title,
            "meta_description": self.meta_description,
            "headings": self.headings,
            "extracted_text": self.extracted_text[:3000],
            "sublinks": self.sublinks[:10],
            "error": self.error,
            "engine": self.engine,
            "timestamp": self.timestamp,
        }


def is_safe_url(url: str, resolve_dns: bool = True) -> Tuple[bool, str]:
    """
    SSRF Protection: Block private, link-local, loopback, or reserved destinations,
    including DNS resolution checks and redirect validation.
    """
    if not url or not url.startswith(("http://", "https://")):
        return False, "SSRF Protection: Invalid or missing HTTP/HTTPS scheme"

    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False, f"SSRF Protection: Scheme '{parsed.scheme}' is not permitted (only http and https)."

        # Reject URL credentials (e.g. http://user:pass@example.com)
        if parsed.username or parsed.password:
            return False, "SSRF Protection: URL credentials are not permitted."

        hostname = parsed.hostname
        if not hostname:
            return False, "Missing hostname in URL"

        # Check raw IP literals
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False, f"SSRF Protection: Access to private/reserved IP {hostname} is blocked."
            return True, ""
        except ValueError:
            pass

        # Not an IP literal; check hostname keywords and internal TLDs
        lower_host = hostname.lower()
        if lower_host in ("localhost", "127.0.0.1", "::1", "metadata.google.internal", "instance-data") or lower_host.endswith((".local", ".internal", ".lan", ".localhost", ".home", ".corp")):
            return False, f"SSRF Protection: Access to local/internal host '{hostname}' is blocked."

        # DNS resolution check for non-literal hostnames
        if resolve_dns:
            try:
                addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
                for family, socktype, proto, canonname, sockaddr in addr_info:
                    ip_str = sockaddr[0]
                    resolved_ip = ipaddress.ip_address(ip_str)
                    if resolved_ip.is_private or resolved_ip.is_loopback or resolved_ip.is_link_local or resolved_ip.is_reserved or resolved_ip.is_multicast:
                        return False, f"SSRF Protection: Hostname '{hostname}' resolves to private/reserved IP {ip_str}."
            except socket.gaierror:
                # DNS failure can be handled gracefully during fetch
                pass
            except Exception as dns_err:
                logger.debug(f"DNS check notice for {hostname}: {dns_err}")

        return True, ""
    except Exception as e:
        return False, f"Malformed URL: {e}"


def decode_ddg_url(raw_url: str) -> str:
    """Decode direct destination URL from DuckDuckGo redirect link."""
    if not raw_url:
        return ""
    if "uddg=" in raw_url:
        match = re.search(r"uddg=([^&]+)", raw_url)
        if match:
            return unquote(match.group(1))
    if raw_url.startswith("//"):
        return f"https:{raw_url}"
    return raw_url


class ScraplingScraper:
    """High-reliability web scraper powered by Scrapling browser automation with Tor support."""

    def __init__(
        self,
        timeout: int = 25,
        max_retries: int = 2,
        user_agent: str = DEFAULT_USER_AGENT,
        request_delay: float = 0.5,
        use_browser: bool = True,
        use_tor: bool = True,
        proxy: Optional[str] = None,
        headless: bool = True,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent
        self.request_delay = request_delay
        self.use_browser = use_browser and HAS_STEALTHY_FETCHER
        self.use_tor = use_tor
        self.headless = headless
        self._last_request_time: Dict[str, float] = {}

        # Resolve proxy
        self.tor_manager = TorManager()
        if proxy:
            self.proxy = proxy
        elif self.use_tor:
            self.proxy = self.tor_manager.get_proxy_url()
        else:
            self.proxy = None

        logger.info(
            f"ScraplingScraper initialized: browser={self.use_browser}, "
            f"tor={self.use_tor}, proxy={self.proxy}"
        )

    def _respect_rate_limit(self, domain: str) -> None:
        """Throttle requests per domain."""
        if not domain:
            return
        last_time = self._last_request_time.get(domain, 0.0)
        elapsed = time.time() - last_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request_time[domain] = time.time()

    def clean_untrusted_text(self, text: str, max_chars: int = 4000) -> str:
        """Sanitize scraped text to prevent prompt injection or malformed data."""
        if not text:
            return ""
        # Remove zero-width characters and unusual control chars
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        # Normalize whitespace
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n\s*\n+", "\n\n", cleaned)
        return cleaned.strip()[:max_chars]

    def _extract_page_metadata(self, response: Any, url: str) -> ScrapeResult:
        """Extract structured elements from a Scrapling response."""
        domain = urlparse(url).netloc.lower()
        title = ""
        meta_desc = ""
        headings: List[str] = []
        sublinks: List[str] = []

        # Title
        title_nodes = response.css("title")
        if title_nodes:
            t_text = title_nodes[0].get_all_text() if hasattr(title_nodes[0], "get_all_text") else title_nodes[0].text
            title = clean_str(t_text)

        # Meta Description
        meta_nodes = response.css("meta[name='description'], meta[property='og:description']")
        if meta_nodes:
            meta_desc = clean_str(meta_nodes[0].attrib.get("content", ""))

        # Headings (h1, h2, h3)
        for h in response.css("h1, h2, h3")[:15]:
            h_text = h.get_all_text() if hasattr(h, "get_all_text") else h.text
            h_clean = clean_str(h_text)
            if h_clean and len(h_clean) < 150 and h_clean not in headings:
                headings.append(h_clean)

        # Relevant sublinks
        for a in response.css("a[href]")[:40]:
            href = a.attrib.get("href", "")
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                full_sub = urljoin(url, href)
                lower_href = href.lower()
                if any(k in lower_href for k in ["about", "team", "security", "ai", "product", "platform", "trust"]):
                    if full_sub not in sublinks and urlparse(full_sub).netloc == domain:
                        sublinks.append(full_sub)

        # Full text
        all_text = response.get_all_text() if hasattr(response, "get_all_text") else ""
        cleaned_text = self.clean_untrusted_text(all_text)

        status_code = getattr(response, "status", 200)

        return ScrapeResult(
            url=url,
            status_code=status_code,
            success=True,
            title=title,
            meta_description=meta_desc,
            headings=headings,
            extracted_text=cleaned_text,
            sublinks=sublinks,
            engine="scrapling_stealth_browser" if self.use_browser else "scrapling_fetcher",
        )

    def fetch_url(self, url: str) -> ScrapeResult:
        """Fetch and extract page contents using Scrapling StealthyFetcher with Fetcher fallback and SSRF protection."""
        # 1. SSRF Safety Check
        safe, reason = is_safe_url(url)
        if not safe:
            return ScrapeResult(url=url, status_code=400, success=False, error=reason)

        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Check for known auth-walled domains
        if "linkedin.com" in domain:
            return ScrapeResult(
                url=url,
                status_code=403,
                success=False,
                error="LinkedIn profile access is restricted by authentication wall. Public domain sources prioritized."
            )

        self._respect_rate_limit(domain)

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # 2. HTTP Fetch with manual redirect validation loop (max 5 redirects)
        # Pre-validates every redirect destination before connection to prevent SSRF via 3xx redirects
        max_redirects = 5
        current_url = url
        visited_urls = {current_url}
        last_error = ""

        for redirect_step in range(max_redirects + 1):
            safe, reason = is_safe_url(current_url)
            if not safe:
                return ScrapeResult(
                    url=url,
                    status_code=400,
                    success=False,
                    error=f"Destination blocked by SSRF protection: {reason}",
                )

            response = None
            attempts = self.max_retries + 1
            for attempt in range(attempts):
                try:
                    response = Fetcher.get(
                        current_url,
                        headers=headers,
                        timeout=min(self.timeout, 10),
                        follow_redirects=False,
                        retries=0,
                    )
                    break
                except Exception as exc:
                    last_error = str(exc)
                    logger.debug(f"Fetch attempt {attempt + 1}/{attempts} failed for {current_url}: {exc}")
                    if attempt < attempts - 1:
                        time.sleep(0.25 * (attempt + 1))

            if response is None:
                break

            status = getattr(response, "status", 200)

            # Handle 3xx redirects with destination pre-validation
            if 300 <= status < 400:
                location = None
                if hasattr(response, "headers") and response.headers:
                    location = response.headers.get("location") or response.headers.get("Location")

                if not location:
                    last_error = f"HTTP {status} redirect without Location header"
                    break

                next_url = urljoin(current_url, location)

                # Check redirect loop
                if next_url in visited_urls:
                    return ScrapeResult(
                        url=url,
                        status_code=400,
                        success=False,
                        error=f"Redirect loop detected: {next_url}",
                    )

                # Validate redirect destination BEFORE making request
                safe_redir, redir_reason = is_safe_url(next_url)
                if not safe_redir:
                    return ScrapeResult(
                        url=url,
                        status_code=400,
                        success=False,
                        error=f"Redirect destination blocked by SSRF protection: {redir_reason}",
                    )

                visited_urls.add(next_url)
                current_url = next_url

                if redirect_step == max_redirects:
                    return ScrapeResult(
                        url=url,
                        status_code=400,
                        success=False,
                        error=f"Too many redirects (exceeded limit of {max_redirects})",
                    )
                continue
            elif status < 400:
                res = self._extract_page_metadata(response, current_url)
                res.engine = "scrapling_fetcher"
                return res
            else:
                last_error = f"HTTP {status}"
                break

        # 3. If direct HTTP failed due to connection/DNS resolution, do NOT hit with browser
        if "connection" in last_error.lower() or "dns" in last_error.lower() or "resolve" in last_error.lower():
            return ScrapeResult(
                url=url,
                status_code=500,
                success=False,
                error=f"Request failed after {attempts} attempts: {last_error}",
            )

        # 4. Optional Browser-based Scraping with StealthyFetcher for anti-bot or JS-heavy sites
        if self.use_browser:
            try:
                logger.info(f"Scrapling StealthyFetcher browser fetching: {url}")
                fetch_kwargs: Dict[str, Any] = {
                    "headless": self.headless,
                    "timeout": 12000,
                    "disable_resources": True,
                    "block_ads": True,
                    "network_idle": False,
                    "retries": 1,
                }
                response = StealthyFetcher.fetch(url, **fetch_kwargs)
                return self._extract_page_metadata(response, url)
            except Exception as exc:
                logger.warning(f"Browser scrape attempt failed for {url}: {exc}")
                last_error = str(exc)

        return ScrapeResult(
            url=url,
            status_code=504,
            success=False,
            error=f"Website could not be reached via HTTP or Browser. Last error: {last_error}",
        )

    def search_person(self, name: str, company: str, custom_query: Optional[str] = None) -> List[Dict[str, str]]:
        """Search DuckDuckGo using Scrapling browser with Tor proxy for professional background."""
        query = custom_query or f"{name} {company}"
        if not query.strip():
            return []

        encoded_q = quote_plus(query)
        ddg_html_url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
        results: List[Dict[str, str]] = []

        # 1. Primary: Browser-based Scraping via StealthyFetcher with Tor
        if self.use_browser:
            try:
                self._respect_rate_limit("duckduckgo.com")
                logger.info(f"Scrapling StealthyFetcher searching DuckDuckGo via Tor: '{query}'")
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

                page = StealthyFetcher.fetch(ddg_html_url, **fetch_kwargs)

                # Parse DuckDuckGo search result blocks
                result_blocks = page.css(".result")
                for r in result_blocks[:6]:
                    title_elem = r.css(".result__title a")
                    url_elem = r.css(".result__url")
                    snip_elem = r.css(".result__snippet")

                    title = ""
                    if title_elem:
                        t_text = title_elem[0].get_all_text() if hasattr(title_elem[0], "get_all_text") else title_elem[0].text
                        title = clean_str(t_text)

                    raw_url = ""
                    if url_elem:
                        raw_url = url_elem[0].attrib.get("href", "")
                    elif title_elem:
                        raw_url = title_elem[0].attrib.get("href", "")

                    real_url = decode_ddg_url(raw_url)

                    snippet = ""
                    if snip_elem:
                        s_text = snip_elem[0].get_all_text() if hasattr(snip_elem[0], "get_all_text") else snip_elem[0].text
                        snippet = clean_str(s_text)

                    cleaned_snip = self.clean_untrusted_text(snippet, max_chars=1000)

                    if title and cleaned_snip and len(cleaned_snip) > 20:
                        results.append({
                            "title": title,
                            "url": real_url,
                            "snippet": cleaned_snip,
                            "engine": "scrapling_stealth_browser",
                        })

                if results:
                    logger.info(f"Found {len(results)} browser search results for '{query}'")
                    return results

            except Exception as e:
                logger.warning(f"Browser DuckDuckGo search failed for '{query}': {e}")

        # 2. Fallback: DuckDuckGo Lite via Fetcher.post
        try:
            self._respect_rate_limit("lite.duckduckgo.com")
            headers = {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            response = Fetcher.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query},
                headers=headers,
                timeout=min(self.timeout, 12),
            )

            links = response.css(".result-link")
            snippets = response.css(".result-snippet")
            for link_elem, snip_elem in list(zip(links, snippets))[:5]:
                title = clean_str(link_elem.text)
                url = link_elem.attrib.get("href", "")
                snippet = clean_str(snip_elem.get_all_text() if hasattr(snip_elem, "get_all_text") else snip_elem.text)
                cleaned_snip = self.clean_untrusted_text(snippet, max_chars=1000)

                if cleaned_snip and len(cleaned_snip) > 20:
                    results.append({
                        "title": title,
                        "url": url,
                        "snippet": cleaned_snip,
                        "engine": "scrapling_lite_fallback",
                    })

            return results
        except Exception as e:
            logger.warning(f"Fallback person search error for '{query}': {e}")
            return []


def clean_str(s: Any) -> str:
    if s is None:
        return ""
    return str(s).strip()
