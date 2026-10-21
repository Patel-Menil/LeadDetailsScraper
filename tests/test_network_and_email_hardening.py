"""Comprehensive tests for:
1. SSRF & connection-level DNS pinning (CurlOpt.RESOLVE, mixed DNS rejection, redirects, proxy policies).
2. Tor deployment, health configuration, and credential sanitation.
3. Professional email verification audit (exact address evidence vs domain-only, malformed syntax, unprobed status).
"""

import http.server
import ipaddress
import os
import socket
import threading
from unittest.mock import MagicMock, patch
import pytest

from src.lead_research.research import LeadResearcher, validate_claims_provenance
from src.lead_research.schemas import (
    Icebreaker,
    LeadClaim,
    LeadInput,
    ProfessionalContext,
    SourceEvidence,
)
from src.lead_research.scoring import LeadScorer
from src.lead_research.scraper import (
    ScraplingScraper,
    ScrapeResult,
    format_curl_resolve_entry,
    is_safe_url,
    resolve_and_validate_destination,
)
from src.lead_research.tor_manager import TorManager


# ---------------------------------------------------------------------------
# 1. SSRF & Connection-Level DNS Pinning Tests
# ---------------------------------------------------------------------------

def test_connection_pinning_transport_enforces_approved_ip():
    """Verify libcurl CurlOpt.RESOLVE routes connection to pinned IP while preserving Host header."""
    received_headers = {}

    class PinnedHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            received_headers["Host"] = self.headers.get("Host")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><head><title>Pinned Test Success</title></head><body><h1>Pinned</h1></body></html>")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), PinnedHandler)
    port = server.server_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        scraper = ScraplingScraper(use_browser=False, use_tor=False)
        fake_host = "unresolvable-ssrf-pin-test.example"

        # Explicitly invoke _execute_pinned_get with the resolve entry
        resolve_entries = [f"{fake_host}:{port}:127.0.0.1"]
        resp = scraper._execute_pinned_get(
            f"http://{fake_host}:{port}/test-pin",
            headers={"User-Agent": "TestBot/1.0"},
            timeout=5,
            resolve_entries=resolve_entries,
        )

        assert getattr(resp, "status", getattr(resp, "status_code", 0)) == 200
        # Host header must preserve the original target hostname, not the IP
        assert fake_host in received_headers.get("Host", "")
        # Scrapling Selector parsing works on the converted response
        assert "Pinned Test Success" in resp.css("title::text").get()
    finally:
        server.shutdown()


def test_connection_pinning_transport_multiple_addresses_failover():
    """
    Verify libcurl CURLOPT_RESOLVE comma-separated entries preserve multiple IPs
    and fall back to reachable IP when the first address fails, whereas separate
    un-prefixed entries overwrite and discard the earlier IP.
    """
    received = []

    class MultiIpHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(True)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK-Multi-IP")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), MultiIpHandler)
    port = server.server_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        scraper = ScraplingScraper(use_browser=False, use_tor=False)
        fake_host = "dual-ip-fallback-test.example"

        # Format: 192.0.2.1 is TEST-NET-1 (unreachable), followed by 127.0.0.1 (server)
        entry = format_curl_resolve_entry(fake_host, port, ["192.0.2.1", "127.0.0.1"])
        assert entry == f"{fake_host}:{port}:192.0.2.1,127.0.0.1"

        resp = scraper._execute_pinned_get(
            f"http://{fake_host}:{port}/fallback",
            headers={"User-Agent": "TestBot/1.0"},
            timeout=3,
            resolve_entries=[entry],
        )

        assert getattr(resp, "status", getattr(resp, "status_code", 0)) == 200
        assert len(received) == 1
    finally:
        server.shutdown()


def test_format_curl_resolve_entry_semantics():
    """Verify libcurl CURLOPT_RESOLVE formatting: IPv6 brackets, multiple IPs, non-default ports."""
    # 1. Multiple approved IPv4 addresses
    e1 = format_curl_resolve_entry("api.example.com", 443, ["93.184.216.34", "93.184.216.35"])
    assert e1 == "api.example.com:443:93.184.216.34,93.184.216.35"

    # 2. IPv6 addresses require square brackets in libcurl CURLOPT_RESOLVE
    e2 = format_curl_resolve_entry("ipv6.example.com", 80, ["2606:4700:4700::1111"])
    assert e2 == "ipv6.example.com:80:[2606:4700:4700::1111]"

    # 3. Mixed address families (IPv4 + IPv6) with non-default port
    e3 = format_curl_resolve_entry("dual.example.com", 8443, ["93.184.216.34", "2606:4700:4700::1111"])
    assert e3 == "dual.example.com:8443:93.184.216.34,[2606:4700:4700::1111]"

    # 4. Fails closed on invalid host, port, or empty/malformed IPs
    with pytest.raises(ValueError, match="Invalid host"):
        format_curl_resolve_entry("", 80, ["93.184.216.34"])

    with pytest.raises(ValueError, match="Invalid port"):
        format_curl_resolve_entry("example.com", 0, ["93.184.216.34"])

    with pytest.raises(ValueError, match="Invalid port"):
        format_curl_resolve_entry("example.com", 70000, ["93.184.216.34"])

    with pytest.raises(ValueError, match="No approved IP addresses"):
        format_curl_resolve_entry("example.com", 80, [])

    with pytest.raises(Exception):
        format_curl_resolve_entry("example.com", 80, ["not-an-ip"])


def test_redirect_re_pinning_generates_distinct_pin_per_hop():
    """Verify that each redirect hop generates and applies an independent resolve pin for the target host."""
    scraper = ScraplingScraper(use_browser=False, use_tor=False)
    hop_pins = []

    def mock_resolve(url, resolve_dns=True):
        if "start.example" in url:
            return True, "", "start.example", 80, ["93.184.216.10"]
        elif "final.example" in url:
            return True, "", "final.example", 80, ["93.184.216.20"]
        return False, "Unknown host", "", 0, []

    class MockResponse:
        def __init__(self, status, headers):
            self.status = status
            self.status_code = status
            self.headers = headers
            self.text = "Redirected"
            self.attrib = {}
        def css(self, selector):
            return []
        def get_all_text(self):
            return "Final Content"

    def mock_pinned_get(url, headers, timeout, resolve_entries):
        hop_pins.append((url, list(resolve_entries)))
        if "start.example" in url:
            return MockResponse(302, {"Location": "http://final.example/landing"})
        return MockResponse(200, {})

    with patch("src.lead_research.scraper.resolve_and_validate_destination", side_effect=mock_resolve):
        with patch.object(scraper, "_execute_pinned_get", side_effect=mock_pinned_get):
            res = scraper.fetch_url("http://start.example/entry")

    assert res.success is True
    assert len(hop_pins) == 2
    # First hop pinned to start.example's approved IP
    assert hop_pins[0][0] == "http://start.example/entry"
    assert hop_pins[0][1] == ["start.example:80:93.184.216.10"]
    # Second hop pinned to final.example's approved IP
    assert hop_pins[1][0] == "http://final.example/landing"
    assert hop_pins[1][1] == ["final.example:80:93.184.216.20"]


def test_ssrf_rejects_loopback_and_prohibited_destinations_end_to_end():
    """Verify fetch_url immediately rejects loopback, link-local, and cloud metadata without network requests."""
    scraper = ScraplingScraper(use_browser=False, use_tor=False)

    prohibited_urls = [
        "http://127.0.0.1:8080/admin",
        "http://localhost:3000/api",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/secret",
        "http://metadata.google.internal/computeMetadata/v1",
        "http://10.0.0.1/internal",
        "http://192.168.1.1/router",
    ]

    for p_url in prohibited_urls:
        res = scraper.fetch_url(p_url)
        assert res.success is False
        assert res.status_code == 400
        assert "SSRF Protection" in res.error


def test_transport_fails_without_connection_pinning():
    """Verify that requesting an unresolvable hostname without CurlOpt.RESOLVE fails with DNS error."""
    scraper = ScraplingScraper(use_browser=False, use_tor=False)
    fake_host = "completely-nonexistent-domain-xyz987654.example"

    with pytest.raises(Exception):
        scraper._execute_pinned_get(
            f"http://{fake_host}:8080/path",
            headers={"User-Agent": "TestBot/1.0"},
            timeout=2,
            resolve_entries=[],
        )


def test_resolve_and_validate_destination_public_hostname():
    """Verify safe public hostname returns approved IP addresses and valid port."""
    mock_addr = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
    ]
    with patch("socket.getaddrinfo", return_value=mock_addr):
        safe, reason, host, port, approved_ips = resolve_and_validate_destination(
            "https://public-site.example.com/about", resolve_dns=True
        )
        assert safe is True
        assert reason == ""
        assert host == "public-site.example.com"
        assert port == 443
        assert approved_ips == ["93.184.216.34"]


def test_resolve_and_validate_destination_mixed_dns_fails_closed():
    """Verify that if a DNS response contains any private or reserved IP, the destination is rejected."""
    mock_addr = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.50", 80)),
    ]
    with patch("socket.getaddrinfo", return_value=mock_addr):
        safe, reason, host, port, approved_ips = resolve_and_validate_destination(
            "http://mixed-records.example.com", resolve_dns=True
        )
        assert safe is False
        assert "private/reserved IP" in reason
        assert approved_ips == []


def test_resolve_and_validate_destination_blocks_prohibited_ipv6_and_mapped():
    """Verify that loopback, link-local, unspecified, and IPv4-mapped IPv6 are rejected."""
    prohibited_urls = [
        "http://[::1]:8080/secret",
        "http://[fc00::1]/admin",
        "http://[fe80::1]/metadata",
        "http://[::ffff:127.0.0.1]/status",
        "http://[::ffff:169.254.169.254]/latest/meta-data/",
    ]
    for target in prohibited_urls:
        safe, reason, _, _, _ = resolve_and_validate_destination(target, resolve_dns=True)
        assert safe is False, f"URL {target} should be blocked"
        assert "blocked" in reason.lower() or "private/reserved" in reason.lower()


def test_fetch_url_redirect_applies_fresh_independent_connection_pinning():
    """Verify that when a 3xx redirect occurs, each hop gets an independent connection pin."""
    scraper = ScraplingScraper(use_browser=False, use_tor=False)

    class Mock302Response:
        status = 302
        status_code = 302
        headers = {"Location": "https://secondary-partner.example.com/welcome"}

    class Mock200Response:
        status = 200
        status_code = 200
        headers = {}

        def css(self, selector):
            m = MagicMock()
            m.get_all_text.return_value = "Secondary Partner Page"
            m.attrib = {}
            return [m]

        def get_all_text(self):
            return "Welcome to Secondary Partner"

    pinned_resolves = []

    def mock_pinned_get(url, headers, timeout, resolve_entries):
        pinned_resolves.append((url, resolve_entries))
        if "first" in url:
            return Mock302Response()
        return Mock200Response()

    with patch.object(scraper, "_execute_pinned_get", side_effect=mock_pinned_get):
        with patch("src.lead_research.scraper.resolve_and_validate_destination") as mock_resolve:
            def mock_resolve_fn(u, resolve_dns=True):
                if "first" in u:
                    return (True, "", "first-site.example.com", 443, ["93.184.216.34"])
                return (True, "", "secondary-partner.example.com", 443, ["104.20.23.154"])

            mock_resolve.side_effect = mock_resolve_fn
            res = scraper.fetch_url("https://first-site.example.com/start")

            assert res.success is True
            assert len(pinned_resolves) == 2
            # Hop 1 was pinned to first host
            assert "first-site.example.com:443:93.184.216.34" in pinned_resolves[0][1]
            # Hop 2 was pinned to second host
            assert "secondary-partner.example.com:443:104.20.23.154" in pinned_resolves[1][1]


def test_unconstrained_target_proxy_rejected_by_egress_policy():
    """Verify that routing arbitrary target fetches through an unconstrained proxy is rejected."""
    scraper = ScraplingScraper(use_browser=False, use_tor=False)
    scraper.target_proxy = "socks5://unconstrained-proxy:1080"

    with patch("src.lead_research.scraper.resolve_and_validate_destination", return_value=(True, "", "example.com", 443, ["93.184.216.34"])):
        res = scraper.fetch_url("https://example.com/some-page")
        assert res.success is False
        assert res.status_code == 400
        assert "egress security policy" in res.error.lower()


# ---------------------------------------------------------------------------
# 2. Tor Deployment and Health Configuration Tests
# ---------------------------------------------------------------------------

def test_tor_manager_respects_tor_enabled_flag(monkeypatch):
    """Verify TorManager returns None and reports disabled when TOR_ENABLED=false."""
    monkeypatch.setenv("TOR_ENABLED", "false")
    manager = TorManager()
    assert manager.is_enabled() is False
    assert manager.get_proxy_url() is None

    status = manager.get_status()
    assert status["enabled"] is False
    assert status["state"] == "disabled"
    assert status["is_running"] is False
    assert status["socks_reachable"] is False
    assert status["proxy_url"] is None
    assert status["compose_service"] == "tor"


def test_tor_manager_sanitizes_credentials():
    """Verify TorManager.sanitize_proxy_url masks credentials."""
    raw = "socks5://sec_user:p@ssw0rd!@127.0.0.1:9050"
    cleaned = TorManager.sanitize_proxy_url(raw)
    assert cleaned == "socks5://***:***@127.0.0.1:9050"
    assert "p@ssw0rd!" not in cleaned


def test_tor_manager_reports_unreachable_endpoint_safely(monkeypatch):
    """Verify TorManager does not equate configured proxy with running when endpoint is offline."""
    monkeypatch.setenv("TOR_ENABLED", "true")
    monkeypatch.setenv("TOR_PROXY", "socks5://offline-tor-node.internal:9050")
    with patch.object(TorManager, "is_port_open", return_value=False):
        manager = TorManager()
        proxy = manager.get_proxy_url()
        # Must NOT return unreachable proxy as active
        assert proxy is None
        status = manager.get_status()
        assert status["enabled"] is True
        assert status["is_running"] is False
        assert status["socks_reachable"] is False
        assert status["state"] == "proxy_configured_unreachable"
        assert "unreachable" in status["details"].lower()


def test_tor_manager_rejects_open_tcp_port_if_not_socks_proxy(monkeypatch):
    """Verify open TCP port that fails SOCKS5 handshake is identified as check_failed_or_inconclusive."""
    # Ephemeral server listening on TCP but sending non-SOCKS HTTP response
    class NonSocksHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"NOT A SOCKS PROXY")
        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), NonSocksHandler)
    port = server.server_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        monkeypatch.setenv("TOR_ENABLED", "true")
        monkeypatch.setenv("TOR_PROXY", f"socks5://127.0.0.1:{port}")
        manager = TorManager()

        # Port is open, but it's not a SOCKS5 proxy
        assert manager.is_port_open("127.0.0.1", port) is True
        assert manager.is_socks5_functional("127.0.0.1", port) is False

        # get_proxy_url must reject it
        assert manager.get_proxy_url() is None

        status = manager.get_status()
        assert status["enabled"] is True
        assert status["is_running"] is False
        assert status["socks_reachable"] is False
        assert status["state"] == "check_failed_or_inconclusive"
        assert "handshake failed" in status["details"].lower()
    finally:
        server.shutdown()


def test_tor_manager_functioning_mock_socks5_endpoint(monkeypatch):
    """Verify functioning SOCKS5 responder is recognized as socks_endpoint_reachable."""
    running = True

    def mock_socks5_server(server_sock):
        server_sock.settimeout(2.0)
        while running:
            try:
                conn, _ = server_sock.accept()
                with conn:
                    conn.settimeout(2.0)
                    greeting = conn.recv(10)
                    if greeting.startswith(b"\x05"):
                        # Respond with SOCKS5, No Authentication Required
                        conn.sendall(b"\x05\x00")
            except (socket.timeout, OSError):
                continue

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(5)
    port = server_sock.getsockname()[1]

    t = threading.Thread(target=mock_socks5_server, args=(server_sock,), daemon=True)
    t.start()

    try:
        monkeypatch.setenv("TOR_ENABLED", "true")
        monkeypatch.setenv("TOR_PROXY", f"socks5://127.0.0.1:{port}")
        manager = TorManager()

        assert manager.is_port_open("127.0.0.1", port) is True
        assert manager.is_socks5_functional("127.0.0.1", port) is True

        proxy = manager.get_proxy_url()
        assert proxy == f"socks5://127.0.0.1:{port}"

        status = manager.get_status()
        assert status["enabled"] is True
        assert status["is_running"] is True
        assert status["socks_reachable"] is True
        assert status["state"] == "socks_endpoint_reachable"
        assert status["routing_verified"] is False
    finally:
        running = False
        server_sock.close()


def test_tor_manager_verified_routing_and_secret_redaction(monkeypatch):
    """Verify routing_verified state and credential masking in details and proxy_url."""
    monkeypatch.setenv("TOR_ENABLED", "true")
    monkeypatch.setenv("TOR_PROXY", "socks5://user:TopSecretPass999@tor:9050")

    with patch.object(TorManager, "is_port_open", return_value=True):
        with patch.object(TorManager, "is_socks5_functional", return_value=True):
            with patch.object(TorManager, "verify_tor_routing", return_value=True):
                manager = TorManager()
                status = manager.get_status(verify_routing=True)

                assert status["enabled"] is True
                assert status["is_running"] is True
                assert status["socks_reachable"] is True
                assert status["routing_verified"] is True
                assert status["state"] == "routing_verified"
                assert "TopSecretPass999" not in status["proxy_url"]
                assert "TopSecretPass999" not in status["details"]
                assert status["proxy_url"] == "socks5://***:***@tor:9050"


# ---------------------------------------------------------------------------
# 3. Professional Email Verification Audit Tests
# ---------------------------------------------------------------------------

def test_exact_email_on_verified_source_corroborates_email():
    """Verify exact email on verified company source elevates claim to verified."""
    scraper = ScraplingScraper(use_browser=False, use_tor=False)
    researcher = LeadResearcher(scraper=scraper)
    lead = LeadInput(
        lead_id="lead_exact_email_01",
        name="Marcus Vance",
        job_title="Chief Information Security Officer",
        company="SecureSphere Corp",
        company_website="https://securesphere.com",
        professional_email="marcus.vance@securesphere.com",
    )
    # Page contains exact email and corroborates company & leadership
    mock_res = ScrapeResult(
        url="https://securesphere.com/about/leadership",
        status_code=200,
        success=True,
        title="Leadership Team | SecureSphere Corp",
        extracted_text="SecureSphere Corp leadership: Marcus Vance serves as Chief Information Security Officer. Contact: marcus.vance@securesphere.com for security inquiries.",
    )

    with patch.object(researcher.scraper, "fetch_url", return_value=mock_res):
        with patch.object(researcher.scraper, "search_person", return_value=[]):
            profile = researcher.research_lead(lead, skip_web_scrape=False)

    email_claim = next(c for c in profile.claims if c.field == "professional_email")
    assert email_claim.status == "verified"
    assert email_claim.confidence >= 0.85
    assert "corroborated on official company domain" in email_claim.review_reason
    assert profile.contact.get("email_verification_status") == "corroborated_on_verified_source"
    assert "email_syntax_valid_unprobed" not in profile.contact_readiness.blockers


def test_matching_domain_without_exact_email_remains_unprobed():
    """Verify that matching company domain without exact email evidence remains input_provided/unprobed."""
    scraper = ScraplingScraper(use_browser=False, use_tor=False)
    researcher = LeadResearcher(scraper=scraper)
    lead = LeadInput(
        lead_id="lead_domain_only_02",
        name="Marcus Vance",
        job_title="Chief Information Security Officer",
        company="SecureSphere Corp",
        company_website="https://securesphere.com",
        professional_email="marcus.vance@securesphere.com",
    )
    # Page corroborates company and person, but does NOT contain the email address anywhere
    mock_res = ScrapeResult(
        url="https://securesphere.com/about/leadership",
        status_code=200,
        success=True,
        title="Leadership Team | SecureSphere Corp",
        extracted_text="SecureSphere Corp leadership: Marcus Vance serves as Chief Information Security Officer leading zero-trust enterprise initiatives.",
    )

    mock_candidates = [{
        "title": "Marcus Vance - Chief Information Security Officer - SecureSphere Corp",
        "url": "https://securesphere.com/about/leadership",
        "snippet": "Marcus Vance serves as Chief Information Security Officer at SecureSphere Corp.",
    }]

    with patch.object(researcher.scraper, "fetch_url", return_value=mock_res):
        with patch.object(researcher.scraper, "search_person", return_value=mock_candidates):
            profile = researcher.research_lead(lead, skip_web_scrape=False)

    email_claim = next(c for c in profile.claims if c.field == "professional_email")
    # Must NOT be elevated to verified
    assert email_claim.status != "verified"
    assert email_claim.status == "input_provided"
    assert profile.contact.get("email_verification_status") == "syntax_valid_unprobed"
    assert "email_syntax_valid_unprobed" in profile.contact_readiness.blockers
    assert profile.contact_readiness.status == "ready_with_caveat"


def test_malformed_email_syntax_rejected():
    """Verify malformed email is marked unverified and blocks usable contact channel."""
    scraper = ScraplingScraper(use_browser=False, use_tor=False)
    researcher = LeadResearcher(scraper=scraper)
    lead = LeadInput(
        lead_id="lead_bad_email_03",
        name="Alex Mercer",
        job_title="VP of Engineering",
        company="TechCore",
        professional_email="invalid_email_no_domain",
    )
    profile = researcher.research_lead(lead, skip_web_scrape=True)

    email_claim = next(c for c in profile.claims if c.field == "professional_email")
    assert email_claim.status == "unverified"
    assert "malformed" in email_claim.review_reason.lower()
    assert profile.contact.get("email_verification_status") == "syntax_invalid"
    assert "no_usable_contact_channel" in profile.contact_readiness.blockers
    assert profile.contact_readiness.status in ("not_ready", "needs_research")


def test_validate_claims_provenance_downgrades_unsupported_email_claims():
    """Verify validate_claims_provenance downgrades verified email lacking genuine evidence."""
    claims = [
        LeadClaim(
            claim_id="clm_email",
            field="professional_email",
            value="fake@example.com",
            status="verified",
            confidence=0.90,
            source_ids=["src_no_email"],
        )
    ]
    sources = [
        SourceEvidence(
            source_id="src_no_email",
            source_url="https://example.com",
            source_type="official_company",
            evidence_quality=0.85,
            relevant_excerpt="General company about page with no contact emails.",
            facts_supported=["Company Identity: example.com"],
        )
    ]

    validated = validate_claims_provenance(claims, sources)
    email_clm = validated[0]
    assert email_clm.status != "verified"
    assert email_clm.status == "input_provided"
    assert "lacks eligible inspected source evidence" in email_clm.review_reason
