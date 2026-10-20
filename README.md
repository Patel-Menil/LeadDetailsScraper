# SealAPI Lead Research & Prioritization Pipeline

A production-conscious lead intelligence, web extraction, and enrichment pipeline for **SealAPI** using the **Scrapling** Python library.

The system accepts CSV or Excel lead lists, extracts publicly accessible professional and infrastructure information using Scrapling, assigns deterministic priority levels (0=Highest, 1=Medium, 2=Lowest), generates an enriched prioritized CSV, and creates a versioned, verifiable JSON research profile per person.

Included is a **single-container Docker setup** and an enterprise localhost **web dashboard** that allows users to upload files, preview columns, trigger research batches, inspect prioritized leads in the browser, review full JSON profiles, and download exports.

---

## 🚀 Key Features

1. **Robust Import & Validation (`CSV` & `XLSX`)**
   - Automatically detects standard lead columns (`Name`, `Title`, `Company`, `Email`, `Website`, `LinkedIn`, `Industry`).
   - Generates stable, deterministic lead IDs (`lead_<hash>`).
   - Detects duplicate records (by normalized email, profile URL, or name+company).
   - Generates import summaries, row-level validation errors, and sample previews.

2. **Public-Web Research via Scrapling**
   - Uses Scrapling (`Fetcher`, `Selector`) for high-reliability HTTP extraction.
   - Extracts website titles, meta descriptions, headings, and tech/security keywords.
   - Respects rate limits, timeouts (configurable, default 10s), and bounded retries.
   - Treats scraped content as untrusted input with sanitization.
   - Transparently records authentication limitations (e.g. LinkedIn login walls) without fabricating facts or breaking pipeline execution.

3. **Deterministic Priority Scoring (0, 1, 2)**
   - **Priority 0 (Highest Fit)**: CISO, Chief AI Officer, Head of AI, VP Engineering, or CTO in target enterprise verticals (cybersecurity, software, healthcare, financial services) with active AI/API security needs.
   - **Priority 1 (Medium Fit)**: Relevant leadership or vertical, requiring further qualification of immediate urgency.
   - **Priority 2 (Lowest Fit)**: Weak fit or insufficient evidence.
   - Includes transparent reasoning and traceable supporting evidence.

4. **Structured Dual Outputs**
   - **Output A: Prioritized CSV** (`output/<batch_id>/leads_prioritized.csv`): Sorted by numeric priority (0, then 1, then 2), preserving all original columns plus enrichment metadata.
   - **Output B: Per-Person JSON Profiles** (`output/<batch_id>/profiles/person_<id>_<slug>.json`): Conforms to a versioned schema with `identity`, `professional_context`, `priority`, `sources`, `cold_email_context`, and `research_metadata`.
   - **Errors Report** (`output/<batch_id>/errors.csv`): Actionable report of row-level errors and domain limitations.
   - **Manifest** (`manifest.json`): Batch metadata and priority distributions.

5. **Enterprise Localhost Web Application**
   - **Dashboard**: High-level metrics (total leads, P0/P1/P2 breakdown, recent batches).
   - **Import Leads**: Drag-and-drop file upload, column mapping overrides, validation report, dry-run mode.
   - **Prioritized Leads**: Filterable table (by priority, status, search, pagination) reading directly from the enriched CSV.
   - **Profile Detail Modal**: 5 tabs (Overview, Professional Research, Source Evidence, Cold Email Context, Raw JSON with copy & download).
   - **Batch Progress**: Live progress bar, counters, and real-time execution logs.
   - **Export Center**: Instant downloads for CSV, Errors CSV, and complete batch ZIP archive.

---

## 🐳 Quick Start with Docker (Single Application Container)

The application is packaged into a **single application container** running both the **Next.js frontend** and the **FastAPI Scrapling research backend** supervised in a single container.

### 1. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

### 2. Build and Start Container
```bash
docker compose up -d --build
```

### 3. Verify Health & Open Applications
- **Next.js Web Frontend**: [http://127.0.0.1:3000](http://127.0.0.1:3000)
- **FastAPI Backend & API Proxy**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **API Health Check**: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)
- **API Documentation (Swagger)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 4. Stopping & Managing
- Check status: `docker compose ps`
- View live logs: `docker compose logs -f`
- Stop container: `docker compose down`

All data and generated profiles are persisted in `./data` (`./data/uploads` and `./data/batches`).

---

## 💻 Localhost Development Setup (Without Docker)

You can run both the Next.js frontend and the FastAPI backend concurrently on localhost:

### 1. Requirements
- Python 3.11+
- Node.js 20+ and npm 10+

### 2. Backend Setup & Run (Port 8000)
```bash
pip install -r requirements.txt
uvicorn src.lead_research.server:app --host 127.0.0.1 --port 8000 --reload
```

### 3. Frontend Setup & Run (Port 3000)
```bash
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser.

### 4. Frontend Production Build & Type Checking
```bash
# Typecheck TypeScript
npm run typecheck

# Production Next.js Build
npm run build

# Start Production Server
npm run start
```

---

## 🛠️ Command-Line Interface (CLI)

The backend pipeline can also be run directly from the command line:

```bash
# Standard research batch
python -m src.lead_research --input newlead.csv --output output/

# Dry-run mode (validate, normalize, and score without HTTP calls)
python -m src.lead_research --input newlead.csv --output output/ --dry-run

# Limit number of leads and specify concurrency
python -m src.lead_research --input newlead.csv --output output/ --max-leads 10 --concurrency 4

# Force re-scraping (ignore resume cache)
python -m src.lead_research --input newlead.csv --output output/ --no-resume
```

---

## 🧪 Automated Testing

### 1. Backend Automated Tests (Pytest)
```bash
pytest tests/ -v
```

### 2. Frontend Automated Tests (Node Test Runner)
```bash
npm test
```
Tests verify numerical priority sorting (0 first, 1, 2), pagination boundaries, search query filtering, and API endpoint construction.

---

## 📋 Schema Reference

### Prioritized CSV Columns (`leads_prioritized.csv`)
1. `lead_id`: Stable identifier (e.g., `lead_c6a4e1670bbb`)
2. `name`: Full name
3. `job_title`: Job title
4. `company`: Company name
5. `industry`: Industry vertical
6. `linkedin_url`: LinkedIn profile URL
7. `company_website`: Company website domain
8. `professional_email`: Verified business email
9. `priority`: Numeric priority (`0`, `1`, `2`)
10. `priority_reason`: Explainable reason for priority assignment
11. `relevance_evidence`: Traceable signals supporting the priority
12. `profile_json_path`: Relative path to individual JSON profile
13. `research_status`: `completed`, `partial`, or `failed`
14. `last_researched_at`: ISO 8601 timestamp
*Plus all original columns from the uploaded input file.*

### Individual JSON Profile (`profiles/person_<id>_<slug>.json`)
```json
{
  "schema_version": "1.0.0",
  "lead_id": "lead_c6a4e1670bbb",
  "identity": {
    "name": "Jane Doe",
    "job_title": "Head of AI",
    "company": "Acme Corp",
    "industry": "information technology",
    "professional_email": "jane@acme.com",
    "company_website": "https://acme.com",
    "linkedin_url": "https://linkedin.com/in/janedoe"
  },
  "professional_context": {
    "responsibilities": [...],
    "technical_interests": [...],
    "public_projects": [...],
    "recent_developments": [...],
    "sealapi_relevance": {
      "summary": "...",
      "relevant_use_cases": ["Secure AI Integration & LLM Guardrails"],
      "evidence_points": [...]
    }
  },
  "priority": {
    "numeric_priority": 0,
    "reason": "Priority 0 (Highest Fit): Head of AI at Acme Corp ...",
    "score": 90.0,
    "confidence": 0.85,
    "supporting_evidence": [...]
  },
  "sources": [
    {
      "source_url": "https://acme.com",
      "source_type": "company_website",
      "retrieval_timestamp": "2026-10-10T16:00:00Z",
      "facts_supported": [...]
    }
  ],
  "cold_email_context": {
    "verified_personalization_points": [...],
    "suggested_value_propositions": [...],
    "suggested_call_to_action": "...",
    "claims_to_avoid": [...],
    "missing_verification_points": []
  },
  "research_metadata": {
    "research_status": "completed",
    "last_research_timestamp": "2026-10-10T16:00:00Z",
    "sources_examined": 2,
    "errors_and_limitations": []
  }
}
```

---

## 🔒 Security & Operational Guardrails

- **Untrusted Input Sanitization**: Scraped text is sanitized, stripping invisible control characters, scripts, and limiting length.
- **Path Traversal Protection**: Export filenames and lead IDs are sanitized using strict alphanumeric rules.
- **Login Wall & Anti-Bot Respect**: The system does not bypass CAPTCHAs or authentication walls. Restricted domains (e.g. LinkedIn profiles) are flagged in limitations and public company sources are used instead.
- **No Hallucinations**: Cold-email hooks and priority reasoning are strictly grounded in verified facts from import records and accessible public domains.
