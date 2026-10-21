"""Tests for Scrapling scraper using mocked HTML fixtures (no external requests)."""

from unittest.mock import MagicMock, patch
import pytest
from scrapling import Selector
from src.lead_research.scraper import ScraplingScraper, ScrapeResult


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


@patch("src.lead_research.scraper.Fetcher.get")
def test_mocked_scrapling_fetch_success(mock_get):
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
        <a href="/about-us">About Us</a>
        <a href="/security">Security Center</a>
      </body>
    </html>
    """
    mock_response = Selector(sample_html)
    mock_get.return_value = mock_response

    scraper = ScraplingScraper()
    res = scraper.fetch_url("https://omniai.example.com")

    assert res.success is True
    assert res.title == "OmniAI — Secure Enterprise LLM Gateway"
    assert "zero-trust API security" in res.meta_description
    assert "Enterprise AI Platform" in res.headings
    assert any("/security" in sub for sub in res.sublinks)


@patch("src.lead_research.scraper.Fetcher.get")
def test_mocked_scrapling_fetch_retry_and_failure(mock_get):
    mock_get.side_effect = ConnectionError("DNS resolution failed")

    scraper = ScraplingScraper(max_retries=1)
    res = scraper.fetch_url("https://nonexistent-domain-404.example.com")

    assert res.success is False
    assert res.status_code == 500
    assert "Request failed after 2 attempts" in res.error


def test_ssrf_blocks_multi_ip_when_any_ip_is_private():
    import socket
    from src.lead_research.scraper import is_safe_url

    mock_addrinfo = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80)),
    ]
    with patch("socket.getaddrinfo", return_value=mock_addrinfo):
        safe, reason = is_safe_url("http://dual-homed-target.com/api")
        assert not safe
        assert "private/reserved IP" in reason or "10.0.0.1" in reason


def test_browser_fallback_disabled_without_proxy_for_arbitrary_urls():
    scraper = ScraplingScraper(use_browser=True, use_tor=False, proxy=None)
    with patch("src.lead_research.scraper.Fetcher.get", return_value=None):
        res = scraper.fetch_url("https://example.com/test-path")
        assert res.success is False
        assert res.status_code in (500, 504)

