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

1. **discovery**: builds up to 5 queries (deduplicated), in this priority order: `"Name"`, `"Name" linkedin`,
   `"Name" (CEO OR CTO OR founder OR engineer)`, then `"Name" "<company>"`, `"Name" <location>` and
   `"Name" <first 3 context keywords>` when those hints are given, then `"Name" github` and
   `"Name" twitter OR x.com`; only the first 5 run (so with company, location and context all given, the context
   query is dropped and the context hint still counts in scoring). Each runs through DuckDuckGo Lite directly. Then
   GitHub and the supplied website are consulted (see sources below).
2. **identity_resolution**: turns each hit into an observation (name checked with `names_compatible`, title,
   company, location, profile URL, avatar, snippet), merges observations into candidates, scores them and
   decides whether to auto-select, ask the user to select, or ask for a hint.
3. **company_discovery**: finds and verifies the person's company website.
4. **company_research**: runs the existing `CompanyResearcher` on the verified domain.
5. **professional_profile**: role category, decision authority, GitHub languages and AI-related repos.
6. **verdict**: SealAPI relevance and P0/P1/P2 priority. It always runs, including when the company is Unknown.

### Discovery sources

- **DuckDuckGo**, searched the same way as bulk lead research. The request's `use_browser` and `use_tor`
  (both default `true`, shown on the form as "Stealth Chromium" and "Enable Tor Routing", kept per job in
  `search_options` and reused for select and retry) build `ScraplingScraper(use_browser=..., use_tor=...)`:
  the stealth Chromium browser on `html.duckduckgo.com` routed through Tor when it is reachable, falling back to
  DuckDuckGo Lite over direct HTTP when that finds nothing. Only searches use Tor; company and personal pages are
  always fetched directly through the SSRF-safe, IP-pinned fetcher. Result titles are parsed (LinkedIn titles as `Name - Title - Company | LinkedIn`; GitHub titles) and
  snippets are pattern-matched for `<Title> at <Company>`. DuckDuckGo redirect links (`//duckduckgo.com/l/?uddg=`)
  are decoded to the real destination first. A hit is dropped unless its name is compatible with the searched
  name. The scraper swallows request errors and bot challenges (for example HTTP 202) and returns no results, so
  failures cannot be told apart per query; when every query returns nothing, the job records the error and
  limitation "Web search returned no results for any query (DuckDuckGo may be blocking or throttling automated
  requests); results come from GitHub and supplied URLs only."
- **GitHub public REST API**, unauthenticated, no token: `GET /search/users` (top 3, `"<name>" in:name`),
  `GET /users/<login>` for each of those 3 hits, and `GET /users/<login>/repos` (10 most recently pushed) for the
  selected candidate. A supplied GitHub URL is looked up directly. Searched (not supplied) users whose profile name
  is not compatible with the input name are discarded. The binding limit is GitHub's unauthenticated core API
  quota of 60 requests per hour per IP address (a job uses at most about 6). When GitHub answers 403/429 with
  `X-RateLimit-Remaining: 0`, the job records "GitHub API rate limit reached; resets at HH:MM UTC" and makes no
  further GitHub calls in that run. Other HTTP errors are recorded as job errors.
  - The user's GitHub `company` field is parsed: a URL or domain (`https://vercel.com`, `vercel.com`) gives the
    company name from the domain label (`Vercel`) and that domain becomes the first company-domain candidate
    (`domain_source` `github_company`); several orgs (`@vercel @nextjs`) give the first (`vercel`). A role in the
    bio (CEO, CTO, CISO, founder/co-founder, VP ..., Head of ..., Director ..., engineer, Chief ... Officer)
    becomes the title (`@vercel CEO` gives `CEO`).
- **Supplied personal website**: fetched with the SSRF-safe `fetch_url` (not social domains). It becomes an
  observation only if the page mentions the full name.
- **LinkedIn and X**: supplied URLs are identifiers only and are **never fetched**; LinkedIn data comes only from
  search-result titles and snippets.

### Identity thresholds

Observations merge into one candidate when they share a LinkedIn slug or GitHub login, or the same normalized
company (a merge by company is refused if it would join two different LinkedIn/GitHub handles). Different
companies stay separate candidates. Confidence (0 to 1) adds: name match (+0.30 strong, +0.15 weak), job title
(+0.10), company (+0.15), each corroborating distinct source (+0.12, up to 3), matching company hint (+0.20),
matching location hint (+0.10), and at least one context keyword (3+ characters, not a stopword) appearing in
the candidate's title, company or description (+0.10). A supplied LinkedIn or GitHub URL that matches the candidate sets confidence to at
least 0.95 and ranks that candidate first.

| Outcome | Rule |
| --- | --- |
| Auto-select | Top candidate has a supplied-URL match, or confidence >= 0.75 and (no runner-up or runner-up at least 0.25 lower) |
| Needs input (select) | Otherwise, among candidates with confidence >= 0.35 (the candidate floor) |
| Needs input (low confidence) | No candidate >= 0.35, or no profiles found; asks the user to add a company, location or profile URL. No identity is invented |

### Company discovery

The company name comes from the selected candidate, else the supplied company hint. Candidate domains are tried
in this order, each at most once, at most 6 homepage fetches in total:

1. Domain from the GitHub `company` field (`github_company`)
2. GitHub `blog` field (`github_blog`)
3. Supplied website, then websites from website observations, then the candidate's website (`website`)
4. Non-social result URLs whose domain is named after the company (`search_result`)
5. Results of a `"<Company>" official site` search, first 10 (`search`)

A domain is accepted only if **both** hold: the company's most distinctive name token (the longest normalized
token of 3+ characters) appears in the domain's registrable label (`vercel` in `vercel.com`, `blog.vercel.com` or
`vercel.app`; not in `janedoe.dev` or `techcrunch.com`), and its homepage passes `is_company_corroborated`. This
applies to every source, so a personal blog or news article that mentions the company is never taken as the
company's website. If the company has no distinctive token, corroboration alone decides. A `github_blog` or
`website` homepage that is not accepted still has its links harvested: links to domains named after the company
are tried next (`website_link`), so a personal site linking to the employer finds it. Domains that are not named
after the company are not fetched otherwise, and are listed in the Unknown note. Social, free-mail and LinkedIn/X
domains are never used. If nothing is corroborated the company is **Unknown**: `company_research` is
`skipped`, and the verdict is "Insufficient evidence".

### Company research (reuse)

`CompanyResearcher` from the company-intel engine runs unchanged against a `MemoryCompanyStore` (dict-based, same
methods, no file IO), so no company record or page cache is written under `DATA_DIR`. It runs inside the existing
`company_research_slots` semaphore. The job keeps the record without raw page text and links; its AI findings
(`ai`, `ai_provider` categories), providers and AI products populate `ai_usage`. Page text is untrusted and only
pattern-matched.

### Live products and AI usage detail

Built from the company pages already fetched (full text stays in the job's in-memory store only), so this adds no
company-site requests. Code: `ai_usage.py` and `live_products.py`.

- **Live products** (`live_products.live` / `.excluded`): every product found by company research, plus AI pages
  that are not already a product. A product counts as live only when its page loaded on the company domain and
  offers a way to use or buy it now: sign-up, get started, free trial, pricing, buy, download, install, demo or
  "talk to sales", or an app-store link. Site-wide "Log in" / "Subscribe" count only when nothing stronger is found.
  "Beta", "early access" or "public preview" with such a route gives **Live (beta)**. "Coming soon", "join the
  waitlist", "private beta" and similar give **Not live**; "discontinued", "deprecated", "sunset", "end of life"
  in a sentence naming the product (or "this product/service") give **Discontinued**. A loaded page with none of
  these is **Could not confirm live**. Only live and beta products are shown in the main list; the quoted text
  that decided each status is kept as `signal`.
- **Person's projects** (`person.projects`): the person's own GitHub repos (forks and archived repos excluded),
  newest first. A repo is live only when its homepage loads; repos without one are "code only". With a supplied
  personal website, its projects page (`/projects`, `/work`, `/portfolio`, `/apps`...) is read and external
  project sites on it are listed only if they load. All of this is capped at 6 requests per job (at most 3 repo
  homepage checks), through the same SSRF-safe fetcher.
- **AI use cases** (`ai_usage.use_cases`, `ai_usage.summary`): every AI-related sentence on the fetched pages
  (4 per page, 20 total; AI and product pages first), each tagged with:
  - type: generative, agentic, predictive / analytical ML, retrieval / search (a sentence can have several; none
    matched gives "general");
  - purpose: customer support, coding / developer tools, content & marketing, search & knowledge, analytics &
    insights, security & fraud, sales & CRM, workflow automation, document processing, or other;
  - stage: GA, beta / preview, or unspecified; context: in their product, hiring / internal (careers pages), or
    company page; and the live product whose page it came from, if any.
  The summary counts types and purposes and gives the main type and overall stage. Tags are keyword rules, shown
  with the quoted sentence so they can be checked.

## Analysis rules

- **Role** (inferred from title text only): Founder / Co-founder, CTO, CISO, CEO (authority executive); chief
  AI/ML/data officer (executive AI/ML Leader); VP/Head/Director of Engineering (senior leader); Head/Director/VP/
  Lead of AI (senior leader AI/ML Leader); Security Architect and AI Engineer (practitioner); Engineering Manager
  (senior leader); everything else is Other with unknown authority. President (not Vice President), COO, CPO, CFO,
  CMO, CRO, any Chief ... Officer, Managing Director and Owner (not Product Owner) always get executive authority;
  their category follows the rules above, else Other. Profile facts are labelled `verified` (seen in
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
`candidates`, `selected_candidate_id`, `identity`, `person` (including `projects`), `company`, `ai_usage`
(including `use_cases` and `summary`), `live_products`, `sealapi`, `priority`, `sources`, `errors` and `limitations`.

## Jobs and concurrency

- Jobs are held in an in-memory store: at most 50 (the oldest is dropped when full) and a 1-hour lifetime.
  Job ids are `ind_<hex>`.
- Each start, select or retry spawns one daemon worker thread for that job. A server-owned active set rejects
  a second start, select or retry for a job already running (409). A fresh pipeline and GitHub source are created
  per run.
- Reads take snapshots under the job lock, so polling stays responsive while a worker runs. The page polls every
  1.5 seconds; if a poll returns 404 (job expired or the server restarted) it stops polling and says the job no
  longer exists.
- Candidate selection resumes at company_discovery. Retry of `identity_resolution` restarts from discovery because
  observations are not stored.

## Storage

None. Nothing is written to `data/` or `DATA_DIR`; jobs, the company record and its page cache exist only in
process memory and are lost on restart or after expiry. The "Download JSON" button builds the file in the browser
from the job already on screen; "Copy JSON" copies the same JSON to the clipboard.

## Configuration

No new environment variables and no API keys (GitHub is queried unauthenticated). Company research uses the
existing `COMPANY_RESEARCH_*` settings (see `docs/COMPANY_INTELLIGENCE.md`) and shares its concurrency slots.

## Known limitations

- DuckDuckGo returns about 5-6 results per query and may still throttle or serve a bot challenge, especially
  with the stealth browser or Tor turned off, or when Tor is offline (the form shows Tor's status and a
  "Start Tor" button). The stealth browser makes each search slower (several seconds per query). The scraper turns
  those into empty results, so they are not recorded per query; only when every query comes back empty does the
  job record a "Web search returned no results" error and limitation.
- LinkedIn data comes only from search-result titles and snippets; LinkedIn and X pages are never fetched.
- JavaScript-rendered company sites yield thin findings (no browser fetching).
- GitHub is queried without a token: 60 requests per hour per IP address. Once exhausted, the job records
  "GitHub API rate limit reached; resets at HH:MM UTC" and skips GitHub for the rest of that run.
- Extraction is pattern-based: titles, companies and findings can be imperfectly parsed. Common names produce
  multiple candidates, and a person with no public footprint yields low confidence rather than a guess.
- "Live" means the page loaded and offered a sign-up or purchase route when checked; it does not prove usage.
  Sites that block bots or render their buttons with JavaScript can be marked "Could not confirm live" or
  "Site down". Company pages keep only links on the company's own domain, so app-store buttons are usually
  detected from page text.
- AI tagging is keyword-based and can miss unusual wording; each tag is shown with its sentence.
- Job state is in-process: a restart loses all jobs, and results cannot be reopened after an hour.
- No pitch strategy, outreach drafts, PDF, or "add to Prioritized Leads" in this feature.
