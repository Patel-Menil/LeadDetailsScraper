import pytest

from src.lead_research.individual_discovery import Candidate, IndividualInput, Observation
from src.lead_research.individual_research import (
    ai_repo_signals, assign_priority, build_professional_profile, classify_role, discover_company, sealapi_verdict,
)
from src.lead_research.scraper import ScrapeResult


class FakeSearch:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return self.results.get(query, [])


def fetch_ok(url, text):
    def _f(u):
        return ScrapeResult(url=u, success=True, title=text, meta_description=text, extracted_text=text)
    return _f


def fail_if_called(u):
    raise AssertionError("fetch must not be called")


def cand(company="", github_site="", title="", obs_extra=None):
    obs = []
    if github_site:
        obs.append(Observation(source_id="github:jane", source_type="github", url="https://github.com/jane", name="Jane Doe",
                               github_login="jane", website=github_site))
    obs += obs_extra or []
    return Candidate(candidate_id="c1", name="Jane Doe", title=title, company=company, location="", avatar_url="",
                     profile_url="", description="", linkedin_slug="", github_login="jane" if github_site else "",
                     website=github_site, observations=obs)


def test_company_domain_from_github_blog_corroborated():
    c = cand(company="Acme AI", github_site="https://acme.ai")
    out = discover_company(c, IndividualInput(name="Jane Doe"), FakeSearch({}), fetch_ok("https://acme.ai", "Acme AI - secure agents"))
    assert out == {**out, "domain": "acme.ai", "status": "verified", "corroborated": True, "domain_source": "github_blog"}


def test_company_uncorroborated_is_unknown():
    c = cand(company="Acme AI", github_site="https://randomblog.io")
    out = discover_company(c, IndividualInput(name="Jane Doe"), FakeSearch({}), fetch_ok("https://randomblog.io", "My cooking blog"))
    assert out["status"] == "unknown" and out["domain"] == "" and out["corroborated"] is False and out["note"]


def test_company_domain_from_official_site_search_skips_social():
    search = FakeSearch({'"Acme AI" official site': [{"url": "https://www.linkedin.com/company/acme"}, {"url": "https://acme.ai/"}]})
    out = discover_company(cand(company="Acme AI"), IndividualInput(name="Jane Doe"), search, fetch_ok("https://acme.ai/", "Acme AI"))
    assert out["domain"] == "acme.ai" and out["domain_source"] == "search"


def test_no_company_is_unknown_without_fetching():
    out = discover_company(cand(company=""), IndividualInput(name="Jane Doe"), FakeSearch({}), fail_if_called)
    assert out["status"] == "unknown" and out["domain"] == ""


def test_inp_company_used_and_website_source():
    out = discover_company(cand(company=""), IndividualInput(name="Jane Doe", company="Acme AI", website="https://acme.ai"),
                           FakeSearch({}), fetch_ok("https://acme.ai", "Acme AI"))
    assert out["name"] == "Acme AI" and out["domain_source"] == "website" and out["status"] == "verified"


def test_never_fetches_social_or_free_mail_and_fetch_errors_are_survived():
    seen = []

    def fetch(u):
        seen.append(u)
        raise RuntimeError("boom")

    search = FakeSearch({'"Acme AI" official site': [{"url": "https://x.com/acme"}, {"url": "https://gmail.com/"},
                                                      {"url": "https://twitter.com/a"}, {"url": "https://acme.ai"}]})
    out = discover_company(cand(company="Acme AI", github_site="https://github.com/acme"), IndividualInput(name="Jane Doe"), search, fetch)
    assert out["status"] == "unknown"
    assert seen == ["https://acme.ai/"]


def test_search_result_observation_url():
    o = Observation(source_id="search:1", source_type="search", url="https://www.acme.ai/about", name="Jane Doe")
    out = discover_company(cand(company="Acme AI", obs_extra=[o]), IndividualInput(name="Jane Doe"), FakeSearch({}),
                           fetch_ok("x", "Acme AI"))
    assert out["domain"] == "acme.ai" and out["domain_source"] == "search_result"


@pytest.mark.parametrize("title,cat,auth", [
    ("Co-Founder & CEO", "Founder / Co-founder", "executive"), ("Chief Technology Officer", "CTO", "executive"),
    ("CISO", "CISO", "executive"), ("VP of Engineering", "VP Engineering", "senior_leader"),
    ("Head of Machine Learning", "AI/ML Leader", "senior_leader"), ("Senior AI Engineer", "AI Engineer", "practitioner"),
    ("Engineering Manager", "Engineering Manager", "senior_leader"), ("", "Other", "unknown"),
    ("CEO", "CEO", "executive"), ("Security Architect", "Security Architect", "practitioner"),
    ("Barista", "Other", "unknown")])
def test_classify_role(title, cat, auth):
    r = classify_role(title)
    assert (r["category"], r["authority"]) == (cat, auth) and r["basis"] == "inferred"


@pytest.mark.parametrize("fit,rel", [("strong", "relevant"), ("validation_required", "needs_validation"),
    ("weak", "not_relevant"), ("not_suitable", "not_relevant"), ("insufficient_evidence", "insufficient_evidence")])
def test_verdict_mapping(fit, rel):
    assert sealapi_verdict({"company_fit": {"classification": fit, "label": "x", "reasoning": "r"}})["relevance"] == rel


def test_verdict_unknown_company_and_caps():
    v = sealapi_verdict(None)
    assert v["relevance"] == "insufficient_evidence" and v["opportunities"] == [] and v["scope_note"]
    rec = {"company_fit": {"classification": "strong", "label": "L", "reasoning": "R"},
           "opportunities": [{"n": i} for i in range(9)], "discovery_questions": [str(i) for i in range(9)]}
    v = sealapi_verdict(rec)
    assert len(v["opportunities"]) == 5 and len(v["discovery_questions"]) == 5 and v["fit_label"] == "L"


def test_priority_rules():
    assert assign_priority("relevant", {"category": "CTO", "authority": "executive"})["level"] == 0
    assert assign_priority("needs_validation", {"category": "AI Engineer", "authority": "practitioner"})["level"] == 1
    assert assign_priority("not_relevant", {"category": "CEO", "authority": "executive"})["level"] == 1
    assert assign_priority("insufficient_evidence", {"category": "CTO", "authority": "executive"})["level"] == 2
    p = assign_priority("relevant", {"category": "Security Architect", "authority": "practitioner"})
    assert p["level"] == 0 and p["label"] == "P0" and p["reasons"]
    assert assign_priority("relevant", {"category": "AI Engineer", "authority": "practitioner"})["level"] == 1


def test_ai_repo_signals():
    repos = [{"name": "my-llm-app", "html_url": "https://github.com/j/my-llm-app", "description": "x", "topics": [], "language": "Python"},
             {"name": "dotfiles", "description": "mail setup", "topics": ["vim"], "language": "Shell"},
             {"name": "x", "description": "Vector search", "topics": ["rag"], "language": None}]
    out = ai_repo_signals(repos)
    assert [r["repo"] for r in out] == ["my-llm-app", "x"]
    assert "llm" in out[0]["matched"] and {"vector", "rag"} <= set(out[1]["matched"])


def test_profile():
    c = cand(company="Acme", github_site="https://acme.ai", title="CTO")
    c.location = "Berlin"
    p = build_professional_profile(c, [{"name": "llm-x", "description": "", "topics": [], "language": "Python"},
                                       {"name": "b", "language": "Go"}])
    assert p["current_title"] == "CTO" and p["role"]["category"] == "CTO" and p["current_company"] == "Acme"
    assert p["github"]["login"] == "jane" and p["github"]["public_repos"] == 2
    assert set(p["github"]["languages"]) == {"Python", "Go"} and len(p["github"]["ai_repos"]) == 1
    assert all(f["basis"] in ("verified", "inferred") for f in p["facts"]) and p["facts"]


def test_priority_needs_validation_p0():
    assert assign_priority("needs_validation", {"category": "CTO", "authority": "executive"})["level"] == 0
    assert assign_priority("needs_validation", {"category": "CISO", "authority": "executive"})["level"] == 0
    assert assign_priority("needs_validation", {"category": "Security Architect", "authority": "practitioner"})["level"] == 0


def test_founding_engineer_not_founder():
    assert classify_role("Founding Engineer")["category"] != "Founder / Co-founder"
    assert classify_role("Founding AI Engineer")["category"] != "Founder / Co-founder"
    assert classify_role("Cofounder")["category"] == "Founder / Co-founder"


def test_corroboration_exception_does_not_raise(monkeypatch):
    import src.lead_research.individual_research as ir

    def boom(*a, **k):
        raise ValueError("bad")

    monkeypatch.setattr(ir, "is_company_corroborated", boom)
    c = cand(company="Acme AI", github_site="https://acme.ai")
    out = discover_company(c, IndividualInput(name="Jane Doe"), FakeSearch({}), fetch_ok("x", "Acme AI"))
    assert out["status"] == "unknown" and "ValueError" in out["note"]


def test_website_links_used_when_homepage_not_company():
    def fetch(u):
        if "janedoe.dev" in u:
            return ScrapeResult(url=u, success=True, title="Jane's page", meta_description="", extracted_text="portfolio",
                                links=[("https://github.com/jane", "gh"), ("https://www.acme.ai/", "Acme")])
        return ScrapeResult(url=u, success=True, title="Acme AI", meta_description="Acme AI", extracted_text="Acme AI")

    out = discover_company(cand(company="Acme AI"), IndividualInput(name="Jane Doe", website="https://janedoe.dev"),
                           FakeSearch({}), fetch)
    assert out["domain"] == "acme.ai" and out["domain_source"] == "website_link" and out["status"] == "verified"
