# Individual Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Name-only individual discovery that resolves identity, finds the current company, researches its AI usage and returns a SealAPI relevance verdict, shown on a new `/individual` page.

**Architecture:** Two new backend modules: `individual_discovery.py` (sources, parsing, candidate merging, identity decision) and `individual_research.py` (company discovery, profile, verdict, in-memory job store, stage pipeline). The pipeline reuses `CompanyResearcher` with an in-memory store. FastAPI endpoints run each job in a thread. Next.js page polls job state.

**Tech Stack:** Python 3.11, FastAPI, Scrapling (`ScraplingScraper`), httpx (GitHub REST), pytest; Next.js 14, React 18, Tailwind, lucide-react, node:test.

**Spec:** `docs/superpowers/specs/2026-11-07-individual-research-design.md`

## Global Constraints

- No new dependencies (httpx is already in `requirements.txt`). No API keys. No LLM.
- Nothing written to disk: no `DATA_DIR` writes, no page cache files.
- DuckDuckGo via `ScraplingScraper(use_browser=False, use_tor=False)` only. LinkedIn and X URLs are never fetched.
- `sealapi_capabilities.py`, the bulk import pipeline and existing endpoints are unchanged.
- Thresholds: auto-select top ≥ 0.75 and runner-up ≤ top − 0.25 (or supplied-URL match); candidate floor 0.35.
- Jobs: max 50, TTL 1 hour, id `^ind_[0-9a-f]{16}$`.
- Stage names, in order: `discovery`, `identity_resolution`, `company_discovery`, `company_research`, `professional_profile`, `verdict`. Stage statuses: `pending|running|done|skipped|failed|needs_input`.
- Job `status`: `running|needs_input|completed|partial|failed`.
- All new endpoints use `Depends(verify_api_key)`.
- Scraped text is untrusted: rendered as text only, truncated (snippets ≤ 300 chars).

## Review Focus

1. Two different people with the same name at different companies must stay two candidates (never merged) — test in Task 1.
2. A search result whose title names a different person (e.g. "John Smithson") must not become an observation — test in Task 1.
3. Every source failing (DDG throttled, GitHub 403 rate limit) must yield `low_confidence`, not a crash or 500 — test in Task 4.
4. Selecting a candidate twice, or selecting while the job is still running, returns 409 and does not start a second worker — test in Task 5.
5. A company homepage that fails corroboration must leave the company Unknown and mark company stages `skipped`, never guess the employer — test in Task 3.

---

### Task 1: Discovery parsing, candidate merging and identity decision

**Files:**
- Create: `src/lead_research/individual_discovery.py`
- Test: `tests/test_individual_discovery.py`

**Interfaces:**
- Produces:
  - `@dataclass IndividualInput(name: str, company="", linkedin_url="", x_url="", github_url="", website="", location="", context="")`
  - `@dataclass Observation(source_id: str, source_type: str, url: str, name: str, title="", company="", location="", avatar_url="", snippet="", linkedin_slug="", github_login="", website="", query="")` — `source_type` ∈ `search|github|website`
  - `@dataclass Candidate(candidate_id: str, name: str, title: str, company: str, location: str, avatar_url: str, profile_url: str, description: str, linkedin_slug: str, github_login: str, website: str, observations: List[Observation], confidence: float = 0.0, confidence_reasons: List[str])` with `to_dict() -> dict`
  - `build_discovery_queries(inp: IndividualInput) -> List[str]` (≤ 5, deduped)
  - `parse_linkedin_title(title: str) -> Tuple[str, str, str]` → `(name, role, company)`
  - `parse_role_at_company(text: str) -> Tuple[str, str]` → `(role, company)`
  - `linkedin_slug(url: str) -> str`, `github_login_from_url(url: str) -> str`
  - `parse_search_hit(hit: Dict[str, str], name: str, query: str) -> Optional[Observation]`
  - `github_user_to_observation(user: dict) -> Optional[Observation]` (None if user's `name` incompatible is decided by caller; this maps fields only)
  - `merge_observations(observations: List[Observation], name: str) -> List[Candidate]`
  - `score_candidate(c: Candidate, inp: IndividualInput) -> Candidate` (sets `confidence`, `confidence_reasons`)
  - `@dataclass IdentityDecision(mode: str, selected_id: str, candidates: List[Candidate], message: str)` — `mode` ∈ `auto|select|low_confidence`
  - `resolve_identity(observations: List[Observation], inp: IndividualInput) -> IdentityDecision` (candidates sorted by confidence desc, those < 0.35 dropped from `select`)
  - Constants `AUTO_SELECT_MIN = 0.75`, `AUTO_SELECT_MARGIN = 0.25`, `CANDIDATE_MIN = 0.35`

- [ ] **Step 1: Write failing tests**

```python
def test_queries_name_only():
    qs = build_discovery_queries(IndividualInput(name="Jane Doe"))
    assert qs[0] == '"Jane Doe"'
    assert '"Jane Doe" linkedin' in qs
    assert len(qs) <= 5

def test_queries_use_hints():
    qs = build_discovery_queries(IndividualInput(name="Jane Doe", company="Acme", location="Berlin"))
    assert '"Jane Doe" "Acme"' in qs and '"Jane Doe" Berlin' in qs and len(qs) <= 5

def test_parse_linkedin_title():
    assert parse_linkedin_title("Jane Doe - CTO - Acme AI | LinkedIn") == ("Jane Doe", "CTO", "Acme AI")
    assert parse_linkedin_title("Jane Doe – Acme AI | LinkedIn") == ("Jane Doe", "", "Acme AI")

def test_parse_role_at_company():
    assert parse_role_at_company("Jane is the Chief Technology Officer at Acme AI, building...") == ("Chief Technology Officer", "Acme AI")

def test_parse_search_hit_rejects_other_person():
    hit = {"title": "John Smithson - CEO - Foo | LinkedIn", "url": "https://www.linkedin.com/in/jsmithson", "snippet": "x" * 30}
    assert parse_search_hit(hit, "John Smith", '"John Smith"') is None

def test_parse_search_hit_linkedin():
    hit = {"title": "Jane Doe - CTO - Acme AI | LinkedIn", "url": "https://www.linkedin.com/in/janedoe", "snippet": "Berlin · CTO at Acme AI"}
    ob = parse_search_hit(hit, "Jane Doe", '"Jane Doe"')
    assert ob.linkedin_slug == "janedoe" and ob.company == "Acme AI" and ob.title == "CTO"

def test_same_name_different_companies_not_merged():
    obs = [obs_li("Jane Doe", "CTO", "Acme AI", "janedoe"), obs_li("Jane Doe", "Nurse", "City Hospital", "jane-doe-rn")]
    assert len(merge_observations(obs, "Jane Doe")) == 2

def test_shared_company_merges_github_and_linkedin():
    obs = [obs_li("Jane Doe", "CTO", "Acme AI", "janedoe"), obs_gh("Jane Doe", "Acme AI", "jdoe")]
    cands = merge_observations(obs, "Jane Doe")
    assert len(cands) == 1 and cands[0].github_login == "jdoe" and cands[0].linkedin_slug == "janedoe"

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

def test_no_observations_low_confidence():
    d = resolve_identity([], IndividualInput(name="Jane Doe"))
    assert d.mode == "low_confidence" and d.selected_id == ""
```

`obs_li`, `obs_gh`, `obs_search` are local test helpers building `Observation`s.

- [ ] **Step 2: Run** `pytest tests/test_individual_discovery.py -v` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement `individual_discovery.py`.**
  - Name check uses `identity.names_compatible`; a hit is kept only if the parsed name (LinkedIn title part / text before first ` - `, ` | `, ` – `) is compatible, or the exact full name appears in title.
  - Merge key, in order: shared LinkedIn slug, shared GitHub login, same normalized company (`company_intel.normalize_company_name`). Observations with no company and no handle attach to the single company-bearing candidate only when exactly one exists; otherwise they form their own candidate.
  - `candidate_id` = `cand_` + 10-hex sha1 of the merge key.
  - Scoring (cap 1.0): exact name 0.30; title present 0.10; company present 0.15; +0.12 per additional independent source type/URL beyond the first (max +0.36); hint company match +0.20; hint location match +0.10; supplied LinkedIn/GitHub URL handle match → set to max(score, 0.95) and mark `url_match`. Reasons list explains each addition.
  - Truncate snippets/descriptions to 300 chars.

- [ ] **Step 4: Run** `pytest tests/test_individual_discovery.py -v` — Expected: PASS.

- [ ] **Step 5: Commit** `feat(individual): discovery parsing and identity resolution`

---

### Task 2: Discovery sources (DuckDuckGo, GitHub, personal website)

**Files:**
- Modify: `src/lead_research/individual_discovery.py`
- Test: `tests/test_individual_discovery.py`

**Interfaces:**
- Consumes: Task 1 types.
- Produces:
  - `class SearchSource(Protocol): def search(self, query: str) -> List[Dict[str, str]]`
  - `class DuckDuckGoSource: __init__(self, scraper: Optional[ScraplingScraper] = None)`; `search(query)` calls `scraper.search_person("", "", custom_query=query)`; default scraper `ScraplingScraper(use_browser=False, use_tor=False)`.
  - `class GitHubSource: __init__(self, client: Optional[httpx.Client] = None, base_url="https://api.github.com")`; `search_users(name: str, limit: int = 5) -> List[dict]`; `get_user(login: str) -> Optional[dict]`; `get_repos(login: str, limit: int = 10) -> List[dict]`. Any non-200/exception → `[]`/`None` and the error is appended to `self.errors: List[str]`.
  - `collect_observations(inp: IndividualInput, search: SearchSource, github: GitHubSource, fetch: Callable[[str], ScrapeResult]) -> Tuple[List[Observation], List[dict], List[str]]` → `(observations, sources, errors)`; `sources` items: `{source_id, url, source_type, title, retrieved_at, query}`.

- [ ] **Step 1: Write failing tests**

```python
def test_github_source_maps_users_and_survives_rate_limit():
    transport = httpx.MockTransport(handler)  # /search/users -> 1 item, /users/jdoe -> profile, else 403
    gh = GitHubSource(client=httpx.Client(transport=transport))
    assert gh.search_users("Jane Doe")[0]["login"] == "jdoe"
    assert gh.get_repos("other") == [] and gh.errors

def test_collect_observations_never_fetches_linkedin_or_x():
    fetched = []
    obs, sources, errors = collect_observations(
        IndividualInput(name="Jane Doe", linkedin_url="https://linkedin.com/in/janedoe", x_url="https://x.com/jd",
                        website="https://janedoe.dev"),
        FakeSearch({...}), FakeGitHub(...), lambda url: fetched.append(url) or page_result(url, "Jane Doe CTO at Acme AI"))
    assert fetched == ["https://janedoe.dev"]
    assert any(o.source_type == "website" for o in obs)

def test_collect_observations_search_failure_is_recorded():
    obs, sources, errors = collect_observations(IndividualInput(name="Jane Doe"), RaisingSearch(), FakeGitHub(), no_fetch)
    assert obs == [] and errors
```

- [ ] **Step 2: Run** `pytest tests/test_individual_discovery.py -v` — Expected: new tests FAIL.
- [ ] **Step 3: Implement.** GitHub requests: `User-Agent: SealAPIResearchBot/1.0`, `Accept: application/vnd.github+json`, timeout 10 s; search query `"<name>" in:name type:user`; call `get_user` for each search hit (max 5) and for `github_login_from_url(inp.github_url)`. Website observation: name must appear in page text; role/company from `parse_role_at_company` on title + meta + first 2000 chars; `website` = the URL.
- [ ] **Step 4: Run** `pytest tests/test_individual_discovery.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(individual): DuckDuckGo, GitHub and website discovery sources`

---

### Task 3: Company discovery, professional profile, verdict and priority

**Files:**
- Create: `src/lead_research/individual_research.py`
- Test: `tests/test_individual_research.py`

**Interfaces:**
- Consumes: `Candidate`, `IndividualInput`, `SearchSource` (Task 1–2); `is_company_corroborated` (research.py); `normalize_domain`, `FREE_MAIL_DOMAINS` (company_intel.py).
- Produces:
  - `SOCIAL_DOMAINS` (linkedin.com, x.com, twitter.com, github.com, facebook.com, instagram.com, youtube.com, medium.com, crunchbase.com, wikipedia.org, …)
  - `discover_company(candidate: Candidate, inp: IndividualInput, search: SearchSource, fetch: Callable[[str], ScrapeResult]) -> dict` → `{name, domain, domain_source, corroborated: bool, note, status: "verified"|"unknown"}`; company name = candidate company, else `inp.company`.
  - `classify_role(title: str) -> dict` → `{category, authority, basis: "inferred"}`; categories exactly: `Founder / Co-founder, CEO, CTO, CISO, VP Engineering, AI/ML Leader, Security Architect, AI Engineer, Engineering Manager, Other`; authority ∈ `executive|senior_leader|practitioner|unknown`.
  - `ai_repo_signals(repos: List[dict]) -> List[dict]` → `{repo, url, matched: [keywords], language}` for repos whose name/description/topics match AI keywords (`llm, gpt, openai, anthropic, claude, langchain, rag, embedding, transformer, machine learning, ml, ai, agent, vector`).
  - `build_professional_profile(candidate: Candidate, repos: List[dict]) -> dict` → `{current_title, current_company, location, role, facts: [{text, basis: "verified"|"inferred", source_ids}], github: {login, public_repos, languages, ai_repos}}`
  - `sealapi_verdict(company_record: Optional[dict]) -> dict` → `{relevance, fit_label, reasoning, opportunities, discovery_questions, scope_note}`; relevance ∈ `relevant|needs_validation|not_relevant|insufficient_evidence`.
  - `assign_priority(relevance: str, role: dict) -> dict` → `{level: 0|1|2, label: "P0"|"P1"|"P2", reasons: [str]}`.

- [ ] **Step 1: Write failing tests**

```python
def test_company_domain_from_github_blog_corroborated():
    c = cand(company="Acme AI", github_blog="https://acme.ai")
    out = discover_company(c, IndividualInput(name="Jane Doe"), FakeSearch({}), fetch_ok("https://acme.ai", "Acme AI - secure agents"))
    assert out == {**out, "domain": "acme.ai", "status": "verified", "corroborated": True, "domain_source": "github_blog"}

def test_company_uncorroborated_is_unknown():
    c = cand(company="Acme AI", github_blog="https://randomblog.io")
    out = discover_company(c, IndividualInput(name="Jane Doe"), FakeSearch({}), fetch_ok("https://randomblog.io", "My cooking blog"))
    assert out["status"] == "unknown" and out["domain"] == ""

def test_company_domain_from_official_site_search_skips_social():
    search = FakeSearch({'"Acme AI" official site': [{"url": "https://www.linkedin.com/company/acme"}, {"url": "https://acme.ai/"}]})
    out = discover_company(cand(company="Acme AI"), IndividualInput(name="Jane Doe"), search, fetch_ok("https://acme.ai/", "Acme AI"))
    assert out["domain"] == "acme.ai" and out["domain_source"] == "search"

def test_no_company_is_unknown_without_fetching():
    out = discover_company(cand(company=""), IndividualInput(name="Jane Doe"), FakeSearch({}), fail_if_called)
    assert out["status"] == "unknown"

@pytest.mark.parametrize("title,cat,auth", [
    ("Co-Founder & CEO", "Founder / Co-founder", "executive"), ("Chief Technology Officer", "CTO", "executive"),
    ("CISO", "CISO", "executive"), ("VP of Engineering", "VP Engineering", "senior_leader"),
    ("Head of Machine Learning", "AI/ML Leader", "senior_leader"), ("Senior AI Engineer", "AI Engineer", "practitioner"),
    ("Engineering Manager", "Engineering Manager", "senior_leader"), ("", "Other", "unknown")])
def test_classify_role(title, cat, auth):
    r = classify_role(title); assert (r["category"], r["authority"]) == (cat, auth)

@pytest.mark.parametrize("fit,rel", [("strong", "relevant"), ("validation_required", "needs_validation"),
    ("weak", "not_relevant"), ("not_suitable", "not_relevant"), ("insufficient_evidence", "insufficient_evidence")])
def test_verdict_mapping(fit, rel):
    assert sealapi_verdict({"company_fit": {"classification": fit, "label": "x", "reasoning": "r"}})["relevance"] == rel

def test_verdict_unknown_company():
    assert sealapi_verdict(None)["relevance"] == "insufficient_evidence"

def test_priority_rules():
    assert assign_priority("relevant", {"category": "CTO", "authority": "executive"})["level"] == 0
    assert assign_priority("needs_validation", {"category": "AI Engineer", "authority": "practitioner"})["level"] == 1
    assert assign_priority("not_relevant", {"category": "CEO", "authority": "executive"})["level"] == 1
    assert assign_priority("insufficient_evidence", {"category": "CTO", "authority": "executive"})["level"] == 2
```

- [ ] **Step 2: Run** `pytest tests/test_individual_research.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement.** Domain candidates in order: candidate GitHub blog (`domain_source="github_blog"`), `inp.website` / candidate website and its links (`"website"`), non-social observation URLs whose domain contains the company's distinctive token (`"search_result"`), then search `"<Company>" official site` first non-social, non-free-mail result (`"search"`). For each, fetch `https://<domain>/` and accept the first passing `is_company_corroborated`. P0 role rule: authority `executive` or category in {CISO, Security Architect, AI/ML Leader}. Opportunities/discovery questions come from the company record (`opportunities`, `discovery_questions`), max 5 each; `scope_note` from `SCOPE_NOTE`.
- [ ] **Step 4: Run** `pytest tests/test_individual_research.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(individual): company discovery, role classification and SealAPI verdict`

---

### Task 4: In-memory store, job store and stage pipeline

**Files:**
- Modify: `src/lead_research/individual_research.py`
- Test: `tests/test_individual_research.py`

**Interfaces:**
- Consumes: Tasks 1–3; `CompanyResearcher`, `new_company_record`, `normalize_company_name`, `_hash`-style id (`co_` + 12 hex of domain) from company_intel.
- Produces:
  - `class MemoryCompanyStore` — same methods `CompanyResearcher` uses: `load(id)`, `save(record)`, `cache_get(id, url, max_age=...)`, `cache_put(id, page)`; dict-backed, thread-safe, no file IO.
  - `STAGES: List[str]` (the six names), `JOB_ID_RE`.
  - `class IndividualJobStore(max_jobs: int = 50, ttl: timedelta = timedelta(hours=1), now=...)`: `create(inp: IndividualInput) -> dict`, `get(job_id: str) -> Optional[dict]` (raises `ValueError` on bad id), `lock(job_id) -> threading.Lock`; evicts expired then oldest.
  - Job dict: `{job_id, status, created_at, updated_at, input, stages: [{name, status, message, started_at, finished_at}], candidates, selected_candidate_id, identity, person, company, ai_usage, sealapi, priority, sources, errors, limitations, running: bool}`.
  - `class IndividualPipeline(search: SearchSource, github: GitHubSource, fetch: Callable[[str], ScrapeResult], company_researcher: Callable[[MemoryCompanyStore], CompanyResearcher] = CompanyResearcher)`:
    - `run(job: dict, start_stage: str = "discovery") -> None` — runs stages from `start_stage` to the end or until `needs_input`; each stage wrapped so an exception marks it `failed`, records the error and continues with later stages marked `skipped`.
    - `select(job: dict, candidate_id: str) -> None` — raises `KeyError` if unknown; sets selection, marks `identity_resolution` done.
    - `retry_stage(job: dict) -> Optional[str]` — first `failed` or `skipped` stage name, or None.
  - `ai_usage` = `{ai_findings: [{evidence, source_url, label}], providers: [str], ai_products: [name]}` from company record findings with category `ai`/`ai_provider`.
  - Final job `status`: `needs_input` if any stage needs input; `failed` if discovery failed; `partial` if any stage failed/skipped; else `completed`.

- [ ] **Step 1: Write failing tests**

```python
def test_job_store_eviction_and_id_validation():
    t = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    store = IndividualJobStore(max_jobs=2, ttl=timedelta(hours=1), now=lambda: t[0])
    a = store.create(IndividualInput(name="A B")); store.create(IndividualInput(name="C D")); store.create(IndividualInput(name="E F"))
    assert store.get(a["job_id"]) is None
    t[0] += timedelta(hours=2)
    assert all(store.get(j) is None for j in list(store._jobs))
    with pytest.raises(ValueError): store.get("../etc")

def test_pipeline_auto_path_completes_with_verdict():
    job = run_pipeline(fakes_single_match_with_ai_company())
    assert job["status"] == "completed"
    assert [s["status"] for s in job["stages"]] == ["done"] * 6
    assert job["company"]["domain"] == "acme.ai" and job["sealapi"]["relevance"] in ("relevant", "needs_validation")
    assert job["ai_usage"]["providers"] == ["OpenAI"] and job["priority"]["label"] == "P0"

def test_pipeline_ambiguous_waits_then_continues_after_select():
    pipe, job = start(fakes_two_matches())
    assert job["status"] == "needs_input" and job["stages"][1]["status"] == "needs_input"
    pipe.select(job, job["candidates"][1]["candidate_id"]); pipe.run(job, "company_discovery")
    assert job["selected_candidate_id"] == job["candidates"][1]["candidate_id"] and job["status"] in ("completed", "partial")

def test_pipeline_all_sources_fail_low_confidence():
    job = run_pipeline(fakes_everything_fails())
    assert job["status"] == "needs_input" and job["candidates"] == [] and job["errors"]

def test_pipeline_unknown_company_skips_company_stages():
    job = run_pipeline(fakes_single_match_uncorroborated_site())
    st = {s["name"]: s["status"] for s in job["stages"]}
    assert st["company_research"] == "skipped" and job["company"]["status"] == "unknown"
    assert job["sealapi"]["relevance"] == "insufficient_evidence" and job["status"] == "partial"

def test_pipeline_stage_crash_is_partial_and_retryable():
    pipe, job = start(fakes_company_researcher_raises())
    assert job["status"] == "partial" and pipe.retry_stage(job) == "company_research"

def test_memory_store_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); run_pipeline(fakes_single_match_with_ai_company())
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run** `pytest tests/test_individual_research.py -v` — Expected: new tests FAIL.
- [ ] **Step 3: Implement.** `company_research` stage: build record with `new_company_record({"company_id": ..., "name": company name, "domain": domain, "domain_source": source})`, run `company_researcher(MemoryCompanyStore()).research(record)`, keep the record minus `pages[].text`/`links` in `job["company"]["intel"]`. `professional_profile` fetches GitHub repos when the candidate has a login. Sources list merges discovery sources and company pages (`url`, `title`, `accessed_at`, `source_type="company_site"`). Limitations: the spec's Known limits plus "LinkedIn data comes only from search snippets" when a LinkedIn observation was used.
- [ ] **Step 4: Run** `pytest tests/test_individual_research.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(individual): in-memory job store and research pipeline`

---

### Task 5: API endpoints

**Files:**
- Modify: `src/lead_research/server.py` (new section after "Company intelligence", before `@app.get("/")`)
- Test: `tests/test_individual_api.py`

**Interfaces:**
- Consumes: `IndividualJobStore`, `IndividualPipeline`, `IndividualInput`, `DuckDuckGoSource`, `GitHubSource`.
- Produces (server module attributes tests can monkeypatch): `individual_jobs: IndividualJobStore`, `make_individual_pipeline() -> IndividualPipeline`, `_spawn(fn, *args) -> None` (starts a daemon thread).
  - `class IndividualResearchRequest(BaseModel)`: `name: str = Field(min_length=2, max_length=120)`, optional str fields `company, linkedin_url, x_url, github_url, website, location` (≤ 300) and `context` (≤ 1000); blank-after-strip name → 422.
  - `POST /api/individual/research` → `{"job_id": ...}` (202-style 200)
  - `GET /api/individual/research/{job_id}` → job dict; 400 bad id, 404 unknown/expired
  - `POST /api/individual/research/{job_id}/select` body `{candidate_id}` → job; 409 unless `identity_resolution` is `needs_input` and not running; 404 unknown candidate
  - `POST /api/individual/research/{job_id}/retry` → job; 409 if running or nothing to retry
  - Worker: sets `job["running"]=True`, runs under the job lock, clears `running` in `finally`; company research acquires the existing `company_research_slots`.

- [ ] **Step 1: Write failing tests** (fixture monkeypatches `server.individual_jobs` with a fresh store, `server.make_individual_pipeline` with fakes from Task 4, and `server._spawn` to call synchronously)

```python
def test_start_and_poll_completed(client): ...  # POST -> job_id; GET -> status "completed", 6 stages
def test_name_validation(client):
    assert client.post("/api/individual/research", json={"name": " "}).status_code == 422
    assert client.post("/api/individual/research", json={}).status_code == 422
def test_bad_and_unknown_job_ids(client):
    assert client.get("/api/individual/research/..%2Fx").status_code in (400, 404)
    assert client.get("/api/individual/research/ind_0000000000000000").status_code == 404
def test_select_flow_and_double_select_conflict(client_ambiguous):
    jid = start(); cid = get(jid)["candidates"][0]["candidate_id"]
    assert post_select(jid, cid).status_code == 200
    assert post_select(jid, cid).status_code == 409
def test_select_unknown_candidate_404(client_ambiguous): ...
def test_retry_nothing_to_retry_409(client): ...
def test_individual_endpoints_require_auth_in_production(client, monkeypatch):
    monkeypatch.setattr(server, "APP_ENV", "production"); monkeypatch.setattr(server, "API_SECRET_KEY", "k")
    assert client.post("/api/individual/research", json={"name": "Jane Doe"}).status_code == 401
```

- [ ] **Step 2: Run** `pytest tests/test_individual_api.py -v` — Expected: FAIL (404 routes).
- [ ] **Step 3: Implement the section in `server.py`.**
- [ ] **Step 4: Run** `pytest tests/ -v -k "not tor_runtime"` — Expected: all PASS (existing suites included).
- [ ] **Step 5: Commit** `feat(individual): research job API endpoints`

---

### Task 6: Frontend — types, API client, helpers, sidebar, page

**Files:**
- Modify: `src/types/index.ts`, `src/lib/api.ts`, `src/components/Sidebar.tsx`, `package.json` (add test file to `test` script)
- Create: `src/lib/individual.mjs`, `src/app/individual/page.tsx`, `src/components/IndividualResults.tsx`
- Test: `tests/individual_research.test.mjs`

**Interfaces:**
- Consumes: Task 5 endpoints and job shape.
- Produces:
  - Types: `IndividualStageName`, `IndividualStage`, `IndividualCandidate`, `IndividualJob`, `IndividualResearchInput`.
  - `api.startIndividualResearch(input) -> Promise<{job_id: string}>`, `api.getIndividualResearch(jobId) -> Promise<IndividualJob>`, `api.selectIndividualCandidate(jobId, candidateId)`, `api.retryIndividualResearch(jobId)`.
  - `individual.mjs`: `STAGE_LABELS` (stage → label, in `STAGES` order: "Public identity discovery", "Identity resolution", "Current company discovery", "Company & product research", "Professional background", "SealAPI relevance & priority"), `shouldPollJob(job) -> boolean` (true iff `job.running` or `job.status === "running"`), `confidenceLabel(x) -> "High"|"Medium"|"Low"` (≥0.75, ≥0.35), `relevanceMeta(r) -> {label, variant}` (relevant→"Relevant"/success, needs_validation→"Needs validation"/warning, not_relevant→"Not relevant"/neutral, insufficient_evidence→"Insufficient evidence"/info), `buildStartPayload(form) -> object` (trims, drops empty optional fields, keeps `name`), `downloadFilename(job) -> string` (`individual_<slug-of-name>_<YYYY-MM-DD>.json`).

- [ ] **Step 1: Write failing node tests**

```js
it("sidebar places Individual Research between Dashboard and Prioritized Leads", () => {
  const src = readFileSync(new URL("../src/components/Sidebar.tsx", import.meta.url), "utf8");
  const i = (s) => src.indexOf(`name: "${s}"`);
  assert.ok(i("Dashboard") < i("Individual Research") && i("Individual Research") < i("Prioritized Leads"));
  assert.match(src, /href: "\/individual"/);
});
it("buildStartPayload keeps only filled fields", () => {
  assert.deepEqual(buildStartPayload({ name: " Jane Doe ", company: "", location: " Berlin " }), { name: "Jane Doe", location: "Berlin" });
});
it("confidence and relevance labels", () => {
  assert.equal(confidenceLabel(0.8), "High"); assert.equal(confidenceLabel(0.5), "Medium"); assert.equal(confidenceLabel(0.1), "Low");
  assert.deepEqual(relevanceMeta("needs_validation"), { label: "Needs validation", variant: "warning" });
});
it("polls only while running", () => {
  assert.equal(shouldPollJob({ running: true, status: "running" }), true);
  assert.equal(shouldPollJob({ running: false, status: "needs_input" }), false);
});
it("download filename", () => {
  assert.equal(downloadFilename({ input: { name: "Jane O'Doe" }, created_at: "2026-11-07T10:00:00Z" }), "individual_jane_o_doe_2026-11-07.json");
});
it("results page renders every required section", () => {
  const src = readFileSync(new URL("../src/components/IndividualResults.tsx", import.meta.url), "utf8");
  for (const t of ["Identity & Profile", "Professional Background", "Company Intelligence", "Products",
                   "AI Usage & SealAPI Relevance", "Sources & Evidence"]) assert.ok(src.includes(t), t);
});
```

- [ ] **Step 2: Run** `node --test tests/individual_research.test.mjs` — Expected: FAIL.
- [ ] **Step 3: Implement.** Sidebar entry `{ name: "Individual Research", href: "/individual", icon: UserSearch, badge: "NEW" }`. Page: form (name required; "Add hints" toggle reveals the optional fields), Start (disabled while running or name < 2 chars) and Clear (resets form and job), stage list with icons per status, error banner, candidate cards (avatar `<img>` only for `https:` URLs, `referrerPolicy="no-referrer"`; Select button) when `identity_resolution` is `needs_input` with candidates, low-confidence message when it is `needs_input` with none, Retry button when `status === "partial"` or `"failed"`, `IndividualResults` once `person` exists, Download JSON via `Blob`. Poll every 1500 ms while `shouldPollJob`. Identity confidence badge and relevance badge shown separately; `PriorityBadge` for priority. All scraped strings rendered as text.
- [ ] **Step 4: Run** `npm test && npm run typecheck && npm run build` — Expected: all pass, build succeeds.
- [ ] **Step 5: Commit** `feat(ui): Individual Research page`

---

### Task 7: Docs and end-to-end verification

**Files:**
- Create: `docs/INDIVIDUAL_RESEARCH.md` (where it lives, pipeline, thresholds, API, no-storage note, limits)
- Modify: `README.md` (one feature bullet linking the doc)

- [ ] **Step 1:** Write the docs.
- [ ] **Step 2: Run** `pytest tests/ -v -k "not tor_runtime"` and `npm test` — Expected: all PASS.
- [ ] **Step 3: Live smoke.** Start backend and frontend; open `/individual`, run a name-only search for a well-known public technologist; confirm candidates or auto-selection, company discovery, verdict and sources render; confirm nothing new under `data/`. Record what worked and what DuckDuckGo throttling did.
- [ ] **Step 4: Commit** `docs: Individual Research feature`
