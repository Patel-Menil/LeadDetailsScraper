# Individual Research — Design

Date: 2026-11-07 · Status: approved in chat, pending spec review

## Goal

Given only a person's full name, SealAPI discovers who they are, finds their current company, researches that
company's offering and AI usage, and states whether SealAPI is relevant, with evidence. Optional hints narrow the
search. Company name is never required.

## Decisions (from the user)

- **Search source:** the existing DuckDuckGo path only (no new API keys), plus GitHub's free public REST API.
  Searches go to DuckDuckGo Lite directly (`use_browser=False`, `use_tor=False`): no stealth browser, no Tor.
- **Output scope:** identity, company data, the company's AI usage, and a SealAPI relevance verdict. No pitch
  strategy, LinkedIn sequence, PDF, or "add to Prioritized Leads". Existing company-intel discovery questions are kept.
- **Synthesis:** deterministic. No LLM.
- **Storage:** none. Jobs live in process memory and expire; nothing is written to `DATA_DIR`. JSON download is
  generated in the browser.
- **Claims:** `sealapi_capabilities.py` is unchanged; relevance uses the existing fit classification and registry.

## Inputs

`name` (required, 2–120 chars). Optional: `company`, `linkedin_url`, `x_url`, `github_url`, `website`,
`location`, `context` (free text, used only as extra search terms and matching tokens).

## Pipeline stages

Each stage records `status` (`pending|running|done|skipped|failed|needs_input`), a message, and timestamps.

1. **discovery** — Build 3–5 queries: `"Name"`, `"Name" linkedin`, `"Name" (CEO OR CTO OR founder OR engineer)`,
   plus `"Name" "<company>"` / `"Name" <location>` / `"Name" <context keywords>` when given. Run each through
   `ScraplingScraper.search_person(custom_query=...)`. Call GitHub `GET /search/users?q=<name> in:name` (top 5) and
   `GET /users/<login>` for each hit; a supplied GitHub URL is looked up directly. A supplied personal website is
   fetched with the SSRF-safe `fetch_url`. LinkedIn and X URLs are **never fetched**; they are identifiers only.
2. **identity_resolution** — Turn each hit into an observation: name (checked with `names_compatible`), title,
   company, location, profile URL, avatar, snippet. Parsers: LinkedIn result titles
   (`Name - Title - Company | LinkedIn`), snippets (`<Title> at <Company>`), GitHub fields. Observations merge into a
   candidate only when they share a LinkedIn slug, GitHub login, or normalized company; different companies stay
   separate candidates. Confidence (0–1): exact name match, count of independent corroborating sources, title+company
   present, agreement with supplied hints (a matching supplied URL is strong evidence).
   - top ≥ 0.75 and (no runner-up or runner-up ≤ top − 0.25), or a supplied-URL match → auto-select
   - any candidate ≥ 0.35 → `needs_input`: user selects a candidate
   - none ≥ 0.35 → `needs_input` with "low confidence; add a hint" (no identity invented)
3. **company_discovery** — From the selected candidate: company name, then domain from (in order) the GitHub `blog`
   field, supplied website / personal site links, non-social result URLs whose domain contains the company's
   distinctive token, then a `"<Company>" official site` search. A domain is accepted only if its homepage passes
   `is_company_corroborated`. Otherwise company is **Unknown** and later company stages are `skipped`.
4. **company_research** — `CompanyResearcher` unchanged, backed by a new `MemoryCompanyStore` (same interface as
   `CompanyStore`, dict-based). Produces overview, products, findings (including `ai` / `ai_provider`), gaps,
   opportunities, fit, discovery questions.
5. **professional_profile** — Role category from title (Founder/Co-founder, CEO, CTO, CISO, VP Engineering, AI/ML
   Leader, Security Architect, AI Engineer, Engineering Manager, Other), decision authority (executive / senior
   leader / practitioner / unknown), GitHub public repos' languages and AI-related topics. Each item is labelled
   `verified` (seen in a source, with source id) or `inferred` (derived from title text).
6. **verdict** — SealAPI relevance from `company_fit.classification`: strong → Relevant, validation_required →
   Needs validation, weak / not_suitable → Not relevant, insufficient_evidence or unknown company → Insufficient
   evidence. Priority: P0 = Relevant/Needs validation + executive or security/AI leader; P1 = Relevant/Needs
   validation otherwise, or Not relevant + executive; P2 = everything else. Identity confidence is reported separately.

## Result shape (JSON)

`{job_id, status, input, stages[], candidates[], selected_candidate_id, person{...}, company{...} | null,
ai_usage{ai_findings[], providers[], ai_products[]}, sealapi{relevance, fit_label, reasoning, opportunities[],
discovery_questions[], scope_note}, priority{level, reasons[]}, sources[], limitations[]}`

## API (all behind `verify_api_key`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/individual/research` | Start a job, returns `{job_id}` |
| GET | `/api/individual/research/{job_id}` | Job state and partial result |
| POST | `/api/individual/research/{job_id}/select` | `{candidate_id}`; continues from company_discovery |
| POST | `/api/individual/research/{job_id}/retry` | Re-runs the first failed/skipped stage onward |

Jobs: in-memory dict, max 50, evicted after 1 hour; one worker thread per job; `job_id` is `ind_<hex>`, validated.
Company research reuses the existing `company_research_slots` semaphore.

## UI

`/individual`, sidebar item "Individual Research" between Dashboard and Prioritized Leads. Form (name required,
optional hints collapsed under "Add hints"), Start / Clear, stage list with status icons (polls every 1.5 s while
running), candidate cards (avatar, title, company, location, profile link, snippet, confidence, Select), and result
sections: Identity & Profile, Professional Background, Company Intelligence, Products, AI Usage & SealAPI Relevance,
Sources & Evidence. Download JSON (client-side). Reuses `Card`, `Badge`, `Button`, existing dark palette.

## Error handling

Search or fetch failures are recorded per stage and never crash the job. Partial results are always returned.
Scraped text is untrusted: pattern-matched only, length-limited, rendered as text (no HTML).

## Testing

Pytest with injected fake search / GitHub / fetch providers (no network): title/snippet parsers, candidate merging,
confidence and auto-select vs selection vs low confidence, company-domain discovery and Unknown path, verdict and
priority mapping, job store eviction, endpoints (start/poll/select/retry, auth, invalid ids). Existing pytest and
Node suites must still pass; `npm run typecheck` and `npm run build` must succeed. One live smoke run with a real name.

## Known limits

DuckDuckGo Lite returns about 5 results per query and may throttle. LinkedIn data comes only from search snippets.
JavaScript-rendered sites produce thin company findings. GitHub unauthenticated search allows 10 requests/minute.
