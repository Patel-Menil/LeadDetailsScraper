"""Tests for the Scrapling scraper with mocked DNS and transport (no external requests)."""

from unittest.mock import patch
from urllib.parse import urlparse

from scrapling import Selector
from src.lead_research import scraper as scraper_mod
from src.lead_research.scraper import ScraplingScraper, is_safe_url

real_resolve = scraper_mod.resolve_and_validate_destination


def fake_resolve(url, resolve_dns=True):
    """Treat hostnames as public (no DNS); IP literals and bad URLs still go through the real check."""
    host = urlparse(url).hostname or ""
    if not url.startswith(("http://", "https://")) or not host or host[0].isdigit() or ":" in host:
        return real_resolve(url, resolve_dns=resolve_dns)
    return True, "", host, 443, ["93.184.216.34"]


def fetch(url, get):
    """Run fetch_url with fake DNS and `get` standing in for the pinned transport."""
    scraper = ScraplingScraper(use_browser=False, use_tor=False)
    with patch.object(scraper_mod, "resolve_and_validate_destination", side_effect=fake_resolve):
        with patch.object(scraper, "_execute_pinned_get", side_effect=get) as pinned:
            return scraper.fetch_url(url), pinned


class Redirect:
    def __init__(self, location, status=302):
        self.status = status
        self.headers = {"Location": location}


def test_clean_untrusted_text():
    scraper = ScraplingScraper()
    dirty = "Hello\x00 World!\x1f\n\n\n\nTest   Spaces"
    cleaned = scraper.clean_untrusted_text(dirty)
    assert "\x00" not in cleaned
    assert "\x1f" not in cleaned
    assert cleaned == "Hello World!\n\nTest Spaces"


def test_linkedin_auth_wall_limitation():
    scraper = ScraplingScraper()
    res = scraper.fetch_url("https://www.linkedin.com/in/some-user")
    assert res.success is False
    assert res.status_code == 403
    assert "authentication wall" in res.error.lower()


def test_mocked_scrapling_fetch_success():
    sample_html = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>OmniAI — Secure Enterprise LLM Gateway</title>
        <meta name="description" content="Deploying zero-trust API security for production AI models." />
      </head>
      <body>
        <h1>Enterprise AI Platform</h1>
        <h2>API Protection & Audit Governance</h2>
        <p>We help Fortune 500 teams safeguard sensitive API tokens and guard against prompt injection.</p>
        <a href="/security">Security Center</a>
      </body>
    </html>
    """
    res, pinned = fetch("https://omniai.example.com", lambda url, **kw: Selector(sample_html))

    assert res.success is True
    assert res.title == "OmniAI — Secure Enterprise LLM Gateway"
    assert "zero-trust API security" in res.meta_description
    assert "Enterprise AI Platform" in res.headings
    assert "safeguard sensitive API tokens" in res.extracted_text
    # The connection is pinned to the validated address.
    assert pinned.call_args.kwargs["resolve_entries"] == ["omniai.example.com:443:93.184.216.34"]


def test_missing_page_returns_http_status():
    class NotFound:
        status = 404

    res, _ = fetch("https://example.com/missing", lambda url, **kw: NotFound())
    assert res.success is False
    assert res.status_code == 404
    assert res.error == "HTTP 404"


def test_malformed_or_empty_page_extracts_without_crashing():
    res, _ = fetch("https://example.com/broken", lambda url, **kw: Selector("<html><head><title>Half<body><h1>Open"))
    assert res.success is True
    assert res.meta_description == ""

    res, _ = fetch("https://example.com/empty", lambda url, **kw: Selector("<html></html>"))
    assert res.success is True
    assert (res.title, res.headings, res.extracted_text) == ("", [], "")


def test_network_failure_is_reported_once_without_retry():
    def boom(url, **kw):
        raise ConnectionError("DNS resolution failed")

    res, pinned = fetch("https://nonexistent-domain-404.example.com", boom)
    assert res.success is False
    assert res.status_code == 500
    assert "Request failed" in res.error and "DNS resolution failed" in res.error
    assert pinned.call_count == 1


def test_no_browser_fallback_for_page_fetches():
    scraper = ScraplingScraper(use_browser=True, use_tor=False, proxy=None)
    with patch.object(scraper_mod, "resolve_and_validate_destination", side_effect=fake_resolve):
        with patch.object(scraper, "_execute_pinned_get", side_effect=ConnectionError("down")):
            with patch.object(scraper_mod, "StealthyFetcher", create=True) as browser:
                res = scraper.fetch_url("https://example.com/test-path")
    assert res.success is False
    assert res.status_code == 500
    browser.fetch.assert_not_called()


def test_ssrf_blocks_multi_ip_when_any_ip_is_private():
    import socket

    mock_addrinfo = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80)),
    ]
    with patch("socket.getaddrinfo", return_value=mock_addrinfo):
        safe, reason = is_safe_url("http://dual-homed-target.com/api")
        assert not safe
        assert "private/reserved IP" in reason or "10.0.0.1" in reason


def test_ssrf_rejects_non_http_schemes():
    schemes = [
        "file:///etc/passwd",
        "file:///c:/boot.ini",
        "gopher://127.0.0.1:6379/_INFO",
        "ftp://ftp.example.com/file",
        "javascript:alert(1)",
        "data:text/html,<h1>test</h1>",
    ]
    for target in schemes:
        safe, reason = is_safe_url(target)
        assert not safe, f"Target {target} should be rejected"
        assert "scheme" in reason.lower() or "invalid" in reason.lower()


def test_ssrf_redirect_loop_detected():
    res, _ = fetch("https://example.com/page-a", lambda url, **kw: Redirect("https://example.com/page-a"))
    assert res.success is False
    assert res.status_code == 400
    assert "redirect loop detected" in res.error.lower()


def test_ssrf_excessive_redirects_rejected():
    hops = iter(range(1, 100))
    res, pinned = fetch("https://example.com/hop-0", lambda url, **kw: Redirect(f"https://example.com/hop-{next(hops)}"))
    assert res.success is False
    assert res.status_code == 400
    assert "too many redirects" in res.error.lower()
    assert pinned.call_count == scraper_mod.MAX_REDIRECTS + 1


def test_ssrf_unsafe_redirect_destination_blocked_before_fetch():
    res, pinned = fetch(
        "https://innocent-looking-site.com/redirect",
        lambda url, **kw: Redirect("http://169.254.169.254/latest/meta-data/", status=301),
    )
    assert res.success is False
    assert res.status_code == 400
    assert "redirect destination blocked" in res.error.lower()
    # The metadata address was never requested.
    assert [c.args[0] for c in pinned.call_args_list] == ["https://innocent-looking-site.com/redirect"]
