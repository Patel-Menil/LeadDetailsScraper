"""Individual research: company discovery, professional profile, SealAPI verdict and priority (pure logic)."""
import re
from typing import Callable, Dict, List, Optional, Tuple

from .company_intel import FIT_LABELS, FREE_MAIL_DOMAINS, normalize_company_name, normalize_domain
from .individual_discovery import Candidate, IndividualInput, SearchSource
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
    fetches = 0
    for url, source in raw_candidates():
        domain = _usable_domain(url)
        if not domain or domain in tried:
            continue
        tried.append(domain)
        if fetches >= MAX_FETCHES:
            break
        fetches += 1
        target = f"https://{domain}/"
        try:
            page = fetch(target)
        except Exception:  # noqa: BLE001
            continue
        if not getattr(page, "success", False):
            continue
        ok, why = is_company_corroborated(
            name, target, getattr(page, "url", "") or target, page.title or "", page.meta_description or "",
            page.extracted_text or "",
        )
        if ok:
            return {"name": name, "domain": domain, "domain_source": source, "corroborated": True,
                    "note": why or "Website content mentions the company.", "status": "verified"}
    if tried:
        return _unknown(name, f"Could not verify a company website for {name} (tried {', '.join(tried)}).")
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
    if _has(t, r"co-?\s?founder", r"\bfounder\b", r"\bfounding\b"):
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
    if relevance == "relevant" and strong_role:
        level, reasons = 0, ["Relevant company", f"Decision-maker role ({category})"]
    elif relevance == "relevant":
        level, reasons = 1, ["Relevant company", f"Role ({category}) is not a primary decision-maker"]
    elif relevance == "needs_validation":
        level, reasons = 1, ["Company fit needs validation", f"Role: {category}"]
    elif relevance == "not_relevant" and authority == "executive":
        level, reasons = 1, ["Company fit is weak", f"Executive role ({category}) may still influence"]
    elif relevance == "not_relevant":
        level, reasons = 2, ["Company fit is weak", f"Role: {category}"]
    else:
        level, reasons = 2, ["Insufficient evidence about the company"]
    return {"level": level, "label": f"P{level}", "reasons": reasons}
