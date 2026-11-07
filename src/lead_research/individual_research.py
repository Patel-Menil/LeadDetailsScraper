"""Individual research: company discovery, profile, SealAPI verdict and priority, plus the in-memory job pipeline."""
import contextlib
import hashlib
import re
import secrets
import threading
from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from .company_intel import (
    COMPANY_ID_RE, FIT_LABELS, FREE_MAIL_DOMAINS, CompanyResearcher, new_company_record, normalize_company_name,
    normalize_domain,
)
from .individual_discovery import (
    Candidate, GitHubSource, IndividualInput, Observation, SearchSource, collect_observations, resolve_identity,
)
from .research import is_company_corroborated
from .sealapi_capabilities import SCOPE_NOTE
from .scraper import ScrapeResult

SOCIAL_DOMAINS = {
    "linkedin.com", "x.com", "twitter.com", "github.com", "facebook.com", "instagram.com", "youtube.com",
    "medium.com", "crunchbase.com", "wikipedia.org", "tiktok.com", "reddit.com", "substack.com", "bsky.app",
    "threads.net", "pinterest.com", "glassdoor.com", "bloomberg.com", "zoominfo.com", "pitchbook.com",
}
_NEVER_FETCH = ("linkedin.com", "x.com", "twitter.com")
MAX_FETCHES = 6
MAX_ITEMS = 5


def _domain_in(domain: str, domains) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in domains)


def _usable_domain(url: str) -> str:
    d = normalize_domain(url)
    if not d or _domain_in(d, SOCIAL_DOMAINS) or _domain_in(d, FREE_MAIL_DOMAINS) or _domain_in(d, _NEVER_FETCH):
        return ""
    return d


def _distinctive_token(company: str) -> str:
    tokens = [t for t in normalize_company_name(company).split() if len(t) >= 3]
    return max(tokens, key=len) if tokens else ""


def _unknown(name: str, note: str) -> dict:
    return {"name": name, "domain": "", "domain_source": "", "corroborated": False, "note": note, "status": "unknown"}


def discover_company(
    candidate: Candidate, inp: IndividualInput, search: SearchSource, fetch: Callable[[str], ScrapeResult],
) -> dict:
    name = (candidate.company or inp.company or "").strip()
    if not name:
        return _unknown("", "No company is known for this person.")

    gh_sites = [o.website for o in candidate.observations if o.source_type == "github" and o.website]
    other_sites = [o.website for o in candidate.observations if o.source_type == "website" and o.website]
    token = _distinctive_token(name)

    def raw_candidates():
        for u in gh_sites:
            yield u, "github_blog"
        if inp.website:
            yield inp.website, "website"
        for u in other_sites:
            yield u, "website"
        if candidate.website:
            yield candidate.website, "github_blog" if candidate.website in gh_sites else "website"
        if token:
            for o in candidate.observations:
                d = _usable_domain(o.url or "")
                if d and token in d:
                    yield o.url, "search_result"
        try:
            hits = search.search(f'"{name}" official site') or []
        except Exception:  # noqa: BLE001 - discovery must never raise
            hits = []
        for h in hits[:10]:
            yield (h.get("url") or ""), "search"

    tried: List[str] = []
    errors: List[str] = []
    fetches = 0
    extra: List[Tuple[str, str]] = []
    gen = raw_candidates()
    supplied = _usable_domain(inp.website) if inp.website else ""
    while True:
        if extra:
            url, source = extra.pop(0)
        else:
            nxt = next(gen, None)
            if nxt is None:
                break
            url, source = nxt
        try:
            domain = _usable_domain(url)
            if not domain or domain in tried:
                continue
            tried.append(domain)
            if fetches >= MAX_FETCHES:
                break
            fetches += 1
            target = f"https://{domain}/"
            page = fetch(target)
            if not getattr(page, "success", False):
                continue
            ok, why = is_company_corroborated(
                name, target, getattr(page, "url", "") or target, page.title or "", page.meta_description or "",
                page.extracted_text or "",
            )
            if ok:
                return {"name": name, "domain": domain, "domain_source": source, "corroborated": True,
                        "note": why or "Website content mentions the company.", "status": "verified"}
            if token and domain == supplied and source == "website":
                for href, _text in (getattr(page, "links", None) or []):
                    if _usable_domain(href) and token in _usable_domain(href):
                        extra.append((href, "website_link"))
        except Exception as e:  # noqa: BLE001 - discovery must never raise
            errors.append(f"{type(e).__name__}")
            continue
    if tried:
        note = f"Could not verify a company website for {name} (tried {', '.join(tried)})."
        if errors:
            note += f" {len(errors)} candidate(s) errored: {', '.join(sorted(set(errors)))}."
        return _unknown(name, note)
    return _unknown(name, f"No candidate website found for {name}.")


# ---------------------------------------------------------------- role
def _has(title: str, *patterns: str) -> bool:
    return any(re.search(p, title) for p in patterns)


_AI_WORD = r"(?:\bai\b|\bml\b|machine learning|artificial intelligence|\bllm\b|deep learning|data science|generative)"
_LEAD_WORD = r"(?:head|director|chief|vp|vice president|lead|principal|manager)"


def classify_role(title: str) -> dict:
    t = (title or "").lower().strip()

    def out(cat: str, auth: str) -> dict:
        return {"category": cat, "authority": auth, "basis": "inferred"}

    if not t:
        return out("Other", "unknown")
    if _has(t, r"co-?\s?founder", r"\bfounder\b"):
        return out("Founder / Co-founder", "executive")
    if _has(t, r"\bcto\b", r"chief technology", r"chief technical"):
        return out("CTO", "executive")
    if _has(t, r"\bciso\b", r"chief information security", r"chief security"):
        return out("CISO", "executive")
    if _has(t, r"\bceo\b", r"chief executive"):
        return out("CEO", "executive")
    if _has(t, r"chief " + _AI_WORD, r"chief .*\b(?:ai|data|analytics) officer"):
        return out("AI/ML Leader", "executive")
    if _has(t, r"\bvp\b.*engineering", r"vice president.*engineering", r"engineering.*\bvp\b", r"head of engineering",
            r"director of engineering"):
        return out("VP Engineering", "senior_leader")
    if _has(t, r"(?:head|director|vp|vice president|lead)\b.*" + _AI_WORD):
        return out("AI/ML Leader", "senior_leader")
    if _has(t, r"security architect"):
        return out("Security Architect", "practitioner")
    if _has(t, _AI_WORD + r".*(?:engineer|scientist|developer|researcher)", r"(?:engineer|scientist|developer).*" + _AI_WORD):
        return out("AI Engineer", "practitioner")
    if _has(t, r"engineering manager", r"manager.*engineering"):
        return out("Engineering Manager", "senior_leader")
    return out("Other", "unknown")


# ---------------------------------------------------------------- repos / profile
AI_KEYWORDS = ["llm", "gpt", "openai", "anthropic", "claude", "langchain", "rag", "embedding", "transformer",
               "machine learning", "ml", "ai", "agent", "vector"]
_KW_RX = {k: re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])") for k in AI_KEYWORDS}


def ai_repo_signals(repos: List[dict]) -> List[dict]:
    out: List[dict] = []
    for r in repos or []:
        if not isinstance(r, dict):
            continue
        topics = r.get("topics") or []
        blob = " ".join([str(r.get("name") or ""), str(r.get("description") or "")]
                        + [str(t) for t in topics if isinstance(t, str)]).lower()
        blob = blob.replace("-", " ").replace("_", " ")
        matched = [k for k in AI_KEYWORDS if _KW_RX[k].search(blob)]
        if matched:
            out.append({"repo": str(r.get("name") or ""), "url": str(r.get("html_url") or r.get("url") or ""),
                        "matched": matched, "language": r.get("language") or ""})
    return out


def build_professional_profile(candidate: Candidate, repos: List[dict]) -> dict:
    repos = [r for r in (repos or []) if isinstance(r, dict)]
    gh_obs = [o for o in candidate.observations if o.source_type == "github"]
    facts: List[dict] = []

    def add(label: str, value: str, attr: str) -> None:
        if not value:
            return
        ids = [o.source_id for o in candidate.observations if getattr(o, attr, "") == value]
        verified = any(o.source_type == "github" for o in candidate.observations if getattr(o, attr, "") == value)
        facts.append({"text": f"{label}: {value}", "basis": "verified" if verified else "inferred", "source_ids": ids})

    add("Title", candidate.title, "title")
    add("Company", candidate.company, "company")
    add("Location", candidate.location, "location")
    if gh_obs and candidate.github_login:
        facts.append({"text": f"GitHub account: {candidate.github_login}", "basis": "verified",
                      "source_ids": [o.source_id for o in gh_obs]})
    langs: List[str] = []
    for r in repos:
        lang = r.get("language")
        if lang and lang not in langs:
            langs.append(lang)
    return {
        "current_title": candidate.title, "current_company": candidate.company, "location": candidate.location,
        "role": classify_role(candidate.title), "facts": facts,
        "github": {"login": candidate.github_login, "public_repos": len(repos), "languages": langs,
                   "ai_repos": ai_repo_signals(repos)},
    }


# ---------------------------------------------------------------- verdict / priority
_RELEVANCE = {
    "strong": "relevant", "validation_required": "needs_validation", "weak": "not_relevant",
    "not_suitable": "not_relevant", "insufficient_evidence": "insufficient_evidence",
}


def sealapi_verdict(company_record: Optional[dict]) -> dict:
    fit = (company_record or {}).get("company_fit") if isinstance(company_record, dict) else None
    if not isinstance(fit, dict) or not company_record:
        return {"relevance": "insufficient_evidence", "fit_label": FIT_LABELS.get("insufficient_evidence", "Insufficient evidence"),
                "reasoning": "The person's company could not be verified, so SealAPI relevance cannot be assessed.",
                "opportunities": [], "discovery_questions": [], "scope_note": SCOPE_NOTE}
    cls = fit.get("classification") or ""
    return {
        "relevance": _RELEVANCE.get(cls, "insufficient_evidence"),
        "fit_label": fit.get("label") or FIT_LABELS.get(cls, ""),
        "reasoning": fit.get("reasoning") or "",
        "opportunities": [o for o in (company_record.get("opportunities") or [])][:MAX_ITEMS],
        "discovery_questions": [q for q in (company_record.get("discovery_questions") or [])][:MAX_ITEMS],
        "scope_note": SCOPE_NOTE,
    }


_P0_CATEGORIES = {"CISO", "Security Architect", "AI/ML Leader"}


def assign_priority(relevance: str, role: dict) -> dict:
    authority = (role or {}).get("authority", "unknown")
    category = (role or {}).get("category", "Other")
    strong_role = authority == "executive" or category in _P0_CATEGORIES
    fit = "Relevant company" if relevance == "relevant" else "Company fit needs validation"
    if relevance in ("relevant", "needs_validation") and strong_role:
        level, reasons = 0, [fit, f"Decision-maker role ({category})"]
    elif relevance in ("relevant", "needs_validation"):
        level, reasons = 1, [fit, f"Role ({category}) is not a primary decision-maker"]
    elif relevance == "not_relevant" and authority == "executive":
        level, reasons = 1, ["Company fit is weak", f"Executive role ({category}) may still influence"]
    elif relevance == "not_relevant":
        level, reasons = 2, ["Company fit is weak", f"Role: {category}"]
    else:
        level, reasons = 2, ["Insufficient evidence about the company"]
    return {"level": level, "label": f"P{level}", "reasons": reasons}


# ---------------------------------------------------------------- in-memory stores
class MemoryCompanyStore:
    """Dict-backed stand-in for CompanyStore: same methods CompanyResearcher uses, no file IO."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: Dict[str, dict] = {}
        self._cache: Dict[str, Dict[str, dict]] = {}

    def load(self, company_id: str) -> Optional[dict]:
        with self._lock:
            return self._records.get(company_id)

    def save(self, record: dict) -> None:
        with self._lock:
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._records[record["company_id"]] = record

    def cache_get(self, company_id: str, url: str, max_age: Optional[timedelta] = None) -> Optional[dict]:
        with self._lock:
            for page in self._cache.get(company_id, {}).values():
                if page.get("url") == url or page.get("requested_url") == url:
                    return page
            return None

    def cache_put(self, company_id: str, page: dict) -> None:
        with self._lock:
            self._cache.setdefault(company_id, {})[page.get("normalized_url") or page.get("url", "")] = page


STAGES: List[str] = ["discovery", "identity_resolution", "company_discovery", "company_research",
                     "professional_profile", "verdict"]
JOB_ID_RE = re.compile(r"^ind_[0-9a-f]{16}$")
KNOWN_LIMITS = [
    "DuckDuckGo Lite returns about 5 results per query and may throttle.",
    "JavaScript-rendered sites produce thin company findings.",
    "GitHub unauthenticated search allows 10 requests/minute.",
]
LINKEDIN_LIMIT = "LinkedIn data comes only from search snippets."


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IndividualJobStore:
    def __init__(self, max_jobs: int = 50, ttl: timedelta = timedelta(hours=1),
                 now: Callable[[], datetime] = _utcnow):
        self.max_jobs, self.ttl, self._now = max_jobs, ttl, now
        self._jobs: "OrderedDict[str, dict]" = OrderedDict()
        self._born: Dict[str, datetime] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._mutex = threading.RLock()

    @staticmethod
    def _validate(job_id: str) -> str:
        if not isinstance(job_id, str) or not JOB_ID_RE.match(job_id):
            raise ValueError("Invalid job id")
        return job_id

    def _drop(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        self._born.pop(job_id, None)
        self._locks.pop(job_id, None)

    def _evict_expired(self) -> None:
        cutoff = self._now() - self.ttl
        for jid in [j for j, t in self._born.items() if t <= cutoff]:
            self._drop(jid)

    def create(self, inp: IndividualInput) -> dict:
        with self._mutex:
            self._evict_expired()
            while len(self._jobs) >= self.max_jobs:
                self._drop(next(iter(self._jobs)))
            job_id = "ind_" + secrets.token_hex(8)
            ts = self._now().isoformat()
            job = {
                "job_id": job_id, "status": "running", "created_at": ts, "updated_at": ts, "input": asdict(inp),
                "stages": [{"name": n, "status": "pending", "message": "", "started_at": None, "finished_at": None}
                           for n in STAGES],
                "candidates": [], "selected_candidate_id": "", "identity": None, "person": None, "company": None,
                "ai_usage": {"ai_findings": [], "providers": [], "ai_products": []}, "sealapi": None, "priority": None,
                "sources": [], "errors": [], "limitations": list(KNOWN_LIMITS), "running": False,
            }
            self._jobs[job_id] = job
            self._born[job_id] = self._now()
            self._locks[job_id] = threading.Lock()
            return job

    def get(self, job_id: str) -> Optional[dict]:
        self._validate(job_id)
        with self._mutex:
            self._evict_expired()
            return self._jobs.get(job_id)

    def lock(self, job_id: str) -> threading.Lock:
        self._validate(job_id)
        with self._mutex:
            if job_id not in self._locks:
                self._locks[job_id] = threading.Lock()
            return self._locks[job_id]


# ---------------------------------------------------------------- pipeline
def _candidate_from_dict(d: dict) -> Candidate:
    return Candidate(**{**d, "observations": [Observation(**o) for o in d.get("observations") or []]})


def company_id_for(domain: str) -> str:
    return "co_" + hashlib.sha1(domain.encode()).hexdigest()[:12]


def build_ai_usage(record: Optional[dict]) -> dict:
    findings = [f for f in (record or {}).get("findings") or []
                if isinstance(f, dict) and f.get("category") in ("ai", "ai_provider")]
    ai_findings = [{"evidence": f.get("evidence", ""), "source_url": f.get("source_url", ""), "label": f.get("label", "")}
                   for f in findings]
    providers = sorted({f.get("label", "") for f in findings if f.get("category") == "ai_provider" and f.get("label")})
    pids = {f.get("product_id") for f in findings if f.get("product_id")}
    products: List[str] = []
    for p in (record or {}).get("products") or []:
        if isinstance(p, dict) and p.get("product_id") in pids and p.get("name") and p["name"] not in products:
            products.append(p["name"])
    return {"ai_findings": ai_findings, "providers": providers, "ai_products": products}


_DEPENDENTS = {
    "discovery": None, "identity_resolution": None, "company_discovery": ["company_research", "verdict"],
    "company_research": ["verdict"], "professional_profile": [], "verdict": [],
}


class IndividualPipeline:
    def __init__(
        self, search: SearchSource, github: GitHubSource, fetch: Callable[[str], Any],
        company_researcher: Callable[[MemoryCompanyStore], CompanyResearcher] = CompanyResearcher,
        company_slots: Any = None,
    ):
        self.search, self.github, self.fetch = search, github, fetch
        self.company_researcher = company_researcher
        self.company_slots = company_slots if company_slots is not None else contextlib.nullcontext()

    # -- helpers
    @staticmethod
    def _stage(job: dict, name: str) -> dict:
        return next(s for s in job["stages"] if s["name"] == name)

    def _set(self, job: dict, name: str, status: str, message: Optional[str] = None) -> None:
        st = self._stage(job, name)
        st["status"] = status
        if message is not None:
            st["message"] = message
        now = _utcnow().isoformat()
        if status == "running":
            st["started_at"], st["finished_at"] = now, None
        else:
            st["finished_at"] = now
        job["updated_at"] = now

    def _candidate(self, job: dict) -> Optional[Candidate]:
        cid = job.get("selected_candidate_id")
        for d in job.get("candidates") or []:
            if d.get("candidate_id") == cid:
                return _candidate_from_dict(d)
        return None

    @staticmethod
    def _inp(job: dict) -> IndividualInput:
        return IndividualInput(**job["input"])

    # -- public
    def select(self, job: dict, candidate_id: str) -> None:
        cand = next((d for d in job["candidates"] if d["candidate_id"] == candidate_id), None)
        if cand is None:
            raise KeyError(candidate_id)
        job["selected_candidate_id"] = candidate_id
        job["identity"] = {"mode": "select", "message": f"Selected {cand['name']}.", "confidence": cand["confidence"]}
        self._set(job, "identity_resolution", "done", f"Selected {cand['name']}.")

    def retry_stage(self, job: dict) -> Optional[str]:
        return next((s["name"] for s in job["stages"] if s["status"] in ("failed", "skipped")), None)

    def run(self, job: dict, start_stage: str = "discovery") -> None:
        if start_stage not in STAGES:
            raise ValueError(f"Unknown stage {start_stage}")
        if start_stage == "identity_resolution":
            start_stage = "discovery"  # observations are not persisted; identity needs a fresh discovery
        if start_stage == "company_research" and (job.get("company") or {}).get("status") != "verified":
            start_stage = "company_discovery"
        start = STAGES.index(start_stage)
        job["running"], job["status"] = True, "running"
        for name in STAGES[start:]:
            self._stage(job, name).update(status="pending", message="", started_at=None, finished_at=None)
        ctx: Dict[str, Any] = {}
        try:
            for name in STAGES[start:]:
                if self._stage(job, name)["status"] == "skipped":  # dependency failed earlier in this run
                    continue
                if self._run_stage(job, name, ctx):
                    break
        finally:
            job["status"] = self._final_status(job)
            job["running"] = False
            job["updated_at"] = _utcnow().isoformat()

    # -- orchestration
    @staticmethod
    def _final_status(job: dict) -> str:
        sts = {s["name"]: s["status"] for s in job["stages"]}
        if "needs_input" in sts.values():
            return "needs_input"
        if sts["discovery"] == "failed":
            return "failed"
        if any(v in ("failed", "skipped") for v in sts.values()):
            return "partial"
        return "completed"

    def _run_stage(self, job: dict, name: str, ctx: dict) -> bool:
        """Run one stage; return True when the run must stop."""
        self._set(job, name, "running")
        try:
            status, msg = getattr(self, "_do_" + name)(job, ctx)
        except Exception as e:  # noqa: BLE001 - nothing propagates out of run
            msg = f"{type(e).__name__}: {str(e)[:200]}"
            job["errors"].append(f"{name} failed: {msg}")
            self._set(job, name, "failed", msg)
            deps = _DEPENDENTS[name]
            for later in STAGES[STAGES.index(name) + 1:]:
                if deps is None or later in deps:
                    self._set(job, later, "skipped", f"Skipped because {name} failed.")
            return deps is None
        self._set(job, name, status, msg)
        return status == "needs_input"

    # -- stages, each returns (status, message)
    def _do_discovery(self, job: dict, ctx: dict) -> Tuple[str, str]:
        job.update(sources=[], candidates=[], identity=None, person=None, selected_candidate_id="", company=None,
                   sealapi=None, priority=None, errors=[], limitations=list(KNOWN_LIMITS),
                   ai_usage=build_ai_usage(None))
        observations, sources, errors = collect_observations(self._inp(job), self.search, self.github, self.fetch)
        ctx["observations"] = observations
        job["sources"] = list(sources)
        job["errors"].extend(errors)
        return "done", f"{len(observations)} observation(s) from {len(sources)} source(s)."

    def _do_identity_resolution(self, job: dict, ctx: dict) -> Tuple[str, str]:
        decision = resolve_identity(ctx.get("observations") or [], self._inp(job))
        job["candidates"] = [c.to_dict() for c in decision.candidates]
        top_conf = decision.candidates[0].confidence if decision.candidates else 0.0
        job["identity"] = {"mode": decision.mode, "message": decision.message, "confidence": top_conf}
        if decision.mode == "auto":
            job["selected_candidate_id"] = decision.selected_id
            return "done", decision.message
        return "needs_input", decision.message

    def _do_company_discovery(self, job: dict, ctx: dict) -> Tuple[str, str]:
        cand = self._candidate(job)
        if cand is None:
            raise RuntimeError("no candidate selected")
        if LINKEDIN_LIMIT not in job["limitations"] and any(
                o.source_type == "search" and o.linkedin_slug for o in cand.observations):
            job["limitations"].append(LINKEDIN_LIMIT)
        job["company"] = None
        comp = discover_company(cand, self._inp(job), self.search, self.fetch)
        job["company"] = {**comp, "company_id": company_id_for(comp["domain"]) if comp["domain"] else "", "intel": None}
        if comp["status"] == "verified":
            return "done", f"Company website verified: {comp['domain']}."
        return "done", comp["note"]

    def _do_company_research(self, job: dict, ctx: dict) -> Tuple[str, str]:
        comp = job.get("company") or {}
        if comp.get("status") != "verified":
            return "skipped", "Company website could not be verified."
        record = new_company_record({"company_id": comp["company_id"], "name": comp["name"], "domain": comp["domain"],
                                     "domain_source": comp["domain_source"]})
        with self.company_slots:
            record = self.company_researcher(MemoryCompanyStore()).research(record)
        pages = [p for p in record.get("pages") or [] if isinstance(p, dict)]
        intel = {k: v for k, v in record.items() if k not in ("pages", "links")}
        intel["pages"] = [{k: v for k, v in p.items() if k not in ("text", "links")} for p in pages]
        comp["intel"] = intel
        job["sources"] = [s for s in job["sources"] if s.get("source_type") != "company_site"] + [
            {"url": p.get("url", ""), "title": p.get("title", ""), "accessed_at": p.get("accessed_at", ""),
             "source_type": "company_site"} for p in pages if p.get("success")]
        job["ai_usage"] = build_ai_usage(record)
        if record.get("research_status") == "failed":
            errs = "; ".join(str(e) for e in (record.get("errors") or [])[:3]) or "company research failed"
            job["errors"].append(f"company_research failed: {errs}")
            return "failed", errs
        return "done", f"Researched {comp['domain']} ({len(pages)} page(s))."

    def _do_professional_profile(self, job: dict, ctx: dict) -> Tuple[str, str]:
        cand = self._candidate(job)
        if cand is None:
            raise RuntimeError("no candidate selected")
        repos: List[dict] = self.github.get_repos(cand.github_login, limit=10) if cand.github_login else []
        for e in getattr(self.github, "errors", []):
            if e not in job["errors"]:
                job["errors"].append(e)
        profile = build_professional_profile(cand, repos)
        job["person"] = {**profile, "candidate": cand.to_dict(), "identity_confidence": cand.confidence}
        return "done", f"Profile built for {cand.name}."

    def _do_verdict(self, job: dict, ctx: dict) -> Tuple[str, str]:
        job["sealapi"] = sealapi_verdict((job.get("company") or {}).get("intel"))
        role = (job.get("person") or {}).get("role")
        if role is None:
            cand = self._candidate(job)
            role = classify_role(cand.title if cand else "")
        job["priority"] = assign_priority(job["sealapi"]["relevance"], role)
        return "done", f"{job['sealapi']['fit_label'] or job['sealapi']['relevance']}; priority {job['priority']['label']}."
