# LeadDetailsScraper — Complete Fix & Development Plan

## Project Objective

You are working on the existing repository:

`https://github.com/Patel-Menil/LeadDetailsScraper/`

Your task is to audit, fix, and improve the current lead-research and prioritization pipeline so it produces **accurate, verifiable, outreach-ready B2B leads** rather than simply scraping search-result snippets and generating generic lead profiles.

The end goal is to help SealAPI identify the right person in a company, understand why that person may care about SealAPI, find appropriate professional contact channels, establish a credible conversation opener, and prepare a personalized first-contact message.

**Do not only write a development plan. Inspect the existing repository, implement the fixes phase by phase, run tests, and deliver working code.**

Preserve existing functionality unless there is a clear technical reason to change it. Do not rewrite the application from scratch.

---

# 1. Start With a Repository Audit

Before modifying code:

1. Inspect the active Git branch, working tree, recent commits, project structure, environment configuration, Docker setup, and test suite.
2. Read the existing scraper, research, scoring, pipeline, schema, importer, exporter, and frontend/backend integration code.
3. Identify which features already exist and which are missing.
4. Record the current behavior of the scraping pipeline before applying changes.
5. Never overwrite unrelated user changes or commit secrets.
6. Run the existing tests and record baseline failures.

Investigate these existing areas, adapting paths to the actual repository:

- `src/lead_research/scraper.py`
- `src/lead_research/research.py`
- `src/lead_research/schemas.py`
- `src/lead_research/scoring.py`
- `src/lead_research/pipeline.py`
- `src/lead_research/importer.py`
- `src/lead_research/exporter.py`
- Existing API, frontend, batch processing, cache, and tests

The existing implementation reportedly uses Scrapling, DuckDuckGo search results, optional browser fetching and Tor configuration, concurrent research, resume caching, lead scoring, JSON/CSV exports, and mirrored output folders. Verify these details in the current code rather than assuming they are unchanged.

The current dataset reportedly contains 144 leads. Generate a baseline report from the actual input files, including source coverage, missing contact fields, duplicate identities, suspicious search results, incomplete profiles, and current scoring distribution.

**Deliverable:** `docs/lead_research_audit.md`

---

# 2. Define Exactly What Information We Need About Each Lead

Do not collect information simply because it is available. Collect information that serves a clear purpose: identify the correct professional, select an appropriate contact channel, establish relevance, and start a credible conversation.

Design the output around the following fields.

## 2.1 Essential Contact Information

| Field | Purpose | Required behavior |
|---|---|---|
| `lead_id` | Stable identifier for the lead | Generate or preserve a stable identifier |
| `first_name` | Natural greeting | Store only when supported by evidence |
| `full_name` | Identify the correct person | Never expand initials by guessing |
| `current_title` | Establish seniority and responsibilities | Verify against a suitable source |
| `company_name` | Identify the intended account | Preserve the input value and record verified alternatives |
| `company_domain` | Locate official company information | Normalize and validate the domain |
| `professional_email` | Enable direct outreach | Preserve the supplied address; validate format and provenance |
| `email_type` | Distinguish work, generic, and unknown addresses | Use values such as `work`, `generic`, `unknown` |
| `email_verification_status` | Represent verification quality | Do not call syntax validation proof of deliverability |
| `linkedin_url` | Professional context and contact discovery | Store when available from a lawful public or authorized source |
| `company_website` | Verify the business and discover its products | Prefer the official domain |
| `contact_channel_status` | Show whether a usable channel exists | Separate `available`, `missing`, `unverified`, and `invalid` |

A verified professional email and a valid LinkedIn URL are useful but not mandatory for every lead. Missing data must remain missing; it must not be fabricated to complete a profile.

Never claim an email is deliverable based on syntax or a domain's existence alone. SMTP checks, when used, must respect provider limitations, applicable rules, and the risks of unnecessary probing. Prefer reputable, authorized verification services where needed.

## 2.2 Information Needed to Break the Ice

Find a **specific, relevant, defensible reason to contact the person**. Prioritize these signals:

1. **Current responsibility:** Is the person responsible for AI infrastructure, APIs, platform engineering, security, data infrastructure, or technical architecture?
2. **Company context:** What product does the company sell, who does it serve, and what technology or business problem is it solving?
3. **Recent company development:** Did the company publicly announce a product launch, integration, expansion, technical initiative, partnership, or relevant hiring push?
4. **Relevant professional work:** Has the person publicly discussed or presented work related to API security, secure AI, agent infrastructure, data access, privacy, trusted execution, or enterprise infrastructure?
5. **Potential technical challenge:** Is there a defensible indication of a problem SealAPI might help address?
6. **Conversation angle:** What thoughtful question could open a conversation without making an unsupported claim?
7. **SealAPI relevance:** Why could a discussion be worth having for this particular person's role and company?

Do not scrape or infer sensitive personal characteristics, private contact details, family information, health information, political beliefs, or other irrelevant personal data.

Do not interpret a generic technology keyword as evidence that a company has a specific security problem.

## 2.3 Store an Evidence-Based Icebreaker

Each researched lead should contain:

- `icebreaker`: a short, factual reference to the person's work or the company's public activity.
- `icebreaker_type`: one of `technical_work`, `company_launch`, `public_interview`, `product_integration`, `hiring_signal`, `company_positioning`, or `general_question`.
- `icebreaker_evidence`: the source IDs supporting the opener.
- `icebreaker_confidence`: a confidence value based on evidence quality.
- `why_it_matters`: why that public information is relevant to a possible SealAPI conversation.
- `potential_pain_point`: a clearly labeled hypothesis, never a claimed fact unless verified.
- `conversation_question`: one concise question grounded in the evidence.
- `personalization_status`: `ready`, `needs_review`, or `generic_fallback`.

A strong icebreaker should sound like a person who read something relevant, not like someone who collected a list of keywords.

**Bad example:**

> I saw you work in AI and thought you might need better security.

This is generic, does not establish genuine familiarity, and assumes a need without evidence.

**Better example — illustrative, not a claim about a real lead:**

Suppose a company's official website announces that it is launching an AI-agent platform with access to enterprise APIs.

> I noticed your team is working on AI agents that interact with enterprise APIs. How are you thinking about controlling which tools and data those agents can access?

Why it works:
- The opening references a verifiable company development.
- The question follows naturally from the public context.
- It does not claim the company has a security weakness.
- It creates an opportunity to discuss access control and secure infrastructure without immediately pitching.

If no useful evidence is found, produce a non-personalized but relevant professional question and mark it as a fallback. Never fabricate an icebreaker to make every lead appear outreach-ready.

---

# 3. Define the Lead Research Output Schema

Introduce versioned Pydantic models and migrate legacy profiles safely. Adapt the example to the project's existing schemas and validation conventions.

The design must separate:
- Original imported data
- Observed source evidence
- Claims supported by evidence
- Inferences or hypotheses
- Research execution status
- Contact readiness
- Lead fit and prioritization

Example schema:

```python
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl


VerificationStatus = Literal[
    "verified",
    "partially_verified",
    "unverified",
    "conflicting",
    "needs_review",
]


class SourceEvidence(BaseModel):
    source_id: str
    source_url: HttpUrl
    source_type: Literal[
        "official_company",
        "official_company_blog",
        "public_professional_profile",
        "public_interview",
        "reputable_news",
        "job_posting",
        "user_input",
        "other_public",
    ]
    title: str | None = None
    publisher: str | None = None
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    published_at: datetime | None = None
    relevant_excerpt: str | None = None
    evidence_quality: float = Field(ge=0.0, le=1.0)
    supports_claim_ids: list[str] = Field(default_factory=list)


class LeadClaim(BaseModel):
    claim_id: str
    field: str
    value: str | None = None
    status: VerificationStatus = "unverified"
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    last_verified_at: datetime | None = None
    review_reason: str | None = None


class ContactReadiness(BaseModel):
    status: Literal[
        "ready",
        "ready_with_caveat",
        "needs_research",
        "not_ready",
    ]
    has_name: bool = False
    has_verified_role: bool = False
    has_company_context: bool = False
    has_usable_contact_channel: bool = False
    has_evidence_based_icebreaker: bool = False
    blockers: list[str] = Field(default_factory=list)


class Icebreaker(BaseModel):
    text: str | None = None
    icebreaker_type: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    why_it_matters: str | None = None
    potential_pain_point: str | None = None
    conversation_question: str | None = None
    personalization_status: Literal[
        "ready", "needs_review", "generic_fallback"
    ] = "needs_review"


class ResearchMetadata(BaseModel):
    schema_version: str = "2.0.0"
    batch_id: str
    pipeline_version: str
    researched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    execution_status: Literal[
        "completed", "partial", "failed"
    ] = "partial"
    verification_status: VerificationStatus = "unverified"
    source_count: int = 0
    review_required: bool = False


class LeadProfileV2(BaseModel):
    lead_id: str
    input_snapshot: dict
    identity: dict
    contact: dict
    company: dict
    professional_context: dict
    public_signals: list[dict] = Field(default_factory=list)
    claims: list[LeadClaim] = Field(default_factory=list)
    sources: list[SourceEvidence] = Field(default_factory=list)
    icebreaker: Icebreaker = Field(default_factory=Icebreaker)
    sealapi_relevance: dict = Field(default_factory=dict)
    scoring: dict = Field(default_factory=dict)
    contact_readiness: ContactReadiness
    research_metadata: ResearchMetadata
```

Extend the model with the actual current application fields as appropriate. Do not remove legacy fields that the existing website, API, or CSV exports depend on without a compatibility strategy.

Every verified claim must reference source IDs. Preserve the original lead input separately so the research process cannot silently rewrite the source data.

---

# 4. Fix Identity Resolution and Incorrect Search Results

The current implementation must not confuse people with the same name, copy irrelevant search results into a lead's profile, or interpret initials as a verified full name.

Implement identity resolution before detailed research.

### Recommended matching signals

- Name compatibility
- Company name or domain match
- Current role or title match
- Official company biography or staff page
- Exact public professional profile URL
- Consistency with the input lead
- Evidence recency and source quality

Do not accept a result merely because its title contains the person's name.

Example algorithm:

```python
def identity_match_score(lead, result) -> float:
    score = 0.0

    if names_compatible(lead.name, result.person_name):
        score += 0.25

    if companies_match(lead.company, result.company):
        score += 0.30

    if titles_compatible(lead.title, result.title):
        score += 0.15

    if official_company_evidence_matches(lead, result):
        score += 0.20

    if result.has_explicit_person_identity:
        score += 0.10

    return min(score, 1.0)
```

Treat this as a starting example, not a statistically calibrated model. Define and test the matching functions, use explicit rejection criteria, and calibrate the weights against manually reviewed examples.

Do not mark a person as verified from the score alone. High-impact claims require supporting evidence. Where two people remain plausible, mark the lead `needs_review`.

For shortened names such as "Andrew R" or "Matt F":
- Keep the supplied name unchanged in `input_snapshot`.
- Search for the person using name, company, title, and domain context.
- Store an expanded name only when reliable evidence supports it.
- Never derive a surname simply from a likely search result.
- Never attach unrelated employment histories or profile details.

Review all existing leads for identity mismatches, missing LinkedIn URLs, and abbreviated names. Do not treat the absence of a LinkedIn URL as proof that a lead is invalid.

---

# 5. Fix the Scraper and Evidence Collection

Modify the existing scraper instead of indiscriminately adding more searches.

## 5.1 Search and fetch separately

A search result is a discovery candidate, not proof.

Use the following sequence:

1. Generate a small set of targeted queries.
2. Collect candidate URLs and search-result metadata.
3. Normalize and deduplicate URLs.
4. Rank results by relevance and likely authority.
5. Fetch eligible destination pages where permitted.
6. Extract relevant factual text and metadata.
7. Record provenance, retrieval time, publication date when available, and page-fetch status.
8. Generate individual claims from the retrieved evidence.
9. Evaluate each claim against its supporting sources.

Prioritize official company websites, official product announcements, public professional biographies, company-owned technical blogs, public interviews, and reputable news.

Do not treat search snippets as verified source content when the destination page has not been fetched. In that case, preserve them as limited discovery evidence and reduce the claim's verification status.

Do not attempt to bypass login walls, CAPTCHAs, access restrictions, paywalls, or anti-bot protections. Respect website terms, robots guidance where applicable, provider rate limits, and privacy requirements. Use authorized APIs or alternative publicly accessible sources when blocked.

## 5.2 Targeted search query generation

Example:

```python
def build_queries(lead):
    queries = []

    if lead.full_name and lead.company_name:
        queries.append(
            f'"{lead.full_name}" "{lead.company_name}"'
        )

    if lead.company_domain:
        queries.append(
            f'site:{lead.company_domain} '
            f'"{lead.first_name or lead.full_name}"'
        )

    if lead.full_name and lead.current_title:
        queries.append(
            f'"{lead.full_name}" "{lead.current_title}"'
        )

    queries.append(
        f'"{lead.company_name}" '
        'API security OR AI infrastructure OR data access'
    )

    return deduplicate_queries(queries)
```

Use only the queries appropriate to the available inputs. Do not send every possible search variation or repeat broad queries that return the same irrelevant content.

Search for a useful public signal relevant to the lead's professional role, not merely any page containing their name.

## 5.3 Implement reliable page fetching

Review the existing `fetch_url()` implementation and:
- Add timeouts, bounded retries, exponential backoff, and clear error classification.
- Apply per-domain rate limits and concurrency limits.
- Handle redirects safely.
- Block unsafe private-network and localhost targets to prevent SSRF.
- Validate URL schemes and redirect destinations.
- Deduplicate equivalent URLs.
- Cache fetched content using a controlled expiration policy.
- Retain retrieval metadata.
- Keep fetch failures separate from verification results.

A page returning HTTP 200 does not mean the content is relevant or verified.

Distinguish:
- `fetch_success`
- `content_extracted`
- `identity_match`
- `claim_verified`
- `research_complete`

Never set all of these to success because one website returned a successful response.

---

# 6. Build Claim-Level Verification

The research pipeline currently risks treating imported facts and loosely related search snippets as verified information.

Change the process so every important output field has an explicit evidence trail.

For example:

- Name and identity
- Current job title
- Current employer
- Company domain
- Professional contact address
- Recent company announcement
- Professional work or technical interest
- Lead-specific SealAPI relevance
- Icebreaker statement

### Verification rules

1. Preserve imported facts as `provided_by_input`, not as independently verified claims.
2. A search result title or snippet is not equivalent to a fetched, relevant source.
3. An official company page showing a person's role is stronger evidence for that role than a generic directory.
4. A source must match the correct person and company before supporting a claim.
5. A stale source must not automatically establish a current job title.
6. Contradictory evidence must be recorded, not silently ignored.
7. No profile field may be labeled `verified` without supporting source IDs.
8. Store the original excerpt or relevant extracted passage that supports the claim.

Use independent evidence where practicable. Do not count syndicated copies of the same announcement as several independent sources.

Example verification flow:

```python
def verify_claim(claim, sources, identity_result):
    relevant_sources = [
        source
        for source in sources
        if source.source_id in claim.source_ids
        and source.supports(claim)
        and source.identity_match_score >= 0.80
    ]

    if identity_result.status == "conflicting":
        claim.status = "conflicting"
        claim.confidence = 0.0
        return claim

    if not relevant_sources:
        claim.status = "unverified"
        claim.confidence = 0.0
        return claim

    if any(source.indicates_contradiction(claim)
           for source in relevant_sources):
        claim.status = "conflicting"
        return claim

    quality = calculate_evidence_quality(relevant_sources)

    if quality >= 0.85 and has_sufficient_support(
        claim, relevant_sources
    ):
        claim.status = "verified"
    elif quality >= 0.55:
        claim.status = "partially_verified"
    else:
        claim.status = "needs_review"

    claim.confidence = quality
    return claim
```

Implement `supports`, `indicates_contradiction`, `calculate_evidence_quality`, and `has_sufficient_support` explicitly. Thresholds are initial settings to validate, not proof of actual accuracy.

---

# 7. Generate Useful Research, Not Generic Biography Text

Replace unsupported synthesis with evidence-grounded summaries.

The current research logic must not automatically:
- Invent responsibilities because of a person's title.
- Claim that a company has a security problem based on industry keywords.
- Describe generic company activity as a person's specific project.
- Create fictional recent developments.
- Attribute technical interests without evidence.
- Set a fixed CTA date such as "next Tuesday."

Generate each factual sentence from one or more relevant claims, and retain source IDs behind the sentence.

Suggested output:

```json
{
  "professional_context": {
    "current_role": "Example role",
    "role_verification": "verified",
    "role_source_ids": ["src_001"]
  },
  "public_signals": [
    {
      "type": "product_launch",
      "summary": "The company publicly announced an AI-agent product.",
      "source_ids": ["src_002"],
      "verification_status": "verified"
    }
  ],
  "sealapi_relevance": {
    "relevance_area": "controlled API access for AI systems",
    "classification": "hypothesis",
    "reason": "The public product context may make this topic relevant.",
    "source_ids": ["src_002"]
  }
}
```

These values are examples of the schema; do not insert them as facts for a real lead.

The system may propose a potential relevance hypothesis, but it must distinguish that hypothesis from a verified company requirement or expressed buying intent.

---

# 8. Implement a Lead-Specific Icebreaker Algorithm

Build a dedicated icebreaker generator rather than embedding generic personalization in the research summary.

### Algorithm

1. Retrieve verified, recent public signals associated with the exact lead and company.
2. Remove stale, ambiguous, duplicate, and irrelevant signals.
3. Rank remaining signals by identity confidence, source authority, relevance to the lead's role, recency, and specificity.
4. Select the strongest eligible signal.
5. Identify a plausible connection to an area SealAPI works on.
6. Draft one factual observation and one natural conversation question.
7. Validate every factual statement against its source IDs.
8. Reject unsupported claims or mark the text for human review.
9. Fall back to a professional but non-personalized opening if no signal is adequate.

Illustrative ranking code:

```python
def rank_public_signal(signal) -> float:
    weights = {
        "identity": 0.30,
        "source_quality": 0.25,
        "relevance": 0.25,
        "recency": 0.10,
        "specificity": 0.10,
    }

    return sum(
        weights[key] * getattr(signal, key + "_score")
        for key in weights
    )


def choose_icebreaker_signal(signals):
    eligible = [
        signal for signal in signals
        if signal.identity_verified
        and signal.source_is_traceable
        and not signal.is_conflicting
        and signal.is_professionally_relevant
    ]

    if not eligible:
        return None

    return max(eligible, key=rank_public_signal)
```

The numerical values are illustrative. Calibrate them using labeled examples and ensure a high relevance score cannot compensate for an incorrect identity or unsupported factual claim.

### Icebreaker validation

Before setting `personalization_status="ready"`, check:
- At least one traceable source supports the opening observation.
- The source refers to the intended person or their company.
- The draft contains no unsupported personal assertion.
- The message does not claim to know an internal problem.
- The question is relevant and not overly invasive.
- The message sounds professional, concise, and natural.

If validation fails, store the draft as `needs_review` or use a clearly labeled generic fallback.

Provide a separate first-message draft with:
- A concise subject line where email is the intended channel.
- A natural greeting.
- The evidence-based icebreaker.
- One short connection to SealAPI's value.
- One low-pressure question or request.
- An appropriate sign-off.

Do not claim an established relationship. Do not fabricate mutual contacts, previous conversations, product usage, customer status, or buying intent. Avoid exaggerated claims, fake urgency, and unsubstantiated security warnings.

---

# 9. Separate Lead Fit, Evidence Confidence, and Contact Readiness

The existing scoring logic reportedly mixes imported lead keywords, research snippets, and confidence. Replace this with three separate evaluations.

## 9.1 Lead-fit score

This measures potential relevance to SealAPI, not evidence certainty.

Suggested factors:

- Professional role and decision-making influence.
- Company product and technical environment.
- Publicly evidenced relevance to APIs, AI infrastructure, data access, security, or related topics.
- Organization and use-case fit.
- Evidence of an appropriate conversation opportunity.

## 9.2 Verification confidence

This measures how reliable the researched profile is.

It should depend on:
- Identity matching.
- Authority of the source.
- Directness of evidence.
- Source recency.
- Independent corroboration.
- Conflicts and ambiguity.

It must not increase simply because an email is present or several irrelevant pages were scraped.

## 9.3 Contact readiness

This determines whether there is enough accurate information to initiate outreach.

A high-potential lead with no reliable identity or contact channel should not be marked fully ready. Conversely, a well-verified person may be contactable while having a low SealAPI fit score.

Recommended initial policy:

```python
def classify_contact_readiness(profile):
    blockers = []

    if not profile.identity.get("name_verified"):
        blockers.append("identity_not_verified")

    if not profile.company.get("company_verified"):
        blockers.append("company_not_verified")

    if not has_usable_contact_channel(profile.contact):
        blockers.append("no_usable_contact_channel")

    if profile.icebreaker.personalization_status == "needs_review":
        blockers.append("icebreaker_needs_review")

    if blockers:
        status = (
            "ready_with_caveat"
            if has_usable_contact_channel(profile.contact)
            else "needs_research"
        )
    else:
        status = "ready"

    return {
        "status": status,
        "blockers": blockers
    }
```

Adapt the exact policy to the product workflow. Do not make a personalized icebreaker mandatory for basic contact readiness if a legitimate professional channel and a good generic opening are available; track personalization readiness separately.

Make score explanations visible to users. A score must be explainable through the evidence and rules that contributed to it.

---

# 10. Create a Reliable BatchID-Based Storage System

**All newly researched data must be stored under `data/output/` and organized by a unique `batchID`.**

First, inspect the existing `data/output/`, `output/`, cache, and profile locations. Preserve legacy integrations until migration and regression tests pass.

If the current implementation does not support proper batch-based output, implement it. If some batch functionality already exists, extend it rather than duplicating it.

## 10.1 Required structure

Use a structure like the following:

```text
data/
├── input/
│   └── newlead.csv
├── output/
│   ├── batches/
│   │   ├── batch_20261020T103000Z_a1b2c3d4/
│   │   │   ├── manifest.json
│   │   │   ├── leads_input_snapshot.csv
│   │   │   ├── lead_profiles.jsonl
│   │   │   ├── leads_enriched.csv
│   │   │   ├── outreach_ready.csv
│   │   │   ├── needs_review.csv
│   │   │   ├── sources.jsonl
│   │   │   ├── claims.jsonl
│   │   │   ├── errors.jsonl
│   │   │   └── summary.json
│   │   └── batch_20261020T120000Z_e5f6g7h8/
│   │       └── ...
│   ├── latest.json
│   ├── profiles/
│   │   └── [legacy compatibility, if required]
│   └── manifest.json
└── ...
```

Each batch must contain the complete record of what that run processed. Adjust file formats if the existing application's performance or interface requires a different approach, but retain the same logical separation.

The `outreach_ready.csv` file should contain only leads satisfying the defined outreach-readiness policy. `needs_review.csv` should contain records that need human intervention. Do not discard leads simply because they fail verification.

## 10.2 Batch ID algorithm

Use a timestamp plus a random suffix or UUID so concurrent executions cannot accidentally generate the same batch ID.

```python
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def create_batch_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    suffix = uuid4().hex[:8]
    return f"batch_{timestamp}_{suffix}"


def create_batch_directory(output_root: Path) -> tuple[str, Path]:
    batch_id = create_batch_id()
    batch_dir = output_root / "batches" / batch_id

    # Never reuse or silently overwrite an existing batch.
    batch_dir.mkdir(parents=True, exist_ok=False)

    return batch_id, batch_dir
```

For strict reproducibility, record input hashes, the pipeline version, schema version, configuration, and start/end timestamps in the manifest.

Do not put credentials, API keys, or sensitive environment variables in a manifest.

## 10.3 Manifest requirements

Each `manifest.json` should include:

```json
{
  "batch_id": "batch_20261020T103000Z_a1b2c3d4",
  "schema_version": "2.0.0",
  "pipeline_version": "record-actual-version",
  "started_at": "2026-10-20T10:30:00Z",
  "completed_at": null,
  "status": "running",
  "input_file": "leads_input_snapshot.csv",
  "input_sha256": "computed-input-file-hash",
  "counts": {
    "total": 0,
    "processed": 0,
    "completed": 0,
    "partial": 0,
    "failed": 0,
    "outreach_ready": 0,
    "needs_review": 0,
    "identity_conflicts": 0
  },
  "files": {},
  "errors": []
}
```

All example values above must be replaced with actual runtime values. The manifest should be written at batch creation and updated as the run progresses.

## 10.4 Storage rules

- Generate a new batch ID for every explicitly requested research run.
- Never reuse a previous batch directory for a new run.
- Do not overwrite historical completed batches.
- Write the input snapshot so each batch can be reproduced and audited.
- Record pipeline version, schema version, input hash, and configuration hash.
- Store research profiles, source records, claims, errors, and summary statistics for that batch.
- Store incomplete results with explicit status rather than silently losing them.
- Update `latest.json` atomically only after a batch reaches a defined publishable state.
- Use atomic file writes for final artifacts.
- Use locking or unique IDs to prevent collisions between concurrent workers.
- Implement retention and deletion policies as explicit configuration, not silent cleanup.
- Never include credentials or unnecessary sensitive data in logs.
- Preserve existing `output/profiles`, `data/output/profiles`, or other paths only as compatibility outputs when the application currently depends on them.

### Example profile path

```text
data/output/batches/{batchID}/profiles/{lead_id}.json
```

Keep the existing application-compatible path if necessary, but make the selected `batchID` explicit throughout the pipeline and API.

## 10.5 Make the batch ID a first-class pipeline concept

Pass `batch_id` through:
- Pipeline creation.
- Research workers.
- Cache keys where relevant.
- Profile metadata.
- CSV and JSON exporters.
- Error records.
- API responses.
- Dashboard batch selection.
- Logging and progress reporting.

Do not generate a new batch ID independently for every worker. All workers processing the same run must use the same batch ID.

---

# 11. Fix Resume Caching and Reprocessing

The existing resume mechanism reportedly identifies cached profiles mainly by `lead_id`. This can return stale or incompatible information when the input, schema, prompts, or scraper logic changes.

Implement a cache fingerprint based on relevant dependencies.

For example:

```python
import hashlib
import json


def research_fingerprint(
    lead_input: dict,
    pipeline_version: str,
    schema_version: str,
    research_config: dict,
) -> str:
    payload = {
        "lead_input": lead_input,
        "pipeline_version": pipeline_version,
        "schema_version": schema_version,
        "research_config": research_config,
    }

    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )

    return hashlib.sha256(serialized.encode()).hexdigest()
```

Store the fingerprint in the profile or manifest and compare it before reusing cached research.

Important behavior:
- Reuse a completed result only when its dependencies remain compatible.
- Never reuse a profile solely because its `lead_id` matches.
- Make forced re-research available.
- Preserve the source batch and its results.
- When exporting a refreshed result, associate it with the new batch.
- If an earlier batch is reused, record the provenance of that reuse.
- Keep cache invalidation separate from historical batch retention.

---

# 12. Repair Existing Lead Profiles

Run a quality audit across the entire current dataset rather than fixing only one or two examples.

Create a per-lead validation report for:
- Identity and name ambiguity.
- Employer and role consistency.
- Broken, inaccessible, irrelevant, or duplicate sources.
- Search snippets that were incorrectly treated as verified sources.
- Missing or invalid professional contact channels.
- Incorrect email-to-person/company relationships.
- Unsupported projects, achievements, and recent developments.
- Generic or fabricated personalization.
- Conflicts between the input CSV and the profile.
- Stale research or cache results.
- Low-quality lead scores.

Prioritize records with name/company mismatches and clearly irrelevant sources. Profiles involving common names, abbreviated names, role conflicts, or unrelated companies should be marked for review until adequate evidence is found.

Examples from the prior code/data review suggest checking abbreviated-name records, profiles with same-name search contamination, questionable company/title mismatches, and cases where source results concern unrelated individuals. Re-discover the actual affected records from the live repository; do not hard-code assumptions from examples.

Do not silently replace an old profile with an uncertain new identity. Record the change, source evidence, and reason.

---

# 13. Update the Exporter and Frontend/API

Preserve the existing API contract wherever possible. Make additions backward-compatible until the frontend has been migrated and tested.

The UI should display:

- Batch ID and batch creation time.
- Total imported, processed, completed, partial, and failed leads.
- Number of outreach-ready leads.
- Number needing review.
- Verified contact information and its status.
- Current title and employer evidence.
- Lead-fit score and a readable explanation.
- Verification confidence and unresolved conflicts.
- Source links.
- The icebreaker and its supporting evidence.
- The recommended contact channel.
- The initial outreach draft.
- The reason a lead was excluded from the outreach-ready export.

Add a batch selector or batch-history page if the frontend already supports batch browsing. Do not show historical and latest records as if they came from the same run.

Provide filters such as:
- Outreach ready.
- Needs research.
- Identity conflict.
- Missing contact channel.
- High SealAPI fit.
- Strong evidence-based icebreaker.

If the dashboard supports downloading CSV files, allow the user to export a selected batch and distinguish between all leads, outreach-ready leads, and records requiring review.

Keep Next.js and FastAPI integration working. Do not remove existing features to simplify this task.

---

# 14. Add Tests for Every Critical Path

Add unit, integration, and end-to-end tests.

## Scraping and identity tests

1. Relevant official company pages rank ahead of irrelevant same-name results.
2. A search result snippet alone cannot verify a claim.
3. A blocked page is not marked as a successful content fetch.
4. Abbreviated names are not automatically expanded.
5. Unrelated people with matching names are rejected or marked for review.
6. A company/title mismatch triggers a conflict or review status.
7. Duplicate URLs and duplicate sources do not inflate verification confidence.
8. Redirects cannot bypass URL safety restrictions.

## Research and personalization tests

9. Every verified claim includes source IDs.
10. An unsupported job title is never marked verified.
11. A generic AI keyword does not create a verified security need.
12. An icebreaker referring to a company launch includes its supporting source.
13. A fabricated project or mutual contact is rejected.
14. No adequate public signal produces a labeled fallback rather than fabricated personalization.
15. A stale source does not automatically establish a current job.
16. Contradictory evidence is represented explicitly.

## Batch and resume tests

17. Every new run creates a unique batch ID.
18. A second batch does not overwrite a previous batch.
19. All workers within one run use the same batch ID.
20. Every output profile points to its originating batch.
21. Partial and failed results remain accounted for.
22. Resume caching rejects incompatible fingerprints.
23. `latest.json` is updated safely.
24. Concurrent runs do not collide.
25. Legacy path compatibility continues to work where required.

## Integration tests

26. CSV import preserves original source data.
27. JSON, CSV, and manifest exports agree on their counts and statuses.
28. Frontend and API can list, select, and view a batch.
29. The outreach-ready export never includes records that fail the readiness criteria.
30. The full pipeline runs against mocked web responses without depending on live websites.

Use deterministic fixtures and mocked responses. Do not make automated tests rely on live search engines, changing public websites, or real email delivery.

Run the project's existing tests, plus any supported frontend type checks, builds, and Docker integration tests.

---

# 15. Benchmark Quality, Not Just Successful Execution

A pipeline that finishes scraping but attaches incorrect evidence is not a successful pipeline.

Establish a manually reviewed validation set that covers:
- Clear identity matches.
- Common names.
- Abbreviated names.
- Conflicting employment information.
- Irrelevant search results.
- Sparse public information.
- Missing email and LinkedIn information.
- Good and poor icebreakers.
- Verified and unverified company signals.

Track these metrics:

| Metric | Definition |
|---|---|
| Correct-person precision | Fraction of identities marked verified that refer to the intended individual |
| Title accuracy | Fraction of verified titles confirmed against the reviewed evidence |
| Company accuracy | Fraction of verified company claims confirmed against reviewed evidence |
| Claim provenance coverage | Fraction of verified claims carrying valid supporting source IDs |
| Source relevance | Fraction of retained sources that genuinely support a profile claim or useful research context |
| Contact accuracy | Fraction of verified contact records belonging to the correct person/company |
| Icebreaker grounding | Fraction of ready icebreakers supported by relevant, accessible evidence |
| Unsupported personalization rate | Fraction of messages containing an unsupported factual assertion |
| Batch completeness | Fraction of imported leads accounted for as completed, partial, failed, or explicitly skipped |
| Reproducibility | Ability to identify inputs, configuration, pipeline version, and output batch for a run |

Use initial release gates of:
- At least 98% correct-person precision among leads marked identity-verified.
- At least 95% accuracy for verified company and current-title claims in the manually reviewed sample.
- 100% of verified claims containing valid supporting source IDs.
- Zero unsupported factual statements in icebreakers marked `ready`.
- 100% of input leads accounted for in exported results or explicitly identified as skipped with a reason.
- No unexplained overwriting of previous batches.

These are acceptance targets, not existing measured results. Calculate them from the actual validation set. If a threshold is missed, document the failure and improve the pipeline rather than claiming it passed.

Do not inflate reported accuracy by measuring only easy or complete profiles.

---

# 16. Recommended Implementation Phases

Execute in this order.

### Phase A — Audit and baseline

Inspect the repository, run baseline tests, document issues, and measure existing dataset quality.

### Phase B — Schema and provenance

Introduce versioned schemas, claim-level evidence, verification states, and separation between imported data and researched facts.

### Phase C — Search, fetch, and identity resolution

Fix source discovery, destination fetching, deduplication, relevance ranking, identity matching, and error handling.

### Phase D — Research synthesis and icebreakers

Replace generic research claims with evidence-grounded summaries and implement the dedicated icebreaker algorithm.

### Phase E — Scoring and contact readiness

Separate lead fit, confidence, and readiness with explainable rules.

### Phase F — Batch storage and resume

Implement immutable batch directories, `batchID` propagation, manifests, input snapshots, cache fingerprints, and safe exports under `data/output/`.

### Phase G — Frontend and API integration

Expose batch selection, evidence, contact readiness, icebreakers, explanations, and export controls without breaking existing behavior.

### Phase H — Testing and migration

Add automated tests, migrate or reprocess existing records into a new batch, compare against the baseline, and verify compatibility.

Do not run an unrestricted full live scrape until the new implementation and mocked tests are passing. Once those tests pass, run a small controlled sample, inspect its output, then reprocess the whole dataset into a **new batch ID**.

---

# 17. Required Final Deliverables

At completion, provide:

1. A summary of the root causes found in the original implementation.
2. A list of files changed and why.
3. The implemented schema and verification workflow.
4. The scoring and icebreaker algorithms, including their parameters and limitations.
5. The new `data/output/batches/{batchID}/` layout.
6. Example JSON, CSV, and manifest files from a real test run.
7. Unit, integration, and frontend test results.
8. The actual data-quality benchmark, clearly distinguishing measured outcomes from targets.
9. The number of leads that are outreach-ready, need review, remain unverified, or failed research.
10. Any unresolved issues or external service requirements.
11. Updated documentation explaining how to run the pipeline, resume a batch, start a fresh batch, review leads, and export outreach-ready data.
12. Confirmation that previous completed batches were not silently overwritten.

Document the exact commands for local development and Docker execution using the existing project's environment and port configuration.

## Final Acceptance Criteria

The task is complete only when:

- The existing pipeline works end to end.
- Research distinguishes search discovery from actual evidence.
- Identity and employment claims are supported by relevant sources.
- Contact fields and email status are represented honestly.
- Icebreakers are relevant, source-backed, and free of unsupported assertions.
- Lead-fit scoring is separate from verification confidence and contact readiness.
- Each new research run gets its own batch ID and preserves its history under `data/output/`.
- Cache invalidation and reprocessing work correctly.
- CSV/JSON exports and the dashboard agree on statuses and counts.
- Automated tests pass, or remaining failures are explicitly documented.
- The final report contains measured results rather than unsupported claims of completion.

**Important execution rule:** Work incrementally, inspect the existing code before changing it, implement actual fixes rather than merely producing this plan, and do not weaken verification rules just to increase the number of leads labeled outreach-ready.