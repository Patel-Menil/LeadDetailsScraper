# Individual Research (Individual Research page)

Given only a person's full name, discovers who they are from public sources, finds their current company,
researches that company's offering and AI usage, and states whether SealAPI is relevant, with evidence. Optional
hints narrow the search; a company name is never required. Synthesis is deterministic (no LLM). Nothing is
persisted: jobs live in process memory only. Lead profiles, scores, CSVs and company intelligence storage are
unchanged.

## Where it lives

| Piece | File |
| --- | --- |
| Discovery, parsers, candidate merging, confidence scoring | `src/lead_research/individual_discovery.py` |
| Company discovery, role/profile, verdict, priority, in-memory stores, pipeline | `src/lead_research/individual_research.py` |
| API endpoints, job admission and workers | `src/lead_research/server.py` (section "Individual research") |
| Page (form, stage list, candidates, polling, JSON download) | `src/app/individual/page.tsx` |
| Page helpers | `src/lib/individual.mjs` |
| Sidebar entry "Individual Research" | `src/components/Sidebar.tsx` |
| Company research engine (reused) | `src/lead_research/company_intel.py` (see `docs/COMPANY_INTELLIGENCE.md`) |
| Design | `docs/superpowers/specs/2026-11-07-individual-research-design.md` |

## How research works

A job runs six stages in order. Each stage has a status (`pending`, `running`, `done`, `skipped`, `failed`,
`needs_input`), a message and start/finish timestamps. A failure in one stage is recorded and never crashes the
job; partial results are always returned.

1. **discovery**: builds up to 5 queries (deduplicated): `"Name"`, `"Name" linkedin`, `"Name" "<company>"` and
   `"Name" <location>` when those hints are given, `"Name" github`, `"Name" twitter OR x.com`. Each runs through
   DuckDuckGo Lite directly. Then GitHub and the supplied website are consulted (see sources below).
2. **identity_resolution**: turns each hit into an observation (name checked with `names_compatible`, title,
   company, location, profile URL, avatar, snippet), merges observations into candidates, scores them and
   decides whether to auto-select, ask the user to select, or ask for a hint.
3. **company_discovery**: finds and verifies the person's company website.
4. **company_research**: runs the existing `CompanyResearcher` on the verified domain.
5. **professional_profile**: role category, decision authority, GitHub languages and AI-related repos.
6. **verdict**: SealAPI relevance and P0/P1/P2 priority. It always runs, including when the company is Unknown.

### Discovery sources

- **DuckDuckGo Lite**, direct HTTP (`ScraplingScraper(use_browser=False, use_tor=False)`): no stealth browser,
  no Tor. Result titles are parsed (LinkedIn titles as `Name - Title - Company | LinkedIn`; GitHub titles) and
  snippets are pattern-matched for `<Title> at <Company>`. A hit is dropped unless its name is compatible with
  the searched name.
- **GitHub public REST API**, unauthenticated, no token: `GET /search/users` (top 5, `"<name>" in:name`),
  `GET /users/<login>` for each hit, and `GET /users/<login>/repos` (10 most recently pushed) for the selected
  candidate. A supplied GitHub URL is looked up directly. Searched (not supplied) users whose profile name is not
  compatible with the input name are discarded. GitHub allows 10 search requests per minute unauthenticated; the
  code does not throttle, so errors such as HTTP 403 are recorded as job errors.
- **Supplied personal website**: fetched with the SSRF-safe `fetch_url` (not social domains). It becomes an
  observation only if the page mentions the full name.
- **LinkedIn and X**: supplied URLs are identifiers only and are **never fetched**; LinkedIn data comes only from
  search-result titles and snippets.

### Identity thresholds

Observations merge into one candidate when they share a LinkedIn slug or GitHub login, or the same normalized
company (a merge by company is refused if it would join two different LinkedIn/GitHub handles). Different
companies stay separate candidates. Confidence (0 to 1) adds: name match (+0.30 strong, +0.15 weak), job title
(+0.10), company (+0.15), each corroborating distinct source (+0.12, up to 3), matching company hint (+0.20),
matching location hint (+0.10). A supplied LinkedIn or GitHub URL that matches the candidate sets confidence to at
least 0.95 and ranks that candidate first.

| Outcome | Rule |
| --- | --- |
| Auto-select | Top candidate has a supplied-URL match, or confidence >= 0.75 and (no runner-up or runner-up at least 0.25 lower) |
| Needs input (select) | Otherwise, among candidates with confidence >= 0.35 (the candidate floor) |
| Needs input (low confidence) | No candidate >= 0.35, or no profiles found; asks the user to add a company, location or profile URL. No identity is invented |

### Company discovery

The company name comes from the selected candidate, else the supplied company hint. Candidate domains are tried
in this order, each at most once, at most 6 homepage fetches in total:

1. GitHub `blog` field
2. Supplied website, then websites from website observations, then the candidate's website
3. Non-social result URLs whose domain contains the company's most distinctive name token
4. Results of a `"<Company>" official site` search (first 10)

If the supplied website does not corroborate the company, its links to domains containing the company token are
tried as well. A domain is accepted only if its homepage passes `is_company_corroborated`. Social, free-mail and
LinkedIn/X domains are never used. If nothing is corroborated the company is **Unknown**: `company_research` is
`skipped`, and the verdict is "Insufficient evidence".

### Company research (reuse)

`CompanyResearcher` from the company-intel engine runs unchanged against a `MemoryCompanyStore` (dict-based, same
methods, no file IO), so no company record or page cache is written under `DATA_DIR`. It runs inside the existing
`company_research_slots` semaphore. The job keeps the record without raw page text and links; its AI findings
(`ai`, `ai_provider` categories), providers and AI products populate `ai_usage`. Page text is untrusted and only
pattern-matched.

## Analysis rules

- **Role** (inferred from title text only): Founder / Co-founder, CTO, CISO, CEO (authority executive); chief
  AI/ML/data officer (executive AI/ML Leader); VP/Head/Director of Engineering (senior leader); Head/Director/VP/
  Lead of AI (senior leader AI/ML Leader); Security Architect and AI Engineer (practitioner); Engineering Manager
  (senior leader); everything else is Other with unknown authority. Profile facts are labelled `verified` (seen in
  a GitHub observation) or `inferred`, with source ids.
- **Relevance** from the company-intel fit classification: strong = Relevant; validation_required = Needs
  validation; weak and not_suitable = Not relevant; insufficient_evidence, unknown company or no fit = Insufficient
  evidence. Opportunities and discovery questions (up to 5 each) come from the company record. The capability
  registry (`sealapi_capabilities.py`) is unchanged.
- **Priority**:
  - P0: Relevant or Needs validation, and an executive role or one of CISO, Security Architect, AI/ML Leader
  - P1: Relevant or Needs validation otherwise; or Not relevant with an executive role
  - P2: everything else
- Identity confidence is reported separately from relevance and priority.

## API

All endpoints use the existing `verify_api_key` dependency (session cookie via the Next.js proxy, or `X-API-Key`).

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/individual/research` | Start a job; body has `name` (2-120 chars, required) and optional `company`, `linkedin_url`, `x_url`, `github_url`, `website`, `location`, `context`; returns `{job_id}` |
| GET | `/api/individual/research/{job_id}` | Snapshot of job state and partial result |
| POST | `/api/individual/research/{job_id}/select` | `{candidate_id}`; continues from company_discovery; returns a snapshot |
| POST | `/api/individual/research/{job_id}/retry` | Re-runs from the first failed or skipped stage; returns a snapshot |

Status codes: 400 invalid job id (must match `ind_<16 hex>`); 404 job not found or expired, or unknown
`candidate_id`; 409 job already running, job not waiting for a selection (select), or nothing to retry (retry); 422
request validation (for example name too short or a field too long).

The result has `job_id`, `status` (`running`, `needs_input`, `partial`, `completed`, `failed`), `input`, `stages`,
`candidates`, `selected_candidate_id`, `identity`, `person`, `company`, `ai_usage`, `sealapi`, `priority`,
`sources`, `errors` and `limitations`.

## Jobs and concurrency

- Jobs are held in an in-memory store: at most 50 (the oldest is dropped when full) and a 1-hour lifetime.
  Job ids are `ind_<hex>`.
- Each start, select or retry spawns one daemon worker thread for that job. A server-owned active set rejects
  a second start, select or retry for a job already running (409). A fresh pipeline and GitHub source are created
  per run.
- Reads take snapshots under the job lock, so polling stays responsive while a worker runs. The page polls every
  1.5 seconds.
- Candidate selection resumes at company_discovery. Retry of `identity_resolution` restarts from discovery because
  observations are not stored.

## Storage

None. Nothing is written to `data/` or `DATA_DIR`; jobs, the company record and its page cache exist only in
process memory and are lost on restart or after expiry. The "Download JSON" button builds the file in the browser
from the job already on screen.

## Configuration

No new environment variables and no API keys (GitHub is queried unauthenticated). Company research uses the
existing `COMPANY_RESEARCH_*` settings (see `docs/COMPANY_INTELLIGENCE.md`) and shares its concurrency slots.

## Known limitations

- DuckDuckGo Lite returns about 5 results per query and may throttle; discovery then yields fewer observations
  (search errors are recorded per query).
- LinkedIn data comes only from search-result titles and snippets; LinkedIn and X pages are never fetched.
- JavaScript-rendered company sites yield thin findings (no browser fetching).
- GitHub unauthenticated search allows 10 requests per minute; rate-limited calls are recorded as errors.
- Extraction is pattern-based: titles, companies and findings can be imperfectly parsed. Common names produce
  multiple candidates, and a person with no public footprint yields low confidence rather than a guess.
- Job state is in-process: a restart loses all jobs, and results cannot be reopened after an hour.
- No pitch strategy, outreach drafts, PDF, or "add to Prioritized Leads" in this feature.
