"""Company intelligence: normalization, research workflow, analysis, SealAPI mapping, outreach, exports, API."""

import csv
import io
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from src.lead_research import company_intel as ci
from src.lead_research import server
from src.lead_research.scraper import ScrapeResult
from src.lead_research.sealapi_capabilities import CAPABILITIES

DOMAIN = "acmehealth.com"

HOME_TEXT = (
    "Acme Health builds AI-powered care software for hospitals and clinics. "
    "Our platform helps care teams spend less time on documentation.\n"
    "Acme Health integrates with Epic and Cerner so patient records stay in sync."
)
PRODUCT_TEXT = (
    "Care Copilot is an AI assistant that drafts clinical notes from patient records. "
    "Care Copilot uses OpenAI models to summarise encounters for clinicians. "
    "Clinicians review every AI-generated note in the dashboard before it is saved."
)
DEV_TEXT = (
    "The Acme Health REST API lets partners read and write scheduling data. "
    "Authenticate every request with an API key issued in the developer dashboard. "
    "Subscribe to webhooks to receive appointment events."
)
SECURITY_TEXT = (
    "Acme Health is SOC 2 Type II audited and supports HIPAA requirements for protected health information. "
    "All data is encrypted at rest and in transit, and customers can enforce SSO for every user."
)


def page(url, title, text, links=(), meta=""):
    return ScrapeResult(url=url, status_code=200, success=True, title=title, meta_description=meta,
                        headings=[title, "Clinical notes", "Integrations"], extracted_text=text, links=list(links))


def acme_site():
    base = f"https://{DOMAIN}"
    return {
        f"{base}/robots.txt": ScrapeResult(url=f"{base}/robots.txt", status_code=200, success=True,
                                           extracted_text="User-agent: *\nDisallow: /private"),
        f"{base}/": page(f"{base}/", "Acme Health | AI care software", HOME_TEXT, links=[
            (f"{base}/products/care-copilot", "Care Copilot"),
            (f"{base}/developers", "Developers"),
            (f"{base}/security", "Security"),
            (f"{base}/integrations", "Integrations"),
            (f"{base}/private/admin", "Admin"),
            ("https://othersite.com/products/x", "Off-domain"),
        ], meta="Acme Health builds AI-powered care software for hospitals."),
        f"{base}/products/care-copilot": page(f"{base}/products/care-copilot", "Care Copilot", PRODUCT_TEXT,
                                              meta="Care Copilot is an AI assistant for clinical documentation."),
        f"{base}/developers": page(f"{base}/developers", "Acme Health Developers", DEV_TEXT),
        f"{base}/security": page(f"{base}/security", "Security at Acme Health", SECURITY_TEXT),
        f"{base}/integrations": page(f"{base}/integrations", "Integrations", "Acme Health integrates with Epic, Cerner and Salesforce."),
    }


class FakeProvider:
    name = "fake"

    def __init__(self, pages, failures=None, gate=None):
        self.pages = pages
        self.failures = dict(failures or {})  # url -> list of status codes to return first
        self.calls = []
        self.gate = gate

    def fetch(self, url):
        if self.gate is not None:
            self.gate.wait(5)
        self.calls.append(url)
        queued = self.failures.get(url)
        if queued:
            return ScrapeResult(url=url, status_code=queued.pop(0), success=False, error="transient")
        return self.pages.get(url) or ScrapeResult(url=url, status_code=404, success=False, error="HTTP 404")


def profile(lead_id="lead_a1", email="dana@acmehealth.com", website="https://www.acmehealth.com/about", title="CTO"):
    return {
        "lead_id": lead_id,
        "identity": {"name": "Dana Reyes", "first_name": "Dana", "job_title": title, "company": "Acme Health",
                     "industry": "hospital & health care", "company_website": website, "professional_email": email},
        "company": {},
        "contact": {"email": email},
        "input_snapshot": {"Employees": "45", "Company City": "Austin", "Company State": "Texas"},
    }


@pytest.fixture
def store(tmp_path):
    return ci.CompanyStore(tmp_path / "companies")


def researched(store, pages=None, **kw):
    ident = ci.company_identity_from_profile(profile())
    record = ci.new_company_record(ident, profile())
    provider = FakeProvider(pages or acme_site(), **kw)
    sleeps = []
    out = ci.CompanyResearcher(store, provider=provider, sleep=sleeps.append).research(record)
    return out, provider, sleeps


# --- normalization & dedupe --------------------------------------------------------------

def test_domain_normalization_and_validation():
    assert ci.normalize_domain("https://WWW.AcmeHealth.com/about?x=1") == DOMAIN
    assert ci.normalize_domain("acmehealth.com:8443") == DOMAIN
    assert ci.normalize_domain("localhost") == ""
    assert ci.normalize_domain("not a domain") == ""
    assert ci.normalize_domain("") == ""


def test_company_identity_dedupes_by_domain_and_ignores_free_mail():
    a = ci.company_identity_from_profile(profile("lead_1"))
    b = ci.company_identity_from_profile(profile("lead_2", website="acmehealth.com", email="x@acmehealth.com"))
    assert a["company_id"] == b["company_id"] and a["domain"] == DOMAIN

    via_email = ci.company_identity_from_profile(profile(website="", email="dana@acmehealth.com"))
    assert via_email["domain"] == DOMAIN and via_email["domain_source"] == "work_email"

    free = ci.company_identity_from_profile(profile(website="", email="dana@gmail.com"))
    assert free["domain"] == "" and free["company_id"].startswith("co_name_")
    record = ci.new_company_record(free, profile(website="", email="dana@gmail.com"))
    assert record["research_status"] == "needs_review"


# --- research workflow --------------------------------------------------------------------

def test_research_collects_attributed_findings_and_products(store):
    record, provider, _ = researched(store)
    assert record["research_status"] == "completed"
    assert record["identity_corroborated"] is True
    assert all(ci._on_company_domain(f["source_url"], DOMAIN) for f in record["findings"])
    assert all(f["verification_status"] == "unreviewed" and 0 < f["confidence"] <= 1 for f in record["findings"])
    assert all(f["evidence"] and f["accessed_at"] for f in record["findings"])
    assert "https://othersite.com/products/x" not in provider.calls

    names = [p["name"] for p in record["products"]]
    assert "Care Copilot" in names
    copilot = next(p for p in record["products"] if p["name"] == "Care Copilot")
    assert copilot["inferred"] is False and copilot["url"].endswith("/products/care-copilot")
    labels = {(f["category"], f["label"]) for f in record["findings"]}
    assert ("ai_provider", "OpenAI") in labels and ("security_controls", "SOC 2") in labels
    assert store.load(record["company_id"])["research_status"] == "completed"


def test_robots_txt_is_respected(store):
    record, provider, _ = researched(store)
    assert not any("/private" in url for url in provider.calls)


def test_homepage_failure_reports_failed_not_completed(store):
    pages = acme_site()
    del pages[f"https://{DOMAIN}/"]
    record, _, _ = researched(store, pages=pages)
    assert record["research_status"] == "failed"
    assert record["errors"]
    assert record["company_fit"]["classification"] == "insufficient_evidence"


def test_bounded_retries_with_backoff(store):
    url = f"https://{DOMAIN}/developers"
    record, provider, sleeps = researched(store, failures={url: [503, 502]})
    assert provider.calls.count(url) == 3
    assert sleeps[:2] == [1.0, 2.0]
    assert any(p["url"] == url and p["success"] for p in record["pages"])

    res, attempts = ci.fetch_with_retry(FakeProvider({}), "https://acmehealth.com/missing", sleep=lambda s: None)
    assert attempts == 1 and res.status_code == 404  # 4xx is not retried


def test_resume_uses_page_cache_and_refresh_refetches(store):
    record, _, _ = researched(store)
    provider = FakeProvider(acme_site())
    ci.CompanyResearcher(store, provider=provider, sleep=lambda s: None).research(record)
    assert f"https://{DOMAIN}/" not in provider.calls  # cached, resumed
    provider2 = FakeProvider(acme_site())
    ci.CompanyResearcher(store, provider=provider2, sleep=lambda s: None).research(record, refresh=True)
    assert f"https://{DOMAIN}/" in provider2.calls


def test_refresh_keeps_manual_reviews_and_rejected_findings_are_excluded(store):
    record, _, _ = researched(store)
    for f in record["findings"]:
        if f["category"] in ("ai", "ai_provider"):
            f["verification_status"] = "rejected"
    soc2 = next(f for f in record["findings"] if f["label"] == "SOC 2")
    soc2["verification_status"] = "verified"
    record = ci.CompanyResearcher(store, provider=FakeProvider(acme_site()), sleep=lambda s: None).research(record, refresh=True)

    by_id = {f["finding_id"]: f for f in record["findings"]}
    assert by_id[soc2["finding_id"]]["verification_status"] == "verified"
    assert not any(g["kind"].startswith("ai_") for g in record["gaps"])
    assert record["company_fit"]["classification"] != "strong"


# --- analysis ------------------------------------------------------------------------------

def test_gaps_are_potential_risks_never_verified_vulnerabilities(store):
    record, _, _ = researched(store)
    assert record["gaps"]
    for gap in record["gaps"]:
        assert gap["classification"] == "potential_risk"
        assert gap["verified_vulnerability"] is False
        assert gap["evidence_ids"] and gap["discovery_question"]
        assert gap["unverified_controls"]
    kinds = {g["kind"] for g in record["gaps"]}
    assert {"ai_provider_credentials", "ai_sensitive_data_flow", "integration_credentials", "public_api_access"} <= kinds


def test_sealapi_mapping_uses_only_implemented_capabilities(store):
    record, _, _ = researched(store)
    by_kind = {g["gap_id"]: g["kind"] for g in record["gaps"]}
    for opp in record["opportunities"]:
        assert all(CAPABILITIES[c]["status"] == "implemented" for c in opp["capability_ids"])
        if by_kind[opp["gap_id"]] in ("integration_credentials", "public_api_access"):
            assert opp["compatibility"]["status"] == "not_supported"
            assert opp["capability_ids"] == []
    cred = next(o for o in record["opportunities"] if by_kind[o["gap_id"]] == "ai_provider_credentials")
    assert cred["compatibility"]["status"] == "compatible_pending_validation"
    assert "live" in cred["compatibility"]["detail"]
    assert "SealAPI gateway" in cred["integration_point"]


def test_fit_classification_and_transparent_scoring(store):
    record, _, _ = researched(store)
    copilot = next(p for p in record["products"] if p["name"] == "Care Copilot")
    assert copilot["fit"]["classification"] == "strong"
    assert copilot["rank"] == 1
    factors = {f["factor"] for f in copilot["score"]["factors"]}
    assert factors == set(ci.DEFAULT_WEIGHTS)
    assert "Industry" in copilot["score"]["note"]
    assert copilot["architecture"]["status"] == "documented"
    backend = next(c for c in copilot["architecture"]["components"] if c["id"] == "backend")
    assert backend["documented"] is False  # inferred components are labelled


def test_no_ai_evidence_gives_weak_fit_and_conservative_outreach(store):
    pages = acme_site()
    pages[f"https://{DOMAIN}/"] = page(f"https://{DOMAIN}/", "Acme Health scheduling", "Acme Health is scheduling software for clinics. "
                                       "Acme Health integrates with Epic for scheduling.", links=[(f"https://{DOMAIN}/developers", "Developers")])
    record, _, _ = researched(store, pages=pages)
    assert record["company_fit"]["classification"] == "weak"
    outreach = ci.generate_outreach(record, profile()["identity"])
    assert [v["variant_id"] for v in outreach["variants"]] == ["conservative"]
    assert outreach["variants"][0]["guardrail_violations"] == []


def test_mentions_without_usage_context_are_not_findings(store):
    base = f"https://{DOMAIN}"
    pages = {
        f"{base}/robots.txt": ScrapeResult(url=f"{base}/robots.txt", status_code=404, success=False),
        f"{base}/": page(f"{base}/", "Acme Health", "When ChatGPT landed it was clearly not just another tool. "
                         "Turn the knowledge in your Slack threads into answers for your team.", links=[(f"{base}/about", "About")]),
        f"{base}/about": page(f"{base}/about", "About Acme Health", "Acme Health is a small team based in Austin, Texas."),
    }
    record, _, _ = researched(store, pages=pages)
    labels = {(f["category"], f["label"]) for f in record["findings"]}
    assert ("ai_provider", "OpenAI") not in labels
    assert ("integrations", "Named integrations") not in labels
    # a negated statement is not a documented control
    pages[f"{base}/about"] = page(f"{base}/about", "About", "Acme Health is not a covered entity under HIPAA.")
    record, _, _ = researched(store, pages=pages)
    assert not any(f["category"] == "security_controls" for f in record["findings"])
    # missing well-known probe paths (/security, /docs, ...) are absences, not fetch failures
    assert not any("could not be fetched" in w for w in record["research_warnings"])
    assert any(p.get("probe_absent") for p in record["pages"])


def test_top_level_platform_page_becomes_the_product(store):
    pages = acme_site()
    base = f"https://{DOMAIN}"
    pages[f"{base}/"] = page(f"{base}/", "Acme Health", HOME_TEXT, links=[(f"{base}/platform", "Platform")])
    pages[f"{base}/platform"] = page(f"{base}/platform", "The Acme platform", PRODUCT_TEXT)
    record, _, _ = researched(store, pages=pages)
    assert [(p["name"], p["inferred"]) for p in record["products"]] == [("Acme Health Platform", False)]


def test_missing_domain_blocks_research_without_fetching(store):
    ident = ci.company_identity_from_profile(profile(website="", email="dana@gmail.com"))
    provider = FakeProvider({})
    record = ci.CompanyResearcher(store, provider=provider).research(ci.new_company_record(ident))
    assert record["research_status"] == "needs_review" and provider.calls == []


# --- outreach --------------------------------------------------------------------------------

def test_outreach_variants_are_grounded_and_within_length(store):
    record, _, _ = researched(store)
    out = ci.generate_outreach(record, profile()["identity"])
    variants = {v["variant_id"]: v for v in out["variants"]}
    assert set(variants) == {"A", "B"}
    assert out["auto_send"] is False
    for v in variants.values():
        assert 100 <= v["word_count"] <= 160, (v["variant_id"], v["word_count"], v["body"])
        assert v["guardrail_violations"] == []
        assert "SealAPI, developed by BAVRIX" in v["body"]
        assert v["body"].rstrip().endswith("BAVRIX — SealAPI")
        assert v["body"].count("?") == 1
    assert variants["A"]["requires_review"] is True  # observation not yet manually verified
    assert variants["A"]["observation_source_url"].startswith(f"https://{DOMAIN}")


def test_outreach_problem_and_question_follow_the_role(store):
    pages = acme_site()
    url = f"https://{DOMAIN}/products/care-copilot"
    pages[url] = page(url, "Care Copilot", PRODUCT_TEXT.replace("Care Copilot uses OpenAI models to summarise encounters for clinicians. ", ""))
    record, _, _ = researched(store, pages=pages)
    questions = {g["kind"]: g["discovery_question"] for g in record["gaps"]}
    cto = ci.generate_outreach(record, {**profile()["identity"], "job_title": "CTO"})["variants"]
    ciso = ci.generate_outreach(record, {**profile()["identity"], "job_title": "CISO"})["variants"]
    assert all(questions["ai_provider_credentials"] in v["body"] for v in cto)
    assert all(questions["ai_sensitive_data_flow"] in v["body"] and "health records" in v["body"] for v in ciso)
    for v in cto + ciso:
        assert "company-level offering" not in v["body"] + v["subject"] and "(phi)" not in v["body"].lower()
        assert 100 <= v["word_count"] <= 160 and v["guardrail_violations"] == []


def test_outreach_guardrail_flags_unsupported_claims():
    text = "We found a vulnerability and guarantee our hardware TEE stops it, trusted by banks."
    reasons = ci.check_outreach_claims(text)
    assert {"claims a vulnerability", "guarantees an outcome", "unverified customer claim"} <= set(reasons)
    assert any("TEE" in r for r in reasons)


def test_role_questions_follow_research_and_role(store):
    record, _, _ = researched(store)
    cto = ci.role_questions(record, "CTO")
    ciso = ci.role_questions(record, "CISO")
    assert cto and ciso and cto[0] != ciso[0]
    assert all(q in record["discovery_questions"] for q in cto + ciso)
    assert ci.role_questions({"gaps": []}, "CTO") == []


# --- exports & secrets -----------------------------------------------------------------------

def test_exports_include_products_and_no_contact_details(store):
    record, _, _ = researched(store)
    ci.add_lead_ref(record, "batch_x", profile())
    text = ci.export_csv([record])
    rows = list(csv.DictReader(io.StringIO(text)))
    assert list(rows[0].keys()) == ci.EXPORT_COLUMNS
    assert any(r["product_name"] == "Care Copilot" for r in rows)
    payload = json.dumps(ci.export_json([record], "batch_x"))
    assert "dana@acmehealth.com" not in text and "dana@acmehealth.com" not in payload
    assert json.loads(payload)["lead_company_associations"][0]["lead_id"] == "lead_a1"


def test_store_rejects_path_traversal_ids(store):
    with pytest.raises(ValueError):
        store.load("../../etc/passwd")


# --- API ---------------------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    batch_dir = tmp_path / "batch_t1"
    (batch_dir / "profiles").mkdir(parents=True)
    (batch_dir / "profiles" / "person_001_lead_a1_dana.json").write_text(json.dumps(profile()), encoding="utf-8")
    test_store = ci.CompanyStore(tmp_path / "companies")
    gate = threading.Event()
    provider = FakeProvider(acme_site(), gate=gate)
    monkeypatch.setattr(server, "resolve_batch_dir", lambda batch_id: batch_dir)
    monkeypatch.setattr(server, "company_store", test_store)
    monkeypatch.setattr(server, "company_jobs", ci.ResearchJobs())
    monkeypatch.setattr(server, "CompanyResearcher",
                        lambda store: ci.CompanyResearcher(store, provider=provider, sleep=lambda s: None))
    return TestClient(server.app), gate


def wait_done(cid, timeout=10):
    end = time.time() + timeout
    while server.company_jobs.is_running(cid) and time.time() < end:
        time.sleep(0.05)


def test_company_api_lifecycle(api):
    client, gate = api
    q = "?batch_id=batch_t1"
    first = client.get(f"/api/leads/lead_a1/company{q}").json()
    assert first["research_status"] == "not_researched"

    started = client.post(f"/api/leads/lead_a1/company/research{q}", json={})
    assert started.status_code == 200 and started.json()["started"] is True
    duplicate = client.post(f"/api/leads/lead_a1/company/research{q}", json={})
    assert duplicate.status_code == 409
    gate.set()
    cid = started.json()["company_id"]
    wait_done(cid)

    view = client.get(f"/api/leads/lead_a1/company{q}").json()
    assert view["research_status"] == "completed" and view["role_questions"]
    cached = client.post(f"/api/companies/{cid}/research", json={}).json()
    assert cached["started"] is False and cached["cached"] is True

    finding = view["company"]["findings"][0]["finding_id"]
    assert client.post(f"/api/companies/{cid}/findings/{finding}", json={"status": "bogus"}).status_code == 422
    reviewed = client.post(f"/api/companies/{cid}/findings/{finding}", json={"status": "verified"}).json()
    assert next(f for f in reviewed["company"]["findings"] if f["finding_id"] == finding)["verification_status"] == "verified"
    assert client.post(f"/api/companies/{cid}/analyze").status_code == 200

    outreach = client.get(f"/api/leads/lead_a1/company/outreach{q}").json()
    assert outreach["variants"] and outreach["auto_send"] is False

    csv_resp = client.get("/api/batches/batch_t1/exports/company_intelligence.csv")
    assert csv_resp.status_code == 200 and "Care Copilot" in csv_resp.text
    js = client.get("/api/batches/batch_t1/exports/company_intelligence.json").json()
    assert js["companies"][0]["company_id"] == cid

    assert client.put(f"/api/companies/{cid}/domain", json={"domain": "not a domain"}).status_code == 422
    assert client.get("/api/companies/..%2F..%2Fsecrets").status_code in (400, 404)


def test_domain_correction_and_batch_research(api):
    client, gate = api
    gate.set()
    no_domain = ci.new_company_record(ci.company_identity_from_profile(profile(website="", email="d@gmail.com")))
    server.company_store.save(no_domain)
    view = client.put(f"/api/companies/{no_domain['company_id']}/domain", json={"domain": "https://www.AcmeHealth.com/x"}).json()
    assert view["company"]["normalized_domain"] == DOMAIN and view["company"]["domain_source"] == "manual"
    # a corrected record waits for research; it must not be reported as an interrupted job
    assert client.get(f"/api/companies/{no_domain['company_id']}").json()["research_status"] == "not_researched"

    job = client.post("/api/batches/batch_t1/companies/research", json={}).json()
    assert job["total_companies"] == 1 and job["queued"] == 1
    cid = ci.company_identity_from_profile(profile())["company_id"]
    wait_done(cid)
    end = time.time() + 10
    while server.batch_company_jobs["batch_t1"]["status"] != "completed" and time.time() < end:
        time.sleep(0.05)
    listing = client.get("/api/batches/batch_t1/companies").json()
    assert listing["job"]["done"] == 1
    assert listing["companies"][0]["research_status"] == "completed"


def test_interrupted_job_is_reported_as_failed(api):
    client, _ = api
    record = ci.new_company_record(ci.company_identity_from_profile(profile()), profile())
    record["research_status"] = "researching"
    server.company_store.save(record)
    view = client.get(f"/api/companies/{record['company_id']}").json()
    assert view["research_status"] == "failed"


def test_company_endpoints_require_auth_in_production(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(server, "APP_ENV", "production")
    monkeypatch.setattr(server, "API_SECRET_KEY", "test-key-123")
    assert client.get("/api/leads/lead_a1/company?batch_id=batch_t1").status_code == 401
    assert client.post("/api/batches/batch_t1/companies/research", json={}).status_code == 401
    ok = client.get("/api/leads/lead_a1/company?batch_id=batch_t1", headers={"X-API-Key": "test-key-123"})
    assert ok.status_code == 200
