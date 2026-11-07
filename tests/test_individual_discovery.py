from src.lead_research.individual_discovery import (
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
    assert qs[0] == '"Jane Doe"'
    assert '"Jane Doe" linkedin' in qs
    assert len(qs) <= 5


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
