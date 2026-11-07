import httpx

from src.lead_research.scraper import ScrapeResult
from src.lead_research.individual_discovery import (
    SEARCH_EMPTY_MSG, DuckDuckGoSource, GitHubSource, collect_observations,
    IndividualInput, Observation, build_discovery_queries, github_login_from_url,
    github_user_to_observation, linkedin_slug, merge_observations, parse_linkedin_title,
    parse_role_at_company, parse_search_hit, resolve_identity, score_candidate,
)


def obs_li(name, title, company, slug):
    return Observation(source_id=f"li:{slug}", source_type="search", url=f"https://www.linkedin.com/in/{slug}",
                       name=name, title=title, company=company, linkedin_slug=slug)


def obs_gh(name, company, login):
    return Observation(source_id=f"gh:{login}", source_type="github", url=f"https://github.com/{login}",
                       name=name, company=company, github_login=login, website="https://acme.ai")


def obs_search(name, title, company):
    return Observation(source_id="s:1", source_type="search", url="https://news.example.com/jane",
                       name=name, title=title, company=company)


def test_queries_name_only():
    qs = build_discovery_queries(IndividualInput(name="Jane Doe"))
    assert qs == ['"Jane Doe"', '"Jane Doe" linkedin', '"Jane Doe" (CEO OR CTO OR founder OR engineer)',
                  '"Jane Doe" github', '"Jane Doe" twitter OR x.com']


def test_role_query_ranks_ahead_of_github_and_twitter():
    qs = build_discovery_queries(IndividualInput(name="Jane Doe", company="Acme"))
    role = '"Jane Doe" (CEO OR CTO OR founder OR engineer)'
    assert role in qs and len(qs) == 5 and qs.index(role) < qs.index('"Jane Doe" github')
    assert '"Jane Doe" twitter OR x.com' not in qs


def test_context_query_uses_first_three_non_stopword_tokens():
    qs = build_discovery_queries(IndividualInput(name="Jane Doe", context="She works on the AI security team at a fintech in Berlin"))
    assert '"Jane Doe" AI security team' in qs and len(qs) <= 5
    qs = build_discovery_queries(IndividualInput(name="Jane Doe", company="Acme", context="fintech payments"))
    assert qs.index('"Jane Doe" "Acme"') < qs.index('"Jane Doe" fintech payments')


def test_queries_use_hints():
    qs = build_discovery_queries(IndividualInput(name="Jane Doe", company="Acme", location="Berlin"))
    assert '"Jane Doe" "Acme"' in qs and '"Jane Doe" Berlin' in qs and len(qs) <= 5
    assert len(qs) == len(set(qs))


def test_parse_linkedin_title():
    assert parse_linkedin_title("Jane Doe - CTO - Acme AI | LinkedIn") == ("Jane Doe", "CTO", "Acme AI")
    assert parse_linkedin_title("Jane Doe – Acme AI | LinkedIn") == ("Jane Doe", "", "Acme AI")


def test_parse_role_at_company():
    assert parse_role_at_company("Jane is the Chief Technology Officer at Acme AI, building...") == (
        "Chief Technology Officer", "Acme AI")
    assert parse_role_at_company("nothing here") == ("", "")


def test_slug_and_login():
    assert linkedin_slug("https://linkedin.com/in/b/") == "b"
    assert linkedin_slug("https://de.linkedin.com/in/Jane-Doe-123?x=1") == "jane-doe-123"
    assert linkedin_slug("https://example.com/in/x") == ""
    assert github_login_from_url("https://github.com/jdoe/repo") == "jdoe"
    assert github_login_from_url("https://github.com/orgs/foo") == ""


def test_parse_search_hit_rejects_other_person():
    hit = {"title": "John Smithson - CEO - Foo | LinkedIn", "url": "https://www.linkedin.com/in/jsmithson", "snippet": "x" * 30}
    assert parse_search_hit(hit, "John Smith", '"John Smith"') is None


def test_parse_search_hit_linkedin():
    hit = {"title": "Jane Doe - CTO - Acme AI | LinkedIn", "url": "https://www.linkedin.com/in/janedoe", "snippet": "Berlin · CTO at Acme AI"}
    ob = parse_search_hit(hit, "Jane Doe", '"Jane Doe"')
    assert ob.linkedin_slug == "janedoe" and ob.company == "Acme AI" and ob.title == "CTO"
    assert ob.location == "Berlin"


def test_parse_search_hit_truncates_snippet():
    hit = {"title": "Jane Doe interview", "url": "https://news.example.com/a", "snippet": "y" * 500}
    ob = parse_search_hit(hit, "Jane Doe", "q")
    assert ob is not None and len(ob.snippet) == 300


def test_github_company_url_or_domain_becomes_name_and_domain():
    for raw in ("https://vercel.com", "vercel.com", "https://www.vercel.com/"):
        ob = github_user_to_observation({"login": "jd", "name": "Jane Doe", "company": raw})
        assert ob.company == "Vercel" and ob.company_domain == "vercel.com", raw


def test_github_company_multiple_orgs_takes_first():
    ob = github_user_to_observation({"login": "jd", "name": "Jane Doe", "company": "@vercel @nextjs"})
    assert ob.company == "vercel" and ob.company_domain == ""
    ob = github_user_to_observation({"login": "jd", "name": "Jane Doe", "company": "Next.js"})
    assert ob.company == "Next.js" and ob.company_domain == ""
    import json
    from dataclasses import asdict
    json.dumps(asdict(ob))


def test_github_bio_sets_title():
    assert github_user_to_observation({"login": "jd", "name": "Jane Doe", "bio": "@vercel CEO"}).title == "CEO"
    assert github_user_to_observation({"login": "jd", "name": "Jane Doe", "bio": "Co-founder & CTO at Acme"}).title == "Co-founder & CTO"
    assert github_user_to_observation({"login": "jd", "name": "Jane Doe", "bio": "VP of Engineering at Acme"}).title == "VP of Engineering"
    assert github_user_to_observation({"login": "jd", "name": "Jane Doe", "bio": "Senior Software Engineer"}).title == "Senior Software Engineer"
    assert github_user_to_observation({"login": "jd", "name": "Jane Doe", "bio": "Chief Product Officer"}).title == "Chief Product Officer"
    assert github_user_to_observation({"login": "jd", "name": "Jane Doe", "bio": "dad, hiker, coffee"}).title == ""
    assert len(github_user_to_observation({"login": "jd", "name": "Jane Doe", "bio": "Head of " + "x" * 300}).title) <= 120


def test_context_token_in_candidate_boosts_score():
    c = merge_observations([obs_li("Jane Doe", "Security Engineer", "Acme Fintech", "a")], "Jane Doe")[0]
    plain = score_candidate(c, IndividualInput(name="Jane Doe")).confidence
    boosted = score_candidate(c, IndividualInput(name="Jane Doe", context="the fintech one"))
    assert round(boosted.confidence - plain, 2) == 0.10
    assert any("context" in r for r in boosted.confidence_reasons)
    unrelated = score_candidate(c, IndividualInput(name="Jane Doe", context="a nurse in Ohio"))
    assert unrelated.confidence == plain


def test_github_user_to_observation():
    ob = github_user_to_observation({"login": "jdoe", "name": "Jane Doe", "company": "@Acme AI", "blog": "https://j.dev",
                                     "html_url": "https://github.com/jdoe", "bio": "b" * 400})
    assert ob.source_type == "github" and ob.github_login == "jdoe" and ob.company == "Acme AI"
    assert ob.website == "https://j.dev" and len(ob.snippet) == 300
    assert github_user_to_observation({"company": "x"}) is None


def test_same_name_different_companies_not_merged():
    obs = [obs_li("Jane Doe", "CTO", "Acme AI", "janedoe"), obs_li("Jane Doe", "Nurse", "City Hospital", "jane-doe-rn")]
    assert len(merge_observations(obs, "Jane Doe")) == 2


def test_shared_company_merges_github_and_linkedin():
    obs = [obs_li("Jane Doe", "CTO", "Acme AI", "janedoe"), obs_gh("Jane Doe", "Acme AI", "jdoe")]
    cands = merge_observations(obs, "Jane Doe")
    assert len(cands) == 1 and cands[0].github_login == "jdoe" and cands[0].linkedin_slug == "janedoe"
    assert cands[0].website == "https://acme.ai"
    assert cands[0].candidate_id.startswith("cand_") and len(cands[0].candidate_id) == 15


def test_bare_observation_attaches_to_single_company_candidate():
    bare = Observation(source_id="s:2", source_type="search", url="https://x.example.com", name="Jane Doe")
    assert len(merge_observations([obs_li("Jane Doe", "CTO", "Acme AI", "a"), bare], "Jane Doe")) == 1
    two = [obs_li("Jane Doe", "CTO", "Acme AI", "a"), obs_li("Jane Doe", "VP", "Beta", "b"), bare]
    assert len(merge_observations(two, "Jane Doe")) == 3


def test_single_corroborated_candidate_auto_selects():
    d = resolve_identity([obs_li("Jane Doe", "CTO", "Acme AI", "janedoe"), obs_gh("Jane Doe", "Acme AI", "jdoe"),
                          obs_search("Jane Doe", "CTO", "Acme AI")], IndividualInput(name="Jane Doe"))
    assert d.mode == "auto" and d.selected_id == d.candidates[0].candidate_id


def test_two_plausible_requires_selection():
    d = resolve_identity([obs_li("Jane Doe", "CTO", "Acme AI", "a"), obs_li("Jane Doe", "VP Eng", "Beta", "b")],
                         IndividualInput(name="Jane Doe"))
    assert d.mode == "select" and len(d.candidates) == 2


def test_supplied_linkedin_url_auto_selects():
    d = resolve_identity([obs_li("Jane Doe", "CTO", "Acme AI", "a"), obs_li("Jane Doe", "VP Eng", "Beta", "b")],
                         IndividualInput(name="Jane Doe", linkedin_url="https://linkedin.com/in/b/"))
    assert d.mode == "auto" and d.candidates[0].linkedin_slug == "b"
    assert d.candidates[0].confidence >= 0.95


def test_hints_raise_score():
    inp = IndividualInput(name="Jane Doe", company="Acme AI", location="Berlin")
    base = merge_observations([obs_li("Jane Doe", "CTO", "Acme AI", "a")], "Jane Doe")[0]
    plain = score_candidate(base, IndividualInput(name="Jane Doe")).confidence
    c = merge_observations([obs_li("Jane Doe", "CTO", "Acme AI", "a")], "Jane Doe")[0]
    c.location = "Berlin, Germany"
    assert score_candidate(c, inp).confidence > plain


def test_no_observations_low_confidence():
    d = resolve_identity([], IndividualInput(name="Jane Doe"))
    assert d.mode == "low_confidence" and d.selected_id == ""


def test_url_match_auto_selects_despite_close_runner_up():
    obs = [obs_li("Jane Doe", "CTO", "Acme", "a"), obs_li("Jane Doe", "VP Eng", "Beta", "b")]
    inp = IndividualInput(name="Jane Doe", company="Acme", linkedin_url="https://linkedin.com/in/b/")
    d = resolve_identity(obs, inp)
    scores = sorted(c.confidence for c in d.candidates)
    assert scores[-1] >= 0.95 and scores[-2] > 0.70
    assert d.mode == "auto" and d.candidates[0].linkedin_slug == "b"
    assert d.selected_id == d.candidates[0].candidate_id


def test_github_url_match_auto_selects():
    obs = [obs_gh("Jane Doe", "Acme", "jdoe"), obs_li("Jane Doe", "VP Eng", "Beta", "b")]
    d = resolve_identity(obs, IndividualInput(name="Jane Doe", github_url="https://github.com/JDoe"))
    assert d.mode == "auto" and d.candidates[0].github_login == "jdoe"


def test_oversized_fields_are_capped():
    hit = {"title": "Jane Doe - " + "T" * 500 + " - " + "C" * 500 + " | LinkedIn",
           "url": "https://www.linkedin.com/in/janedoe", "snippet": "s" * 1000}
    ob = parse_search_hit(hit, "Jane Doe", "q")
    assert len(ob.title) == 120 and len(ob.company) == 120
    big = Observation(source_id="x", source_type="search", url="https://e.com", name="Jane Doe",
                      title="T" * 500, company="C" * 500, location="L" * 500)
    c = merge_observations([big], "Jane Doe")[0]
    assert len(c.title) == len(c.company) == len(c.location) == 120
    role, co = parse_role_at_company("x" * 400 + " is the CTO at Acme")
    assert (role, co) == ("", "")


def test_url_matched_candidate_ranks_first_even_if_other_scores_higher():
    obs = [obs_li("Jane Doe", "CTO", "Acme", "a"), obs_gh("Jane Doe", "Acme", "ghx"),
           obs_search("Jane Doe", "CTO", "Acme"), obs_li("Jane Doe", "VP Eng", "Beta", "b")]
    inp = IndividualInput(name="Jane Doe", company="Acme", linkedin_url="https://linkedin.com/in/b/")
    d = resolve_identity(obs, inp)
    other = [c for c in d.candidates if c.linkedin_slug == "a"][0]
    assert other.confidence > 0.95
    assert d.candidates[0].linkedin_slug == "b" and d.mode == "auto"
    assert d.selected_id == d.candidates[0].candidate_id


class FakeSearch:
    def __init__(self, hits):
        self.hits = hits

    def search(self, query):
        return self.hits.get(query, [])


class RaisingSearch:
    def search(self, query):
        raise RuntimeError("boom")


class FakeGitHub:
    def __init__(self, users=(), profiles=None):
        self.users, self.profiles, self.errors = list(users), profiles or {}, []

    def search_users(self, name, limit=5):
        return [{"login": u} for u in self.users]

    def get_user(self, login):
        return self.profiles.get(login)


def page_result(url, text):
    return ScrapeResult(url=url, success=True, title="Home", extracted_text=text)


def no_fetch(url):
    raise AssertionError("should not fetch")


def test_github_source_maps_users_and_survives_rate_limit():
    def handler(request):
        if request.url.path == "/search/users":
            return httpx.Response(200, json={"items": [{"login": "jdoe"}]})
        if request.url.path == "/users/jdoe":
            return httpx.Response(200, json={"login": "jdoe", "name": "Jane Doe"})
        return httpx.Response(403, json={"message": "rate limited"})

    gh = GitHubSource(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert gh.search_users("Jane Doe")[0]["login"] == "jdoe"
    assert gh.get_user("jdoe")["name"] == "Jane Doe"
    assert gh.get_repos("other") == [] and gh.errors


def test_collect_observations_never_fetches_linkedin_or_x():
    fetched = []
    obs, sources, errors = collect_observations(
        IndividualInput(name="Jane Doe", linkedin_url="https://linkedin.com/in/janedoe", x_url="https://x.com/jd",
                        website="https://janedoe.dev"),
        FakeSearch({}), FakeGitHub(),
        lambda url: fetched.append(url) or page_result(url, "Jane Doe CTO at Acme AI"))
    assert fetched == ["https://janedoe.dev"]
    web = [o for o in obs if o.source_type == "website"]
    assert web and web[0].company == "Acme AI"
    assert {s["source_id"] for s in sources} == {o.source_id for o in obs}


def test_collect_observations_search_failure_is_recorded():
    obs, sources, errors = collect_observations(IndividualInput(name="Jane Doe"), RaisingSearch(), FakeGitHub(), no_fetch)
    assert obs == [] and errors


def test_all_queries_empty_records_search_blocked_error():
    _, _, errors = collect_observations(IndividualInput(name="Jane Doe"), FakeSearch({}), FakeGitHub(), no_fetch)
    assert SEARCH_EMPTY_MSG in errors
    some = FakeSearch({'"Jane Doe"': [{"title": "Unrelated", "url": "https://e.com/x", "snippet": ""}]})
    _, _, errors = collect_observations(IndividualInput(name="Jane Doe"), some, FakeGitHub(), no_fetch)
    assert SEARCH_EMPTY_MSG not in errors


def test_duckduckgo_redirect_links_are_decoded():
    class FakeScraper:
        def search_person(self, name, company, custom_query=None):
            return [{"title": "Jane Doe - CTO - Acme AI | LinkedIn", "snippet": "",
                     "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.linkedin.com%2Fin%2Fjane-doe&rut=abc"}]

    hits = DuckDuckGoSource(scraper=FakeScraper()).search('"Jane Doe"')
    assert hits[0]["url"] == "https://www.linkedin.com/in/jane-doe"
    assert parse_search_hit(hits[0], "Jane Doe", "q").linkedin_slug == "jane-doe"


def test_github_rate_limit_is_explicit_and_stops_calls():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1767225600"},
                              json={"message": "API rate limit exceeded"})

    gh = GitHubSource(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert gh.search_users("Jane Doe") == [] and gh.get_user("jdoe") is None and gh.get_repos("jdoe") == []
    assert calls == ["/search/users"] and gh.rate_limited
    assert gh.errors == ["GitHub API rate limit reached; resets at 00:00 UTC"]


def test_github_429_without_quota_header_is_ordinary_error():
    gh = GitHubSource(client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))))
    assert gh.get_user("a") is None and gh.get_user("b") is None
    assert not gh.rate_limited and len(gh.errors) == 2


def test_github_user_lookups_capped_at_three():
    looked_up = []

    def handler(request):
        if request.url.path == "/search/users":
            per_page = int(request.url.params.get("per_page", "0"))
            return httpx.Response(200, json={"items": [{"login": f"u{i}"} for i in range(max(per_page, 5))]})
        looked_up.append(request.url.path)
        return httpx.Response(200, json={"login": request.url.path.rsplit("/", 1)[-1], "name": "Jane Doe"})

    gh = GitHubSource(client=httpx.Client(transport=httpx.MockTransport(handler)))
    collect_observations(IndividualInput(name="Jane Doe"), FakeSearch({}), gh, no_fetch)
    assert looked_up == ["/users/u0", "/users/u1", "/users/u2"]


def test_collect_observations_github_name_filter_and_supplied_url():
    gh = FakeGitHub(users=["jdoe", "other"], profiles={
        "jdoe": {"login": "jdoe", "name": "Jane Doe", "html_url": "https://github.com/jdoe"},
        "other": {"login": "other", "name": "Bob Smith", "html_url": "https://github.com/other"},
        "pinned": {"login": "pinned", "name": "J. Nickname", "html_url": "https://github.com/pinned"},
    })
    obs, sources, _ = collect_observations(
        IndividualInput(name="Jane Doe", github_url="https://github.com/pinned"), FakeSearch({}), gh, no_fetch)
    assert sorted(o.github_login for o in obs) == ["jdoe", "pinned"]


def test_collect_observations_website_without_name_is_dropped():
    obs, sources, errors = collect_observations(
        IndividualInput(name="Jane Doe", website="https://x.example"), FakeSearch({}), FakeGitHub(),
        lambda url: page_result(url, "Someone else entirely"))
    assert obs == [] and sources == []
