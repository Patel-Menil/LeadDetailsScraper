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


# ------------------------------------------------------------------ pipeline / stores
import json
from datetime import datetime, timedelta, timezone

from src.lead_research.individual_research import (
    STAGES, IndividualJobStore, IndividualPipeline, MemoryCompanyStore,
)

LI_A = {"title": "Jane Doe - CTO - Acme AI | LinkedIn", "url": "https://www.linkedin.com/in/jane-a", "snippet": ""}
LI_B = {"title": "Jane Doe - Engineer - Beta Corp | LinkedIn", "url": "https://www.linkedin.com/in/jane-b", "snippet": ""}


class AnySearch:
    def __init__(self, hits=None, boom=False):
        self.hits, self.boom = hits or [], boom

    def search(self, query):
        if self.boom:
            raise RuntimeError("down")
        return list(self.hits)


class FakeGitHub:
    def __init__(self, errors=None, user=True):
        self.errors = errors or []
        self.user = user

    def search_users(self, name, limit=5):
        return []

    def get_user(self, login):
        if not self.user:
            return None
        return {"login": login, "name": "Jane Doe", "company": "Acme AI", "blog": "https://acme.ai",
                "html_url": f"https://github.com/{login}"}

    def get_repos(self, login, limit=10):
        return [{"name": "llm-agent", "language": "Python", "description": "LLM agent"}]


class FakeResearcher:
    def __init__(self, store):
        self.store = store

    def research(self, record):
        self.store.save(record)
        record.update(research_status="complete", pages=[
            {"url": "https://acme.ai/", "title": "Acme", "accessed_at": "t", "success": True, "text": "SECRET", "links": [["x", "y"]]}],
            products=[{"product_id": "p1", "name": "Agent Cloud"}],
            findings=[{"category": "ai_provider", "label": "OpenAI", "evidence": "uses OpenAI", "source_url": "https://acme.ai/", "product_id": "p1"},
                      {"category": "ai", "label": "AI features", "evidence": "LLM agents", "source_url": "https://acme.ai/ai"}],
            company_fit={"classification": "strong", "label": "Strong fit", "reasoning": "AI via OpenAI"})
        return record


class CrashResearcher:
    def __init__(self, store):
        pass

    def research(self, record):
        raise RuntimeError("engine blew up")


def make_pipe(search=None, github=None, fetch=None, researcher=FakeResearcher):
    return IndividualPipeline(search or AnySearch([LI_A]), github or FakeGitHub(),
                              fetch or fetch_ok("https://acme.ai", "Acme AI - secure agents"), company_researcher=researcher)


def start(pipe, inp):
    job = IndividualJobStore().create(inp)
    pipe.run(job)
    return job


AUTO_INP = IndividualInput(name="Jane Doe", github_url="https://github.com/jane", company="Acme AI")


def test_job_store_eviction_and_id_validation():
    t = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    store = IndividualJobStore(max_jobs=2, ttl=timedelta(hours=1), now=lambda: t[0])
    a = store.create(IndividualInput(name="A B"))
    store.create(IndividualInput(name="C D"))
    store.create(IndividualInput(name="E F"))
    assert store.get(a["job_id"]) is None
    t[0] += timedelta(hours=2)
    assert all(store.get(j) is None for j in list(store._jobs))
    with pytest.raises(ValueError):
        store.get("../etc")
    with pytest.raises(ValueError):
        store.lock("bad")


def test_pipeline_auto_path_completes_with_verdict():
    job = start(make_pipe(), AUTO_INP)
    assert job["status"] == "completed" and job["running"] is False
    assert [s["name"] for s in job["stages"]] == STAGES
    assert [s["status"] for s in job["stages"]] == ["done"] * 6
    assert job["company"]["domain"] == "acme.ai" and job["sealapi"]["relevance"] in ("relevant", "needs_validation")
    assert job["ai_usage"]["providers"] == ["OpenAI"] and job["ai_usage"]["ai_products"] == ["Agent Cloud"]
    assert job["priority"]["label"] == "P0"
    assert job["identity"]["mode"] == "auto" and job["person"]["candidate"]["candidate_id"] == job["selected_candidate_id"]
    assert job["person"]["github"]["public_repos"] == 1
    assert any(s.get("source_type") == "company_site" for s in job["sources"])
    assert "SECRET" not in json.dumps(job) and "LinkedIn data comes only from search snippets." in job["limitations"]


def test_pipeline_ambiguous_waits_then_continues_after_select():
    pipe = make_pipe(search=AnySearch([LI_A, LI_B]))
    job = start(pipe, IndividualInput(name="Jane Doe"))
    assert job["status"] == "needs_input" and job["stages"][1]["status"] == "needs_input"
    assert [s["status"] for s in job["stages"][2:]] == ["pending"] * 4
    with pytest.raises(KeyError):
        pipe.select(job, "cand_nope")
    pipe.select(job, job["candidates"][1]["candidate_id"])
    pipe.run(job, "company_discovery")
    assert job["selected_candidate_id"] == job["candidates"][1]["candidate_id"] and job["status"] in ("completed", "partial")
    assert job["stages"][1]["status"] == "done"


def test_pipeline_all_sources_fail_low_confidence():
    pipe = make_pipe(search=AnySearch(boom=True), github=FakeGitHub(errors=["github /search/users: HTTP 403"]))
    job = start(pipe, IndividualInput(name="Jane Doe"))
    assert job["status"] == "needs_input" and job["candidates"] == [] and job["errors"]


def test_pipeline_unknown_company_skips_company_stages():
    job = start(make_pipe(fetch=fetch_ok("https://acme.ai", "Welcome to a page")), AUTO_INP)
    st = {s["name"]: s["status"] for s in job["stages"]}
    assert st["company_research"] == "skipped" and job["company"]["status"] == "unknown"
    assert job["sealapi"]["relevance"] == "insufficient_evidence" and job["status"] == "partial"


def test_pipeline_stage_crash_is_partial_and_retryable():
    pipe = make_pipe(researcher=CrashResearcher)
    job = start(pipe, AUTO_INP)
    st = {s["name"]: s["status"] for s in job["stages"]}
    assert job["status"] == "partial" and pipe.retry_stage(job) == "company_research"
    assert st["company_research"] == "failed" and st["verdict"] == "done" and st["professional_profile"] == "done"
    assert job["sealapi"]["relevance"] == "insufficient_evidence" and job["priority"]["label"] == "P2"
    assert any("company_research" in e for e in job["errors"])
    json.dumps(job)


def test_pipeline_discovery_crash_fails_job():
    class Boom(FakeGitHub):
        def search_users(self, name, limit=5):
            raise RuntimeError("x")
    job = start(make_pipe(github=Boom()), AUTO_INP)
    assert job["status"] == "failed" and job["stages"][0]["status"] == "failed"
    assert all(s["status"] == "skipped" for s in job["stages"][1:])


def test_retry_runs_from_failed_stage():
    pipe = make_pipe(researcher=CrashResearcher)
    job = start(pipe, AUTO_INP)
    pipe.company_researcher = FakeResearcher
    pipe.run(job, pipe.retry_stage(job))
    assert job["status"] == "completed"
    assert not any("company_research" in e for e in job["errors"])


def test_shared_github_errors_do_not_leak_into_job():
    gh = FakeGitHub(errors=["old"])
    job = start(make_pipe(github=gh), AUTO_INP)
    assert "old" not in json.dumps(job["errors"])
    gh2 = FakeGitHub(errors=["old"])
    gh2.get_repos = lambda login, limit=10: (gh2.errors.append("new repo error"), [])[1]
    job = start(make_pipe(github=gh2), AUTO_INP)
    assert any("new repo error" in e for e in job["errors"]) and "old" not in json.dumps(job["errors"])


def test_company_slots_entered_once_around_research():
    events = []

    class Slots:
        def __enter__(self):
            events.append("enter")

        def __exit__(self, *a):
            events.append("exit")

    class Rec(FakeResearcher):
        def research(self, record):
            events.append("research")
            return super().research(record)

    pipe = IndividualPipeline(AnySearch([LI_A]), FakeGitHub(), fetch_ok("https://acme.ai", "Acme AI - secure agents"),
                              company_researcher=Rec, company_slots=Slots())
    start(pipe, AUTO_INP)
    assert events == ["enter", "research", "exit"]


def test_memory_store_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    start(make_pipe(), AUTO_INP)
    s = MemoryCompanyStore()
    s.save({"company_id": "co_abcdef123456"})
    s.cache_put("co_abcdef123456", {"url": "https://a.com/", "normalized_url": "a.com"})
    assert s.load("co_abcdef123456") and s.cache_get("co_abcdef123456", "https://a.com/")
    assert list(tmp_path.iterdir()) == []
