"""Company & product intelligence for the companies behind imported leads.

Research reads only public pages on a company's official domain (SSRF-checked, IP-pinned fetches,
robots.txt respected, bounded retries). Every finding quotes the page it came from. Analysis is
deterministic: potential gaps are hypotheses built from documented context, never vulnerabilities,
and SealAPI value is mapped only to capabilities marked "implemented" in sealapi_capabilities.
Nothing here scans, probes or authenticates against a company's systems.
"""

import csv
import hashlib
import io
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from .identity import extract_domain
from .research import is_company_corroborated
from .scraper import DEFAULT_USER_AGENT, ScrapeResult, ScraplingScraper
from .sealapi_capabilities import (
    CAPABILITIES,
    POSITIONING,
    PROVIDER_CAVEAT,
    SCOPE_NOTE,
    SUPPORTED_AI_PROVIDERS,
    is_implemented,
)

logger = logging.getLogger("lead_research.company_intel")

SCHEMA_VERSION = "1.0.0"
RESEARCH_STATUSES = ("not_researched", "pending", "researching", "completed", "completed_with_warnings", "needs_review", "failed")
REVIEW_STATUSES = ("unreviewed", "verified", "rejected", "needs_review")
FIT_LABELS = {
    "strong": "Strong potential fit",
    "validation_required": "Potential fit — validation required",
    "weak": "Weak potential fit",
    "insufficient_evidence": "Insufficient evidence",
    "not_suitable": "Not currently suitable",
}
COMPANY_ID_RE = re.compile(r"^co_[a-z0-9_]{6,40}$")
HOSTNAME_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "aol.com",
    "icloud.com", "me.com", "proton.me", "protonmail.com", "gmx.com", "mail.com", "yandex.com", "zoho.com",
}
_LEGAL_SUFFIXES = r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|gmbh|plc|sa|ag|bv|pvt)\b"

USER_AGENT_TOKEN = "SealAPIResearchBot"
CACHE_MAX_AGE = timedelta(hours=24)
RESEARCH_FRESHNESS = timedelta(days=7)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(*parts: str, length: int = 12) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:length]


# ---------------------------------------------------------------------------------------------
# Normalization & lead association
# ---------------------------------------------------------------------------------------------

def normalize_domain(value: Optional[str]) -> str:
    """Return a bare lowercase hostname (no www, port or path) or "" when it is not a valid public name."""
    host = extract_domain(value or "").split("/")[0].strip(".")
    return host if HOSTNAME_RE.match(host) else ""


def normalize_company_name(name: Optional[str]) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", (name or "").lower())
    cleaned = re.sub(_LEGAL_SUFFIXES, " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def company_identity_from_profile(profile: Dict[str, Any]) -> Dict[str, str]:
    """Derive the company key for a lead profile: domain first (website, then work email), else name."""
    identity = profile.get("identity") or {}
    company = profile.get("company") or {}
    name = company.get("name") or identity.get("company") or ""
    candidates = [
        ("company_record", company.get("domain")),
        ("company_website", company.get("website") or identity.get("company_website")),
    ]
    email = identity.get("professional_email") or (profile.get("contact") or {}).get("email") or ""
    if "@" in email:
        email_domain = email.rsplit("@", 1)[1].lower()
        if email_domain not in FREE_MAIL_DOMAINS:
            candidates.append(("work_email", email_domain))
    for source, value in candidates:
        domain = normalize_domain(value)
        if domain:
            return {"company_id": f"co_{_hash(domain)}", "domain": domain, "domain_source": source, "name": name}
    norm = normalize_company_name(name)
    return {"company_id": f"co_name_{_hash(norm or 'unknown')}", "domain": "", "domain_source": "", "name": name}


def _normalize_url(url: str) -> str:
    """Canonical form for duplicate-source detection: no fragment, tracking query or trailing slash."""
    p = urlparse(url)
    query = "&".join(q for q in p.query.split("&") if q and not q.lower().startswith(("utm_", "ref=", "gclid")))
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower().removeprefix("www."), path, "", query, ""))


def _on_company_domain(url: str, domain: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host == domain or host.endswith("." + domain)


# ---------------------------------------------------------------------------------------------
# Research provider interface
# ---------------------------------------------------------------------------------------------

class ResearchProvider(Protocol):
    """Anything that can fetch one public page and return a ScrapeResult."""

    name: str

    def fetch(self, url: str) -> ScrapeResult: ...


class OfficialSiteProvider:
    """Default provider: direct, SSRF-checked and IP-pinned fetches of official company pages (no proxy)."""

    name = "official_site"

    def __init__(self, scraper: Optional[ScraplingScraper] = None):
        if scraper is None:
            scraper = ScraplingScraper(
                timeout=int(os.getenv("SCRAPER_TIMEOUT", "25")),
                user_agent=os.getenv("USER_AGENT") or DEFAULT_USER_AGENT,
                request_delay=float(os.getenv("COMPANY_RESEARCH_REQUEST_DELAY", "1.0")),
                use_browser=False,
                use_tor=False,
            )
            scraper.max_text_chars = 20000
        self.scraper = scraper

    def fetch(self, url: str) -> ScrapeResult:
        return self.scraper.fetch_url(url)


def fetch_with_retry(
    provider: ResearchProvider,
    url: str,
    retries: int = 2,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Tuple[ScrapeResult, int]:
    """Fetch with bounded retries and exponential backoff on transient failures. Returns (result, attempts)."""
    result = provider.fetch(url)
    attempts = 1
    while not result.success and result.status_code in RETRYABLE_STATUS and attempts <= retries:
        sleep(base_delay * (2 ** (attempts - 1)))
        result = provider.fetch(url)
        attempts += 1
    return result, attempts


# ---------------------------------------------------------------------------------------------
# Evidence extraction
# ---------------------------------------------------------------------------------------------

AI_PROVIDER_PATTERNS = [
    ("Microsoft Azure AI", r"\bazure openai\b"),
    ("OpenAI", r"\b(openai|chatgpt|gpt-4o?|gpt-3\.5|gpt-5)\b"),
    ("Anthropic", r"\b(anthropic|claude (ai|model|sonnet|opus|haiku|\d))\b"),
    ("Google Vertex AI", r"\bvertex ai\b"),
    ("Google Gemini", r"\b(google gemini|gemini (api|models?|pro|flash))\b"),
    ("Amazon Bedrock", r"\b(amazon|aws) bedrock\b"),
    ("Mistral AI", r"\bmistral( ai)?\b"),
    ("Cohere", r"\bcohere\b"),
    ("Hugging Face", r"\bhugging ?face\b"),
    ("Meta Llama (model family)", r"\bllama ?[234]?\b"),
]

SIGNALS: Dict[str, List[Tuple[str, str]]] = {
    "api": [
        ("Public API", r"\b(rest(ful)? apis?|graphql|public apis?|open apis?|api reference|api documentation|api docs|api endpoints?|our apis?|developer api)\b"),
        ("API keys / tokens", r"\b(api keys?|access tokens?|bearer tokens?|client secrets?|api credentials?)\b"),
        ("OAuth", r"\boauth ?2?(\.0)?\b"),
        ("Webhooks", r"\bwebhooks?\b"),
        ("SDKs", r"\b(sdks?|client librar(y|ies))\b"),
    ],
    "integrations": [
        ("Third-party integrations", r"\b(integrates? with|integrations? with|pre-built integrations?|native integrations?|integration marketplace|connectors?|seamless(ly)? integrat\w+)\b"),
        ("Named integrations", r"\b(salesforce|hubspot|stripe|quickbooks|netsuite|epic|cerner|athenahealth|plaid|twilio|slack|zapier|workday|shopify|xero|docusign)\b"),
    ],
    "ai": [
        ("AI / ML functionality", r"\b(artificial intelligence|machine learning|ai[- ]powered|ai[- ]driven|ai[- ]enabled|ai[- ]based|ai[- ]generated|generative ai|gen ?ai)\b"),
        ("LLM / assistant features", r"\b(llms?|large language models?|copilot|ai assistants?|chatbots?|ai agents?|agentic)\b"),
    ],
    "ai_provider": AI_PROVIDER_PATTERNS,
    "cloud": [
        ("AWS", r"\b(aws|amazon web services)\b"),
        ("Microsoft Azure", r"\bazure\b"),
        ("Google Cloud", r"\b(google cloud|gcp)\b"),
    ],
    "client_app": [
        ("Client application", r"\b(dashboard|customer portal|patient portal|member portal|mobile apps?|ios and android|web app(lication)?)\b"),
    ],
    "security_controls": [
        ("SOC 2", r"\bsoc ?2\b"),
        ("ISO 27001", r"\biso[ /-]?27001\b"),
        ("HIPAA", r"\bhipaa\b"),
        ("PCI DSS", r"\b(pci[- ]?dss|pci compliant)\b"),
        ("GDPR", r"\bgdpr\b"),
        ("Encryption", r"\b(encrypt(ed|ion)? (at rest|in transit)|aes[- ]?256|tls ?1\.[23])\b"),
        ("SSO / MFA", r"\b(sso|single sign-on|saml|multi-factor|mfa|two-factor|2fa)\b"),
        ("Role-based access", r"\b(rbac|role-based access)\b"),
        ("Vulnerability disclosure", r"\b(bug bounty|vulnerability disclosure|responsible disclosure|penetration test(ing|s)?)\b"),
    ],
    "sensitive_data": [
        ("Health data (PHI)", r"\b(phi|protected health information|patient (data|records?|information)|ehr|emr|electronic health records?)\b"),
        ("Payment / financial data", r"\b(payment (data|processing|information)|cardholder data|bank accounts?|ach (payments?|transfers?)|financial data)\b"),
        ("Personal data", r"\b(pii|personally identifiable information|personal (data|information))\b"),
    ],
    "hiring": [
        ("Security hiring", r"\b(security engineer|appsec|application security engineer|devsecops)\b"),
        ("Platform / API hiring", r"\b(platform engineer|backend engineer|api engineer|site reliability engineer)\b"),
        ("AI / ML hiring", r"\b(ml engineer|machine learning engineer|ai engineer|data scientist)\b"),
    ],
}
_COMPILED = {cat: [(label, re.compile(rx, re.I)) for label, rx in items] for cat, items in SIGNALS.items()}
# A provider or product name alone is a mention, not evidence of use ("ChatGPT landed..."): require usage wording.
_REQUIRED_CONTEXT = {
    ("ai_provider", None): re.compile(
        r"\b(powered by|built (on|with)|uses?|using|leverag\w+|integrat\w+|via|runs? on|on top of|partner\w* with|connect\w*|api|models?)\b", re.I),
    ("integrations", "Named integrations"): re.compile(r"\b(integrat\w+|connect\w*|sync\w*|plug-?ins?|works with|marketplace)\b", re.I),
}
_NEGATION = re.compile(r"\b(not|no longer|isn't|aren't|doesn't|does not|do not|never|without)\b", re.I)

PAGE_CATEGORIES = [
    ("products", r"/(products?|platform|solutions?|features?|modules?)(/|$)"),
    ("developer", r"(developers?|/docs?(/|$)|/api(/|$)|api-reference|/reference|/sdks?)"),
    ("integrations", r"(integrations?|marketplace|connectors?|partners?)"),
    ("security", r"(security|trust|compliance|privacy|hipaa|soc-?2)"),
    ("ai", r"(/ai(/|$|-)|artificial-intelligence|machine-learning|llm|copilot|assistant|/agents?)"),
    ("careers", r"(careers?|jobs|join-us|hiring)"),
    ("news", r"(/blog|/news|/press|/engineering|announcement|changelog)"),
    ("about", r"(/about|/company(/|$)|who-we-are)"),
]
CATEGORY_BUDGET = {"products": 4, "developer": 2, "integrations": 1, "security": 2, "ai": 2, "careers": 1, "news": 1, "about": 1}
FALLBACK_PATHS = {"security": ["/security", "/trust"], "developer": ["/developers", "/docs"]}
_GENERIC_LINK_TEXT = {
    "products", "product", "all products", "overview", "learn more", "platform", "solutions", "features",
    "read more", "see all", "explore", "home", "get started", "more", "view all", "book a demo", "contact",
}
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if 20 <= len(s.strip()) <= 600]


def _snippet(sentence: str, limit: int = 280) -> str:
    sentence = re.sub(r"\s+", " ", sentence).strip()
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rsplit(" ", 1)[0] + "…"


def categorize_page(url: str, link_text: str = "") -> Optional[str]:
    path = urlparse(url).path.lower()
    host = (urlparse(url).hostname or "").lower()
    if host.startswith(("docs.", "developer.", "developers.", "api.")):
        return "developer"
    haystack = f"{path} /{link_text.lower().replace(' ', '-')}"
    for category, rx in PAGE_CATEGORIES:
        if re.search(rx, haystack):
            return category
    return None


def extract_findings(
    page: Dict[str, Any],
    company_id: str,
    product_id: Optional[str],
    confidence_scale: float,
) -> List[Dict[str, Any]]:
    """Pull quoted, categorized evidence sentences from one fetched page."""
    findings: List[Dict[str, Any]] = []
    title_meta = f"{page.get('title', '')} {page.get('meta_description', '')}"
    sentences = _sentences(f"{page.get('meta_description', '')}\n{page.get('text', '')}")
    for category, patterns in _COMPILED.items():
        for label, rx in patterns:
            context = _REQUIRED_CONTEXT.get((category, None)) or _REQUIRED_CONTEXT.get((category, label))
            sentence = next((s for s in sentences if rx.search(s) and (context is None or context.search(s))
                             # "X is not a covered entity under HIPAA" is not evidence of a control
                             and not (category == "security_controls" and _NEGATION.search(s))), None)
            if not sentence:
                continue
            base = 0.8 if rx.search(title_meta) else 0.7
            if category == "ai_provider":
                base = 0.8
            evidence = _snippet(sentence)
            findings.append({
                "finding_id": f"f_{_hash(company_id, category, label, page['normalized_url'])}",
                "company_id": company_id,
                "product_id": product_id,
                "category": category,
                "label": label,
                "title": f"{label} — {page.get('title') or page['source_domain']}"[:160],
                "description": evidence,
                "evidence": evidence,
                "source_id": page["source_id"],
                "source_url": page["url"],
                "source_domain": page["source_domain"],
                "publication_date": page.get("published_at") or None,
                "accessed_at": page["accessed_at"],
                "confidence": round(base * confidence_scale, 2),
                "verification_status": "unreviewed",
                "review_note": "",
                "origin": "official_site_text",
                "stale": False,
            })
    return findings


# ---------------------------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------------------------

class CompanyStore:
    """Atomic JSON storage: one record per company, a page cache, and a lead -> company index."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.cache_dir = self.base_dir / "page_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_dir / "lead_index.json"
        self._lock = threading.RLock()

    @staticmethod
    def validate_id(company_id: str) -> str:
        if not company_id or not COMPANY_ID_RE.match(company_id):
            raise ValueError("Invalid company id")
        return company_id

    def _write(self, path: Path, data: Any) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _read(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"Unreadable company store file {path.name}: {exc}")
            return default

    def load(self, company_id: str) -> Optional[Dict[str, Any]]:
        return self._read(self.base_dir / f"{self.validate_id(company_id)}.json", None)

    def save(self, record: Dict[str, Any]) -> None:
        with self._lock:
            record["updated_at"] = _now()
            self._write(self.base_dir / f"{self.validate_id(record['company_id'])}.json", record)

    def list_all(self) -> List[Dict[str, Any]]:
        return [r for p in sorted(self.base_dir.glob("co_*.json")) if (r := self._read(p, None))]

    def lead_company_id(self, lead_id: str) -> Optional[str]:
        return self._read(self.index_path, {}).get(lead_id)

    def index_leads(self, lead_ids: List[str], company_id: str) -> None:
        with self._lock:
            index = self._read(self.index_path, {})
            index.update({lid: company_id for lid in lead_ids})
            self._write(self.index_path, index)

    def cache_get(self, company_id: str, url: str, max_age: timedelta = CACHE_MAX_AGE) -> Optional[Dict[str, Any]]:
        entry = self._read(self.cache_dir / f"{company_id}.json", {}).get(_normalize_url(url))
        if not entry:
            return None
        if datetime.fromisoformat(entry["accessed_at"]) < datetime.now(timezone.utc) - max_age:
            return None
        return entry

    def cache_put(self, company_id: str, page: Dict[str, Any]) -> None:
        with self._lock:
            path = self.cache_dir / f"{company_id}.json"
            cache = self._read(path, {})
            cache[page["normalized_url"]] = page
            self._write(path, cache)


def new_company_record(ident: Dict[str, str], profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    snap = (profile or {}).get("input_snapshot") or {}
    identity = (profile or {}).get("identity") or {}
    hq = ", ".join(v for v in [snap.get("Company City"), snap.get("Company State"), snap.get("Company Country")] if v)
    return {
        "schema_version": SCHEMA_VERSION,
        "company_id": ident["company_id"],
        "canonical_name": ident.get("name") or ident.get("domain") or "Unknown company",
        "normalized_domain": ident.get("domain", ""),
        "domain_source": ident.get("domain_source", ""),
        "official_website": f"https://{ident['domain']}" if ident.get("domain") else "",
        # Input-provided context (from the lead CSV), shown as such - not web-verified.
        "input_context": {
            "industry": identity.get("industry") or "",
            "headquarters": hq,
            "employee_range": str(snap.get("Employees") or ""),
        },
        "research_status": "not_researched" if ident.get("domain") else "needs_review",
        "research_provider": OfficialSiteProvider.name,
        "research_warnings": [] if ident.get("domain") else [
            "No company domain could be derived from the lead; set the official domain to research this company."
        ],
        "errors": [],
        "last_researched_at": None,
        "identity_corroborated": None,
        "corroboration_note": "",
        "overview": {},
        "pages": [],
        "findings": [],
        "products": [],
        "gaps": [],
        "opportunities": [],
        "company_fit": None,
        "discovery_questions": [],
        "limitations": [],
        "lead_refs": [],
        "progress": {"stage": "not_started", "pages_done": 0, "pages_planned": 0},
        "created_at": _now(),
    }


def add_lead_ref(record: Dict[str, Any], batch_id: str, profile: Dict[str, Any]) -> None:
    identity = profile.get("identity") or {}
    ref = {
        "lead_id": profile.get("lead_id"),
        "batch_id": batch_id,
        "name": identity.get("name", ""),
        "job_title": identity.get("job_title", ""),
    }
    record["lead_refs"] = [r for r in record.get("lead_refs", []) if r.get("lead_id") != ref["lead_id"]] + [ref]


# ---------------------------------------------------------------------------------------------
# Research engine
# ---------------------------------------------------------------------------------------------

class CompanyResearcher:
    """Researches one company's official site and stores findings, products and analysis."""

    def __init__(
        self,
        store: CompanyStore,
        provider: Optional[ResearchProvider] = None,
        max_pages: Optional[int] = None,
        max_products: Optional[int] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.store = store
        self._provider = provider
        self.max_pages = max_pages or int(os.getenv("COMPANY_RESEARCH_MAX_PAGES", "14"))
        self.max_products = max_products or int(os.getenv("COMPANY_RESEARCH_MAX_PRODUCTS", "4"))
        self.sleep = sleep

    @property
    def provider(self) -> ResearchProvider:
        if self._provider is None:
            self._provider = OfficialSiteProvider()
        return self._provider

    # -- page handling ---------------------------------------------------------------------

    def _page_from_result(self, url: str, res: ScrapeResult, domain: str) -> Dict[str, Any]:
        final = res.url or url
        return {
            "source_id": f"csrc_{_hash(_normalize_url(final), length=10)}",
            "url": final,
            "requested_url": url,
            "normalized_url": _normalize_url(final),
            "source_domain": (urlparse(final).hostname or domain).lower(),
            "status_code": res.status_code,
            "success": res.success,
            "error": res.error,
            "title": res.title,
            "meta_description": res.meta_description,
            "headings": res.headings,
            "text": res.extracted_text,
            "links": [list(link) for link in res.links if _on_company_domain(link[0], domain)][:300],
            "published_at": res.published_at,
            "site_name": res.site_name,
            "og_image": res.og_image,
            "accessed_at": _now(),
            "content_hash": _hash(res.extracted_text or "", length=16),
        }

    def _get_page(self, record: Dict[str, Any], url: str, robots: Optional[RobotFileParser], use_cache: bool) -> Dict[str, Any]:
        cid, domain = record["company_id"], record["normalized_domain"]
        if robots is not None and not robots.can_fetch(USER_AGENT_TOKEN, url):
            return {"url": url, "normalized_url": _normalize_url(url), "success": False, "status_code": 0,
                    "error": "Disallowed by robots.txt", "skipped": True, "accessed_at": _now()}
        if use_cache:
            cached = self.store.cache_get(cid, url)
            if cached and cached.get("success"):
                return {**cached, "from_cache": True}
        res, attempts = fetch_with_retry(self.provider, url, sleep=self.sleep)
        page = self._page_from_result(url, res, domain)
        page["attempts"] = attempts
        if page["success"] and not _on_company_domain(page["url"], domain):
            page.update(success=False, error=f"Redirected off the company domain to {page['source_domain']}")
        if page["success"]:
            self.store.cache_put(cid, page)
        return page

    def _robots(self, record: Dict[str, Any]) -> Tuple[Optional[RobotFileParser], str]:
        """Returns (parser or None, note). 4xx means no restrictions; 5xx/network errors are treated as disallow-all."""
        url = f"https://{record['normalized_domain']}/robots.txt"
        res, _ = fetch_with_retry(self.provider, url, sleep=self.sleep)
        parser = RobotFileParser()
        if res.success:
            parser.parse((res.extracted_text or "").splitlines())
            return parser, "robots.txt honoured"
        if 400 <= res.status_code < 500 and res.status_code != 429:
            parser.parse([])
            return parser, f"robots.txt not found (HTTP {res.status_code}); no restrictions"
        parser.parse(["User-agent: *", "Disallow: /"])
        return parser, f"robots.txt unreachable ({res.error or res.status_code}); treated as disallow-all"

    def _plan_pages(self, homepage: Dict[str, Any], domain: str) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """Pick category pages and product candidates from homepage links. Returns (pages, product_links)."""
        by_cat: Dict[str, List[str]] = {c: [] for c in CATEGORY_BUDGET}
        product_links: List[Tuple[str, str]] = []
        seen = {homepage["normalized_url"]}
        for href, text in homepage.get("links", []):
            if not href.startswith(("http://", "https://")) or not _on_company_domain(href, domain):
                continue
            norm = _normalize_url(href)
            if norm in seen or re.search(r"\.(pdf|png|jpe?g|svg|zip|mp4)$", norm):
                continue
            seen.add(norm)
            category = categorize_page(href, text)
            if not category:
                continue
            path_parts = [p for p in urlparse(href).path.split("/") if p]
            clean_text = re.sub(r"\s+", " ", text or "").strip()
            if (category == "products" and len(path_parts) >= 2 and clean_text
                    and clean_text.lower() not in _GENERIC_LINK_TEXT and len(clean_text.split()) <= 6):
                product_links.append((href, clean_text))
            elif len(by_cat[category]) < CATEGORY_BUDGET[category]:
                by_cat[category].append(href)
        probes = []
        for category, paths in FALLBACK_PATHS.items():
            if not by_cat[category]:
                probes += [(f"https://{domain}{p}", category) for p in paths]
        pages = [(url, cat) for cat, urls in by_cat.items() for url in urls] + probes
        return pages, product_links

    # -- main entry ------------------------------------------------------------------------

    def research(self, record: Dict[str, Any], refresh: bool = False) -> Dict[str, Any]:
        """Run research for one company record (mutates and saves it). Never raises for site failures."""
        domain = record.get("normalized_domain")
        if not domain:
            record["research_status"] = "needs_review"
            record["progress"] = {"stage": "blocked_no_domain", "pages_done": 0, "pages_planned": 0}
            self.store.save(record)
            return record

        previous_reviews = {f["finding_id"]: f for f in record.get("findings", [])}
        record.update(research_status="researching", errors=[], research_warnings=[], research_started_at=_now())
        record["progress"] = {"stage": "robots", "pages_done": 0, "pages_planned": 0}
        self.store.save(record)

        try:
            self._run(record, use_cache=not refresh)
        except Exception as exc:  # unexpected engine failure: persist what we have, report failed
            logger.error(f"Company research crashed for {record['company_id']}: {exc}", exc_info=True)
            record["errors"].append(f"Research engine error: {exc}")
            record["research_status"] = "failed"

        self._merge_reviews(record, previous_reviews)
        analyze_company(record)
        record["last_researched_at"] = _now()
        record["progress"]["stage"] = "done"
        self.store.save(record)
        return record

    def _run(self, record: Dict[str, Any], use_cache: bool) -> None:
        domain, cid = record["normalized_domain"], record["company_id"]
        robots, robots_note = self._robots(record)
        record["robots_note"] = robots_note

        home = self._get_page(record, f"https://{domain}/", robots, use_cache)
        pages: List[Dict[str, Any]] = [home]
        record["progress"] = {"stage": "homepage", "pages_done": 1, "pages_planned": 1}
        if not home.get("success"):
            record["pages"] = [_page_summary(home, "homepage")]
            record["errors"].append(f"Official homepage could not be fetched: {home.get('error') or home.get('status_code')}")
            record["research_status"] = "failed"
            return

        corroborated, note = is_company_corroborated(
            record["canonical_name"], f"https://{domain}/", home["url"], home.get("title", ""),
            home.get("meta_description", ""), home.get("text", ""),
        )
        record["identity_corroborated"], record["corroboration_note"] = corroborated, note
        scale = 1.0 if corroborated else 0.6

        planned, product_links = self._plan_pages(home, domain)
        product_links = product_links[: self.max_products]
        budget = max(0, self.max_pages - 1 - len(product_links))
        planned = planned[:budget]
        record["progress"] = {"stage": "pages", "pages_done": 1, "pages_planned": 1 + len(planned) + len(product_links)}
        self.store.save(record)

        categories = {home["normalized_url"]: "homepage"}
        product_pages: List[Tuple[Dict[str, Any], str]] = []
        content_seen = {home.get("content_hash")}
        for url, category in planned + [(u, "product") for u, _ in product_links]:
            page = self._get_page(record, url, robots, use_cache)
            if page.get("success") and page.get("content_hash") in content_seen:
                page.update(success=False, error="Duplicate content of an already-fetched page", duplicate=True)
            content_seen.add(page.get("content_hash"))
            categories[page["normalized_url"]] = category
            pages.append(page)
            if category == "product" and page.get("success"):
                name = next((t for u, t in product_links if _normalize_url(u) == _normalize_url(url)), "")
                product_pages.append((page, name))
            record["progress"]["pages_done"] += 1
            record["pages"] = [_page_summary(p, categories.get(p["normalized_url"], "")) for p in pages]
            self.store.save(record)  # partial-result persistence

        ok_pages = [p for p in pages if p.get("success")]
        if not product_pages:
            # No /products/<name> links: a fetched top-level product/platform page is the documented offering.
            overview_page = next((p for p in ok_pages if categories.get(p["normalized_url"]) == "products"), None)
            if overview_page:
                segment = urlparse(overview_page["url"]).path.strip("/").split("/")[-1].replace("-", " ")
                product_pages = [(overview_page, f"{record['canonical_name']} {segment.title()}".strip())]
        products = _build_products(record, home, product_pages, ok_pages)
        findings: List[Dict[str, Any]] = []
        product_by_url = {p["url_normalized"]: p["product_id"] for p in products if not p["inferred"]}
        for page in ok_pages:
            findings.extend(extract_findings(page, cid, product_by_url.get(page["normalized_url"]), scale))
        record["findings"] = _dedupe_findings(findings)
        record["products"] = products
        record["overview"] = _build_overview(record, home, ok_pages)

        probe_urls = {_normalize_url(u) for cat, paths in FALLBACK_PATHS.items() for u in (f"https://{domain}{p}" for p in paths)}
        for p in pages:  # a missing well-known path (e.g. /docs) is an absence, not a fetch failure
            if not p.get("success") and p.get("status_code") in (404, 410) and _normalize_url(p.get("requested_url") or p["url"]) in probe_urls:
                p["probe_absent"] = True
        record["pages"] = [_page_summary(p, categories.get(p["normalized_url"], "")) for p in pages]
        failed = [p for p in pages[1:] if not p.get("success") and not p.get("duplicate") and not p.get("probe_absent")]
        warnings = []
        if not corroborated:
            warnings.append(f"Company identity not corroborated on the fetched site: {note}")
        if failed:
            warnings.append(f"{len(failed)} of {len(pages) - 1} additional pages could not be fetched or were skipped.")
        if len(ok_pages) < 3:
            warnings.append("Fewer than three official pages were available; findings are thin.")
        record["research_warnings"] = warnings
        record["research_status"] = (
            "needs_review" if not corroborated else "completed_with_warnings" if warnings else "completed"
        )

    @staticmethod
    def _merge_reviews(record: Dict[str, Any], previous: Dict[str, Dict[str, Any]]) -> None:
        """Keep manual review decisions across refreshes; retain reviewed findings that disappeared as stale."""
        current = {f["finding_id"]: f for f in record.get("findings", [])}
        for fid, old in previous.items():
            if old.get("verification_status", "unreviewed") == "unreviewed":
                continue
            if fid in current:
                current[fid]["verification_status"] = old["verification_status"]
                current[fid]["review_note"] = old.get("review_note", "")
            else:
                record["findings"].append({**old, "stale": True})


def _page_summary(page: Dict[str, Any], category: str) -> Dict[str, Any]:
    return {k: page.get(k) for k in (
        "source_id", "url", "source_domain", "title", "status_code", "success", "error",
        "published_at", "accessed_at", "from_cache", "attempts", "probe_absent",
    )} | {"category": category}


def _dedupe_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for f in findings:
        key = (f["category"], f["label"], f["evidence"].lower())
        if key not in seen:
            seen[key] = f
    return list(seen.values())


def _build_products(
    record: Dict[str, Any],
    home: Dict[str, Any],
    product_pages: List[Tuple[Dict[str, Any], str]],
    ok_pages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    products = []
    for page, link_name in product_pages:
        cta = r"^(learn more about|learn more|explore|discover|meet|see|about)\s+"
        name = re.sub(cta, "", link_name or "", flags=re.I) or (page.get("headings") or [page.get("title") or ""])[0]
        features = [h for h in page.get("headings", [])[1:] if 3 <= len(h) <= 90][:8]
        products.append(_product(record, name, page, features, inferred=False))
    if not products:
        # No distinct product pages: analyse the company-level offering, clearly labelled as such.
        products.append(_product(
            record, f"{record['canonical_name']} (company-level offering)", home,
            [h for h in home.get("headings", []) if 3 <= len(h) <= 90][:8], inferred=True,
        ))
    return products


def _product(record: Dict[str, Any], name: str, page: Dict[str, Any], features: List[str], inferred: bool) -> Dict[str, Any]:
    description = page.get("meta_description") or next(iter(_sentences(page.get("text", ""))), "")
    return {
        "product_id": f"p_{_hash(record['company_id'], page['normalized_url'])}",
        "company_id": record["company_id"],
        "name": re.sub(r"\s+", " ", name).strip()[:100] or "Unnamed product",
        "url": page["url"],
        "url_normalized": page["normalized_url"],
        "source_id": page["source_id"],
        "inferred": inferred,
        "description": _snippet(description, 400),
        "features": features,
        "documented_limitations": [],
        "research_status": "completed",
    }


def _build_overview(record: Dict[str, Any], home: Dict[str, Any], ok_pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    text = " ".join(p.get("text", "")[:6000] for p in ok_pages)
    customers = next((
        _snippet(s, 220) for s in _sentences(text)
        if re.search(r"\b(for|helps?|serving|trusted by|built for)\b.{0,80}\b(teams|companies|businesses|enterprises|banks|insurers|carriers|agencies|hospitals|clinics|providers|health systems|practices|lenders|merchants|developers|organizations)\b", s, re.I)
    ), "")
    models = []
    if re.search(r"\b(saas|software[- ]as[- ]a[- ]service)\b", text, re.I):
        models.append("SaaS (stated on site)")
    if re.search(r"\b(consulting|outsourc\w+|staff augmentation|development services|custom software development)\b", text, re.I):
        models.append("Services / custom development (stated on site)")
    return {
        "official_name": home.get("site_name") or record["canonical_name"],
        "logo_url": home.get("og_image") if _on_company_domain(home.get("og_image") or "", record["normalized_domain"]) else "",
        "description": home.get("meta_description") or "",
        "description_source_id": home.get("source_id"),
        "homepage_title": home.get("title", ""),
        "business_model": models or ["Not determined from public sources"],
        "customer_segments": customers,
        "pages_fetched": len(ok_pages),
    }


# ---------------------------------------------------------------------------------------------
# Analysis: architecture, gaps, SealAPI mapping, fit, scoring, questions
# ---------------------------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    "api_evidence": 15, "integration_evidence": 10, "ai_evidence": 25,
    "problem_relevance": 20, "capability_compatibility": 20, "evidence_quality": 10,
}
MAX_UNCERTAINTY_PENALTY = 10


def scoring_weights() -> Dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    raw = os.getenv("COMPANY_FIT_WEIGHTS", "").strip()
    if raw:
        try:
            weights.update({k: float(v) for k, v in json.loads(raw).items() if k in DEFAULT_WEIGHTS})
        except (ValueError, AttributeError):
            logger.warning("Ignoring invalid COMPANY_FIT_WEIGHTS (expected a JSON object of numbers).")
    return weights


def _usable(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [f for f in findings if f.get("verification_status") != "rejected"]


def _by(findings: List[Dict[str, Any]], category: str, label: Optional[str] = None) -> List[Dict[str, Any]]:
    return [f for f in findings if f["category"] == category and (label is None or f["label"] == label)]


def _product_findings(record: Dict[str, Any], product: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A product's own page findings plus company-level findings (scoped so in the UI)."""
    usable = _usable(record.get("findings", []))
    own = [f for f in usable if f.get("product_id") == product["product_id"]]
    company_level = [f for f in usable if not f.get("product_id")]
    return own + company_level


def _ids(findings: List[Dict[str, Any]]) -> List[str]:
    return list(dict.fromkeys(f["finding_id"] for f in findings))


def _mean_conf(findings: List[Dict[str, Any]]) -> float:
    return round(sum(f["confidence"] for f in findings) / len(findings), 2) if findings else 0.0


def build_architecture(product: Dict[str, Any], findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    components: List[Dict[str, Any]] = []
    flows: List[Dict[str, Any]] = []

    def component(cid: str, name: str, responsibility: str, evidence: List[Dict[str, Any]], documented: bool,
                  controls: Optional[List[str]] = None, unknowns: Optional[List[str]] = None, relevance: str = "") -> None:
        components.append({
            "id": cid, "name": name, "responsibility": responsibility, "documented": documented,
            "evidence_ids": _ids(evidence), "source_urls": list(dict.fromkeys(f["source_url"] for f in evidence)),
            "confidence": _mean_conf(evidence) if documented else 0.3,
            "known_controls": controls or [], "unknowns": unknowns or [], "sealapi_relevance": relevance,
        })

    client = _by(findings, "client_app")
    api = [f for f in _by(findings, "api") if f["label"] in ("Public API", "API keys / tokens", "OAuth")]
    hooks, sdks = _by(findings, "api", "Webhooks"), _by(findings, "api", "SDKs")
    integ, ai, providers = _by(findings, "integrations"), _by(findings, "ai"), _by(findings, "ai_provider")
    cloud, idp = _by(findings, "cloud"), [f for f in _by(findings, "security_controls", "SSO / MFA")] + _by(findings, "api", "OAuth")
    controls = sorted({f["label"] for f in _by(findings, "security_controls")})

    if client:
        component("client", "Client applications", "Customer-facing dashboard, portal or app", client, True)
    if api:
        component("public_api", "Public / developer API", "Programmatic access for customers or partners", api, True,
                  controls=[c for c in controls if c in ("SSO / MFA", "Role-based access")],
                  unknowns=["Credential scoping, rotation and per-key monitoring are not publicly documented"],
                  relevance="Outside SealAPI scope (SealAPI does not front a company's own APIs)")
    if hooks:
        component("webhooks", "Webhooks", "Outbound event notifications to customer endpoints", hooks, True,
                  unknowns=["Webhook signing and secret handling not documented"])
    if sdks:
        component("sdks", "SDKs / client libraries", "Client-side integration tooling", sdks, True)
    if integ:
        named = sorted({m.group(0).title() for f in integ for m in [re.search(_COMPILED["integrations"][1][1].pattern, f["evidence"], re.I)] if m})
        component("integrations", "Third-party integrations" + (f" ({', '.join(named[:5])})" if named else ""),
                  "Data exchange with external services", integ, True,
                  unknowns=["How integration credentials are stored, scoped and rotated"],
                  relevance="Outside SealAPI scope unless the integration is an AI provider")
    if ai:
        component("ai_features", "AI / LLM features", "AI-driven product functionality", ai, True,
                  unknowns=["Which model provider is called and from which service"],
                  relevance="In scope: application-to-AI traffic")
    if providers:
        for f in {f["label"]: f for f in providers}.values():
            component(f"ai_provider_{_hash(f['label'], length=6)}", f"External model provider: {f['label']}",
                      "Model inference", [f], True,
                      unknowns=["Where the provider credential is stored and how it is scoped"],
                      relevance="In scope: provider credential shielding and pre-dispatch policy")
    elif ai:
        component("ai_provider_unknown", "Model provider (not publicly documented)", "Model inference (inferred)", [], False,
                  unknowns=["Provider, hosting model (external API vs self-hosted) and credential handling"],
                  relevance="Potentially in scope if an external provider API is used")
    if cloud:
        component("cloud", "Cloud infrastructure: " + ", ".join(sorted({f["label"] for f in cloud})), "Hosting", cloud, True)
    if idp:
        component("identity", "Identity & access (SSO / OAuth)", "User and client authentication", idp, True)
    if len(components) >= 2:
        component("backend", "Product backend services", "Business logic connecting the components (inferred)", [], False,
                  unknowns=["Service boundaries and service-to-service authorization"])

    ids = {c["id"] for c in components}

    def flow(src: str, dst: str, data: str, documented: bool, boundary: bool) -> None:
        if src in ids and dst in ids:
            flows.append({"from": src, "to": dst, "data": data, "documented": documented, "crosses_trust_boundary": boundary})

    flow("client", "backend", "user requests and product data", False, True)
    flow("public_api", "backend", "API requests authenticated with customer credentials", bool(api), True)
    flow("backend", "webhooks", "event payloads to customer endpoints", bool(hooks), True)
    flow("backend", "integrations", "records exchanged using integration credentials", False, True)
    flow("backend", "ai_features", "product data used by AI features", False, False)
    for c in components:
        if c["id"].startswith("ai_provider"):
            flow("ai_features", c["id"], "prompts/context plus a provider API credential", False, True)

    documented = sum(1 for c in components if c["documented"])
    return {
        "status": "documented" if documented >= 3 else "partial" if documented else "insufficient",
        "components": components,
        "flows": flows,
        "trust_boundaries": [f for f in flows if f["crosses_trust_boundary"]],
        "unknowns": sorted({u for c in components for u in c["unknowns"]}),
        "limitation": "" if documented >= 3 else
            "Public documentation does not describe this product's architecture in enough detail; components marked inferred are assumptions to validate.",
    }


def _existing_controls(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    controls = {}
    for f in _by(findings, "security_controls"):
        controls.setdefault(f["label"], {"control": f["label"], "finding_id": f["finding_id"], "source_url": f["source_url"]})
    return list(controls.values())


def build_gaps(record: Dict[str, Any], product: Dict[str, Any], findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Potential gaps only. Missing documentation is never treated as a missing control."""
    ai, providers = _by(findings, "ai"), _by(findings, "ai_provider")
    sensitive = _by(findings, "sensitive_data")
    integrations = _by(findings, "integrations")
    api = [f for f in _by(findings, "api") if f["label"] in ("Public API", "API keys / tokens")]
    agents = [f for f in ai if re.search(r"\bagent", f["evidence"], re.I)]
    controls = _existing_controls(findings)
    provider_names = sorted({f["label"] for f in providers})
    provider_text = " and ".join(provider_names) or "external model providers"
    pname = record["canonical_name"] if product.get("inferred") else product["name"]
    gaps: List[Dict[str, Any]] = []

    def gap(kind: str, feature: str, title: str, context: str, evidence: List[Dict[str, Any]], scenario: str,
            consequence: str, unverified: List[str], info: List[str], question: str, capability_ids: List[str]) -> None:
        conf = min(0.8, round(0.35 + 0.1 * len(_ids(evidence)), 2)) * (1.0 if record.get("identity_corroborated") else 0.75)
        gaps.append({
            "gap_id": f"g_{_hash(product['product_id'], kind)}",
            "kind": kind,
            "product_id": product["product_id"],
            "product_name": pname,
            "feature": feature,
            "title": title,
            "technical_context": context,
            "evidence_ids": _ids(evidence),
            "exposure_scenario": scenario,
            "possible_consequence": consequence,
            "existing_controls": controls,
            "unverified_controls": unverified,
            "confidence": round(conf, 2),
            "information_needed": info,
            "discovery_question": question,
            "capability_ids": capability_ids,
            "classification": "potential_risk",
            "verified_vulnerability": False,
        })

    if ai:
        gap("ai_provider_credentials", "AI features",
            f"Model-provider credential handling for {pname}'s AI features",
            f"Public pages describe AI functionality{' and name ' + ', '.join(provider_names) if provider_names else ''}.",
            ai + providers,
            f"If the API credential the backend uses to call {provider_text} were exposed (configuration, logs, a compromised service), it could be used to send requests under the company's account.",
            "Unplanned model spend, data sent outside normal controls, and an urgent key rotation.",
            ["Where provider credentials are stored", "Whether keys are scoped per service and rotated", "Whether provider calls pass a central policy point"],
            ["Which model providers are called and from which services", "Current secrets-management approach for provider keys"],
            f"How are the credentials your backend uses to call {provider_text} stored, scoped and rotated?",
            ["provider_credential_isolation", "scoped_api_keys", "key_misuse_circuit_breaker"])
    if ai and sensitive:
        kinds = ", ".join(sorted({f["label"] for f in sensitive}))
        gap("ai_sensitive_data_flow", "AI features handling sensitive data",
            f"Sensitive data reaching AI endpoints in {pname}",
            f"Public pages describe AI functionality and handling of {kinds}.",
            ai + sensitive,
            f"Prompts or context built from {kinds.lower()} may be sent to a model provider; the controls applied before data leaves the trust boundary are not publicly documented.",
            "Regulatory exposure and loss of customer trust if sensitive records leave approved boundaries.",
            ["Data minimisation before model calls", "Where AI requests are policy-checked before dispatch"],
            ["Which data categories are included in prompts", "Whether a pre-dispatch policy check exists"],
            "Where are policy checks applied before AI requests that include sensitive records leave your environment?",
            ["sealed_payloads", "pre_dispatch_security_gate"])
    if ai:
        caps = ["scoped_api_keys", "rate_limiting", "pre_dispatch_security_gate"] + (["mcp_tool_policy"] if agents else [])
        gap("ai_access_policy", "AI endpoint access",
            f"Access-policy enforcement for {pname}'s AI endpoints" + (" and agent tools" if agents else ""),
            "AI functionality is documented" + ("; agentic features are mentioned" if agents else "") + ".",
            ai,
            "Without per-service limits on which models (or agent tools) can be called, a misbehaving or compromised service could use AI capacity far beyond its purpose.",
            "Cost overruns and actions taken by AI workflows outside their intended scope.",
            ["Per-service model/tool permissions", "Rate limits on AI calls", "Runtime policy decisions per request"],
            ["How services authenticate to AI endpoints", "Whether agents can invoke tools and with which permissions"],
            "How do you limit which services can call which models" + (" or agent tools" if agents else "") + ", and at what volume?",
            caps)
    if integrations:
        gap("integration_credentials", "Third-party integrations",
            f"Integration credential scope for {pname}",
            "Public pages document third-party integrations.",
            integrations,
            "Integration tokens with broad scopes could expose connected systems if one integration or service were compromised.",
            "Access to customer data in connected systems beyond the integration's purpose.",
            ["Token scoping and rotation for integrations"],
            ["Which integrations hold long-lived credentials"],
            "How are credentials used by third-party integrations scoped and protected?",
            [])
    if api:
        gap("public_api_access", "Public API",
            f"Customer API credential scoping and misuse detection for {pname}",
            "Public pages document an API with keys or tokens.",
            api,
            "A leaked customer API key could be used until it is noticed and revoked.",
            "Unauthorized data access through the product's API.",
            ["Key scoping, rotation and anomaly detection for customer API keys"],
            ["How customer API keys are issued and monitored"],
            "What controls limit the impact of a compromised customer API key?",
            [])
    return gaps


_INTEGRATION_POINTS = {
    "ai_provider_credentials": "Between the product backend and {providers}: point the backend's model client at the SealAPI gateway (provider base URL plus a SealAPI key) and store the provider key as a wrapped BYOK credential in SealAPI instead of application configuration.",
    "ai_sensitive_data_flow": "On the request path from the backend to the model provider: requests are sealed with the SealAPI SDK and must receive the gateway's pre-dispatch Allow decision before dispatch.",
    "ai_access_policy": "At the SealAPI gateway: one SealAPI key per calling service with a model allowlist and rate limit{mcp}.",
}
_COMPLEXITY = {
    "ai_provider_credentials": ("medium", "Assumes the backend calls a supported provider through an HTTP client whose base URL can be changed."),
    "ai_sensitive_data_flow": ("high", "Assumes the calling services can adopt the SealAPI SDK (Python, TypeScript or Go) for sealing."),
    "ai_access_policy": ("low", "Assumes AI calls already pass through SealAPI (see credential shielding)."),
}


def build_opportunities(record: Dict[str, Any], product: Dict[str, Any], gaps: List[Dict[str, Any]],
                        findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    provider_names = sorted({f["label"] for f in _by(findings, "ai_provider")})
    supported_named = [p for p in provider_names if p in SUPPORTED_AI_PROVIDERS]
    opps = []
    for g in gaps:
        caps = [c for c in g["capability_ids"] if is_implemented(c)]
        if not caps:
            compatibility = {
                "status": "not_supported",
                "detail": CAPABILITIES["general_api_gateway"]["description"],
            }
        elif g["kind"] == "ai_provider_credentials" and supported_named:
            compatibility = {"status": "compatible_pending_validation",
                             "detail": f"Documented provider(s) {', '.join(supported_named)} have SealAPI adapters. {PROVIDER_CAVEAT}"}
        elif provider_names and not supported_named:
            compatibility = {"status": "requires_validation",
                             "detail": f"Documented provider(s) {', '.join(provider_names)} have no locally verified SealAPI adapter."}
        else:
            compatibility = {"status": "requires_validation",
                             "detail": "The model provider and integration path are not publicly documented; compatibility cannot be assessed yet."}
        contribution = "; ".join(CAPABILITIES[c]["contribution"] for c in caps) if caps else \
            "Not currently supported by SealAPI's verified capabilities."
        point = _INTEGRATION_POINTS.get(g["kind"], "").format(
            providers=", ".join(provider_names) or "the model provider",
            mcp=" and MCP tool policies for agent tool calls" if "mcp_tool_policy" in caps else "",
        ) if caps else "None — use case not currently supported."
        complexity, assumption = _COMPLEXITY.get(g["kind"], ("n/a", ""))
        opps.append({
            "opportunity_id": f"o_{_hash(g['gap_id'])}",
            "company_id": record["company_id"],
            "product_id": product["product_id"],
            "product_name": product["name"],
            "lead_id": None,
            "gap_id": g["gap_id"],
            "feature": g["feature"],
            "trust_boundary": "Product backend ↔ external model provider" if g["kind"].startswith("ai_") else g["feature"],
            "security_requirement": g["title"],
            "problem_hypothesis": g["exposure_scenario"],
            "why_it_matters": g["possible_consequence"],
            "proposed_contribution": contribution,
            "integration_point": point,
            "expected_benefit": _benefit(g["kind"]) if caps else "",
            "dependencies": ["Architecture validation with the prospect", "Supported provider / SDK"] if caps else [],
            "compatibility": compatibility,
            "complexity": {"estimate": complexity if caps else "n/a", "assumptions": assumption if caps else ""},
            "operational_tradeoffs": "Adds a network hop and a dependency on gateway availability; the gateway fails closed when a security decision is unavailable." if caps else "",
            "capability_ids": caps,
            "supporting_finding_ids": g["evidence_ids"],
            "confidence": g["confidence"] if caps else round(g["confidence"] * 0.5, 2),
            "discovery_question": g["discovery_question"],
            "verification_status": "unreviewed",
            "scope_note": SCOPE_NOTE,
        })
    return opps


def _benefit(kind: str) -> str:
    return {
        "ai_provider_credentials": "Provider keys leave application config; each service uses a revocable SealAPI key that can be paused automatically on anomalous use.",
        "ai_sensitive_data_flow": "AI requests stay sealed to the gateway and cannot be dispatched without a policy decision.",
        "ai_access_policy": "Each service is limited to approved models and request volumes, enforced per request.",
    }.get(kind, "")


def classify_fit(record: Dict[str, Any], product: Dict[str, Any], findings: List[Dict[str, Any]],
                 opps: List[Dict[str, Any]], architecture: Dict[str, Any]) -> Dict[str, Any]:
    ok_pages = sum(1 for p in record.get("pages", []) if p.get("success"))
    supported = [o for o in opps if o["compatibility"]["status"] != "not_supported"]
    compatible = [o for o in supported if o["compatibility"]["status"] == "compatible_pending_validation"]
    ai = _by(findings, "ai")
    has_api = bool(_by(findings, "api") or _by(findings, "integrations"))
    concerns = sorted({o["compatibility"]["detail"] for o in supported})

    if record.get("research_status") == "failed" or ok_pages < 2:
        key, role = "insufficient_evidence", "Undetermined"
        reason = "Research could not collect enough official pages to assess need or compatibility."
    elif compatible and len(ai) >= 2:
        key, role = "strong", "Complementary security layer / enforcement point on documented application-to-AI traffic"
        reason = (f"{len(ai)} official-site findings document AI functionality and a provider with a SealAPI adapter is named. "
                  "Architecture details still need validation before any integration claim.")
    elif supported:
        key, role = "validation_required", "Solution requiring additional architecture validation"
        reason = ("AI functionality is documented, so application-to-AI traffic is plausibly in scope, "
                  "but the model provider and call path are not publicly documented.")
    elif has_api:
        key, role = "weak", "Unsuitable addition based on current evidence"
        reason = ("Public evidence shows APIs/integrations but no AI functionality. SealAPI's verified capabilities "
                  "cover application-to-AI-provider traffic, not a company's own APIs or non-AI integrations.")
    elif ok_pages >= 4:
        key, role = "not_suitable", "Unsuitable addition"
        reason = "No documented API, integration or AI surface within SealAPI's verified scope was found."
    else:
        key, role = "insufficient_evidence", "Undetermined"
        reason = "Too little technical information was published to assess need."
    models = (record.get("overview") or {}).get("business_model") or []
    if key in ("strong", "validation_required") and any(m.startswith("Services") for m in models) and not any(m.startswith("SaaS") for m in models):
        reason += (" The company describes itself as a services / custom-development provider, so any need would come from "
                   "specific client projects or its own AI delivery tooling rather than a product it operates.")
    if record.get("identity_corroborated") is False and key in ("strong", "validation_required"):
        key, role = "validation_required", "Solution requiring additional architecture validation"
        reason += " The fetched site's identity was not corroborated, so findings need manual review."
    return {
        "classification": key,
        "label": FIT_LABELS[key],
        "role": role,
        "reasoning": reason,
        "supporting_finding_ids": _ids(ai + _by(findings, "ai_provider"))[:10],
        "existing_controls_compared": [c["control"] for c in _existing_controls(findings)],
        "compatibility_concerns": concerns,
        "scope_note": SCOPE_NOTE,
        "architecture_status": architecture["status"],
    }


def score_product(findings: List[Dict[str, Any]], opps: List[Dict[str, Any]], architecture: Dict[str, Any],
                  weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    weights = weights or scoring_weights()
    supported = [o for o in opps if o["compatibility"]["status"] != "not_supported"]
    n_api, n_int = len(_by(findings, "api")), len(_by(findings, "integrations"))
    n_ai, n_prov = len(_by(findings, "ai")), len(_by(findings, "ai_provider"))
    statuses = {o["compatibility"]["status"] for o in supported}
    used = _by(findings, "api") + _by(findings, "integrations") + _by(findings, "ai") + _by(findings, "ai_provider")
    factors = {
        "api_evidence": (min(1.0, n_api / 3), f"{n_api} API-related findings"),
        "integration_evidence": (min(1.0, n_int / 2), f"{n_int} integration findings"),
        "ai_evidence": (1.0 if n_prov else min(1.0, n_ai / 3), f"{n_ai} AI findings, {n_prov} named model providers"),
        "problem_relevance": (max((o["confidence"] for o in supported), default=0.0), f"{len(supported)} in-scope potential problems"),
        "capability_compatibility": (1.0 if "compatible_pending_validation" in statuses else 0.5 if statuses else 0.0,
                                     "supported provider documented" if "compatible_pending_validation" in statuses
                                     else "in scope, provider unknown" if statuses else "no supported SealAPI capability applies"),
        "evidence_quality": (_mean_conf(used), "mean confidence of supporting findings"),
    }
    penalty = {"documented": 0, "partial": MAX_UNCERTAINTY_PENALTY / 2}.get(architecture["status"], MAX_UNCERTAINTY_PENALTY)
    total = sum(weights[k] * v for k, (v, _) in factors.items()) - penalty
    return {
        "total": round(max(0.0, min(100.0, total)), 1),
        "factors": [{"factor": k, "value": round(v, 2), "weight": weights[k], "points": round(weights[k] * v, 1), "explanation": e}
                    for k, (v, e) in factors.items()],
        "uncertainty_penalty": penalty,
        "weights": weights,
        "note": "Industry is deliberately not a factor; a score reflects documented relevance, not proof of a vulnerability.",
    }


def analyze_company(record: Dict[str, Any]) -> Dict[str, Any]:
    """(Re)build architecture, gaps, opportunities, fit and scores from stored findings. Rejected findings are ignored."""
    all_gaps, all_opps = [], []
    for product in record.get("products", []):
        findings = _product_findings(record, product)
        architecture = build_architecture(product, findings)
        gaps = build_gaps(record, product, findings)
        opps = build_opportunities(record, product, gaps, findings)
        product.update(
            finding_ids=_ids([f for f in findings if f.get("product_id") == product["product_id"]]),
            category=_product_category(findings),
            architecture=architecture,
            fit=classify_fit(record, product, findings, opps, architecture),
            score=score_product(findings, opps, architecture),
            api_details=[f["evidence"] for f in _by(findings, "api")][:4],
            ai_details=[f["evidence"] for f in _by(findings, "ai") + _by(findings, "ai_provider")][:4],
            integration_details=[f["evidence"] for f in _by(findings, "integrations")][:4],
        )
        all_gaps.extend(gaps)
        all_opps.extend(opps)
    record["products"].sort(key=lambda p: p.get("score", {}).get("total", 0), reverse=True)
    for rank, product in enumerate(record["products"], 1):
        product["rank"] = rank
    record["gaps"], record["opportunities"] = all_gaps, all_opps
    record["company_fit"] = record["products"][0]["fit"] if record["products"] else {
        "classification": "insufficient_evidence", "label": FIT_LABELS["insufficient_evidence"], "role": "Undetermined",
        "reasoning": "No products or company pages could be analysed.", "supporting_finding_ids": [],
        "existing_controls_compared": [], "compatibility_concerns": [], "scope_note": SCOPE_NOTE, "architecture_status": "insufficient",
    }
    record["discovery_questions"] = list(dict.fromkeys(
        g["discovery_question"] for g in sorted(all_gaps, key=lambda g: (not g["capability_ids"], -g["confidence"]))
    ))
    record["limitations"] = _limitations(record)
    record["analysis_updated_at"] = _now()
    return record


def _product_category(findings: List[Dict[str, Any]]) -> str:
    if _by(findings, "ai"):
        return "AI-enabled software product"
    if _by(findings, "api"):
        return "API / developer-facing software product"
    return "Software product or service (category not documented)"


def _limitations(record: Dict[str, Any]) -> List[str]:
    out = [
        "Findings are sentences quoted from the company's official site; they are unreviewed until marked verified.",
        "Missing public documentation is not evidence that a control is absent.",
        "No scanning, probing or authenticated access was performed.",
    ]
    if record.get("identity_corroborated") is False:
        out.append("The fetched website could not be corroborated as this company's; review before use.")
    if not _by(_usable(record.get("findings", [])), "ai_provider"):
        out.append("No model provider is named in public sources.")
    if record.get("input_context", {}).get("headquarters") or record.get("input_context", {}).get("employee_range"):
        out.append("Headquarters and employee range come from the imported lead file, not from web research.")
    return out


def _role_order(job_title: str) -> List[str]:
    """In-scope gap kinds in the order most relevant to a prospect's role."""
    title = (job_title or "").lower()
    if re.search(r"\b(ciso|security|risk|compliance)\b", title):
        return ["ai_sensitive_data_flow", "ai_provider_credentials", "ai_access_policy"]
    if re.search(r"\b(cto|engineer|architect|platform|devops|technology|developer)\b", title):
        return ["ai_provider_credentials", "ai_access_policy", "ai_sensitive_data_flow"]
    return ["ai_access_policy", "ai_provider_credentials", "ai_sensitive_data_flow"]


def role_questions(record: Dict[str, Any], job_title: str) -> List[str]:
    """Pick research-based questions suited to the prospect's role (at most three)."""
    gaps = sorted(record.get("gaps", []), key=lambda g: (not g["capability_ids"], -g["confidence"]))
    if not gaps:
        return []
    order = _role_order(job_title)
    ranked = sorted(gaps, key=lambda g: order.index(g["kind"]) if g["kind"] in order else len(order))
    return list(dict.fromkeys(g["discovery_question"] for g in ranked))[:3]


# ---------------------------------------------------------------------------------------------
# Outreach
# ---------------------------------------------------------------------------------------------

BANNED_OUTREACH_PATTERNS = [
    (r"\bvulnerab", "claims a vulnerability"),
    (r"\bbreach(ed|es)?\b|\bhacked\b|\bcompromised\b", "implies an incident"),
    (r"\bguarantee", "guarantees an outcome"),
    (r"\b100 ?%|\bbulletproof\b|\bprevent(s)? all\b|\bunhackable\b", "absolute security claim"),
    (r"\b(tee|enclave|attest\w*|hardware)\b", "partial capability (hardware TEE) not yet verified"),
    (r"\b(soc ?2|iso ?27001|hipaa[- ]compliant|certified)\b", "unverified certification claim"),
    (r"\bcustomers? (like|including)\b|\btrusted by\b", "unverified customer claim"),
    (r"\b(urgent|alarming|act now)\b", "fear-based language"),
    (r"\b(pii redaction|prompt[- ]injection)\b", "unsupported capability"),
]
SIGNATURE = "Best regards,\n[Your Name]\nBAVRIX — SealAPI"


def check_outreach_claims(text: str) -> List[str]:
    return [reason for rx, reason in BANNED_OUTREACH_PATTERNS if re.search(rx, text, re.I)]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text.replace(SIGNATURE, "")))


def _short_quote(evidence: str, max_words: int = 22) -> str:
    words = evidence.strip().strip('"').split()
    quote = " ".join(words[:max_words]).rstrip(",;:")
    return quote + ("…" if len(words) > max_words else "")


_PROBLEMS = {
    "ai_provider_credentials": (
        "When a product calls {providers} directly, the provider key often sits in backend configuration, shared by every service that needs AI. Whoever obtains it can run requests under your account.",
        "That tends to surface as unexpected spend, data leaving through a channel nobody is watching, and a rushed key rotation across services.",
    ),
    "ai_sensitive_data_flow": (
        "Once AI features work with {sensitive}, the hard question becomes where requests are checked before they leave for the model provider.",
        "Without a consistent checkpoint, sensitive records can reach an external service outside the controls the rest of the platform relies on.",
    ),
    "ai_access_policy": (
        "As AI features spread across services, it gets hard to say which service may call which model, and how much.",
        "A single misbehaving or misused service can then consume AI capacity, or trigger actions, well beyond its purpose.",
    ),
}
_SENSITIVE_PHRASES = {
    "Health data (PHI)": "health records",
    "Payment / financial data": "payment and financial data",
    "Personal data": "personal data",
}


def _display_product(opp: Dict[str, Any], record: Dict[str, Any], company: str) -> str:
    """Name used in prose: the product, or the company when only the company-level offering was analysed."""
    product = next((p for p in record.get("products", []) if p["product_id"] == opp["product_id"]), None)
    return company if (product is None or product.get("inferred")) else opp["product_name"]


_INTRO = (
    POSITIONING + " In practice, {how}."
)
_HOW = {
    "ai_provider_credentials": "provider keys stay wrapped inside the SealAPI gateway rather than in application config, each service gets its own scoped key, and a key showing anomalous use can be paused automatically",
    "ai_sensitive_data_flow": "requests are sealed between your services and the gateway, and nothing is sent to the provider without a policy decision",
    "ai_access_policy": "each calling service gets its own key with a model allowlist and rate limit, enforced on every request",
}


def generate_outreach(record: Dict[str, Any], lead: Dict[str, Any]) -> Dict[str, Any]:
    """Two drafts (evidence-led, problem-led) from the strongest supported opportunity, or a conservative draft."""
    first = lead.get("first_name") or (lead.get("name") or "there").split()[0]
    company = record.get("overview", {}).get("official_name") or record.get("canonical_name") or "your team"
    findings = {f["finding_id"]: f for f in _usable(record.get("findings", []))}
    candidates = [
        o for o in record.get("opportunities", [])
        if o["compatibility"]["status"] != "not_supported" and o["capability_ids"]
    ]
    order = _role_order(lead.get("job_title", ""))
    kind_of = {g["gap_id"]: g["kind"] for g in record.get("gaps", [])}
    # Supported provider first, then the problem most relevant to the prospect's role; its own question keeps the email coherent.
    candidates.sort(key=lambda o: (o["compatibility"]["status"] != "compatible_pending_validation",
                                   order.index(kind_of[o["gap_id"]]) if kind_of.get(o["gap_id"]) in order else len(order),
                                   -o["confidence"]))
    questions = role_questions(record, lead.get("job_title", ""))
    fit = (record.get("company_fit") or {}).get("classification", "insufficient_evidence")

    if not candidates:
        body = (
            f"Hi {first},\n\n"
            f"I don't know how {company} handles this internally, so I'll keep this short. Many teams adding AI to their "
            "products end up with model-provider keys copied into several services, with little control over which service "
            "calls which model.\n\n"
            f"{POSITIONING} If external AI services are part of {company}'s roadmap, it may be worth comparing notes on how "
            "those credentials and calls are governed.\n\n"
            "Are external AI services part of your product today, and if so, how are their credentials managed?\n\n"
            f"{SIGNATURE}"
        )
        return _outreach_result([_variant("conservative", "Conservative problem-led", f"AI credentials at {company}", body, [], None)],
                                fit, questions, "Research did not establish an in-scope SealAPI opportunity; a conservative draft is provided.")

    opp = candidates[0]
    support = [findings[i] for i in opp["supporting_finding_ids"] if i in findings]
    support.sort(key=lambda f: (f.get("verification_status") != "verified", f["category"] != "ai", -f["confidence"]))
    obs = support[0] if support else None
    kind = next(g["kind"] for g in record["gaps"] if g["gap_id"] == opp["gap_id"])
    providers = sorted({f["label"] for f in findings.values() if f["category"] == "ai_provider"})
    sensitive = sorted({_SENSITIVE_PHRASES.get(f["label"], "sensitive data") for f in findings.values() if f["category"] == "sensitive_data"})
    problem, consequence = (p.format(providers=" and ".join(providers) or "an external model provider",
                                     sensitive=" and ".join(sensitive) or "sensitive data") for p in _PROBLEMS[kind])
    intro = _INTRO.format(how=_HOW[kind])
    question = opp["discovery_question"]
    product = _display_product(opp, record, company)
    subject = f"{product}: AI calls and the credentials behind them"
    variants = []
    if obs:
        body_a = (
            f"Hi {first},\n\n"
            f"I was reading {obs['source_domain']}, which describes {product} this way: \"{_short_quote(obs['evidence'])}\"\n\n"
            f"{problem} {consequence}\n\n"
            f"{intro}\n\n{question}\n\n{SIGNATURE}"
        )
        variants.append(_variant("A", "Evidence-led", subject, body_a, [obs["finding_id"]], obs))
    body_b = (
        f"Hi {first},\n\n"
        f"{problem} {consequence}\n\n"
        f"Since {company}'s site describes AI functionality in {product}, I wondered how this is handled on your side.\n\n"
        f"{intro}\n\n{question}\n\n{SIGNATURE}"
    )
    variants.append(_variant("B", "Problem-led", subject, body_b, [f["finding_id"] for f in support[:2]], obs))
    note = "" if fit in ("strong", "validation_required") else "Fit is not strong; review whether outreach is appropriate."
    return _outreach_result(variants, fit, questions, note, opp)


def _variant(vid: str, label: str, subject: str, body: str, finding_ids: List[str], obs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "variant_id": vid,
        "label": label,
        "subject": subject,
        "body": body,
        "word_count": _word_count(body),
        "supporting_finding_ids": finding_ids,
        "observation_source_url": obs["source_url"] if obs else None,
        "requires_review": bool(obs and obs.get("verification_status") != "verified"),
        "guardrail_violations": check_outreach_claims(body.replace(POSITIONING, "")),
    }


def _outreach_result(variants: List[Dict[str, Any]], fit: str, questions: List[str], note: str,
                     opp: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "generated_at": _now(),
        "fit_classification": fit,
        "opportunity_id": opp["opportunity_id"] if opp else None,
        "capabilities_referenced": opp["capability_ids"] if opp else [],
        "discovery_questions": questions,
        "note": note,
        "variants": variants,
        "auto_send": False,
    }


# ---------------------------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------------------------

EXPORT_COLUMNS = [
    "company_id", "company_name", "company_domain", "official_website", "industry", "company_description",
    "research_status", "last_researched_at", "lead_ids", "product_rank", "product_name", "product_url",
    "product_description", "api_evidence", "ai_evidence", "integration_evidence", "security_context",
    "potential_security_gaps", "sealapi_use_cases", "fit_classification", "product_score", "confidence",
    "supporting_source_urls",
]


def export_rows(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for r in records:
        findings = {f["finding_id"]: f for f in _usable(r.get("findings", []))}
        controls = sorted({f["label"] for f in findings.values() if f["category"] == "security_controls"})
        base = {
            "company_id": r["company_id"],
            "company_name": r.get("overview", {}).get("official_name") or r.get("canonical_name"),
            "company_domain": r.get("normalized_domain"),
            "official_website": r.get("official_website"),
            "industry": r.get("input_context", {}).get("industry"),
            "company_description": r.get("overview", {}).get("description", ""),
            "research_status": r.get("research_status"),
            "last_researched_at": r.get("last_researched_at"),
            "lead_ids": ";".join(x["lead_id"] for x in r.get("lead_refs", []) if x.get("lead_id")),
            "security_context": "; ".join(controls),
        }
        for p in r.get("products") or [{}]:
            gaps = [g for g in r.get("gaps", []) if g.get("product_id") == p.get("product_id")]
            opps = [o for o in r.get("opportunities", []) if o.get("product_id") == p.get("product_id")
                    and o["compatibility"]["status"] != "not_supported"]
            urls = {findings[i]["source_url"] for g in gaps for i in g["evidence_ids"] if i in findings}
            rows.append({**base,
                "product_rank": p.get("rank", ""),
                "product_name": p.get("name", ""),
                "product_url": p.get("url", ""),
                "product_description": p.get("description", ""),
                "api_evidence": " | ".join(p.get("api_details", [])),
                "ai_evidence": " | ".join(p.get("ai_details", [])),
                "integration_evidence": " | ".join(p.get("integration_details", [])),
                "potential_security_gaps": " | ".join(f"{g['title']} (potential, not verified)" for g in gaps),
                "sealapi_use_cases": " | ".join(f"{o['proposed_contribution']} [{o['compatibility']['status']}]" for o in opps),
                "fit_classification": (p.get("fit") or {}).get("label", ""),
                "product_score": (p.get("score") or {}).get("total", ""),
                "confidence": max((g["confidence"] for g in gaps), default=""),
                "supporting_source_urls": " ".join(sorted(urls)),
            })
    return rows


def export_csv(records: List[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(export_rows(records))
    return buf.getvalue()


def export_json(records: List[Dict[str, Any]], batch_id: str) -> Dict[str, Any]:
    keep = ("company_id", "canonical_name", "normalized_domain", "official_website", "input_context", "research_status",
            "research_warnings", "errors", "last_researched_at", "identity_corroborated", "overview", "products",
            "findings", "gaps", "opportunities", "company_fit", "discovery_questions", "limitations", "pages")
    return {
        "batch_id": batch_id,
        "generated_at": _now(),
        "schema_version": SCHEMA_VERSION,
        "companies": [{k: r.get(k) for k in keep} for r in records],
        "lead_company_associations": [
            {"lead_id": ref["lead_id"], "company_id": r["company_id"], "batch_id": ref.get("batch_id")}
            for r in records for ref in r.get("lead_refs", [])
        ],
    }


# ---------------------------------------------------------------------------------------------
# Job coordination (prevents duplicate concurrent research)
# ---------------------------------------------------------------------------------------------

class ResearchJobs:
    """In-process registry so repeated clicks or concurrent requests never start a second job for a company."""

    def __init__(self):
        self._lock = threading.Lock()
        self._running: Dict[str, str] = {}

    def try_start(self, company_id: str) -> bool:
        with self._lock:
            if company_id in self._running:
                return False
            self._running[company_id] = _now()
            return True

    def finish(self, company_id: str) -> None:
        with self._lock:
            self._running.pop(company_id, None)

    def is_running(self, company_id: str) -> bool:
        with self._lock:
            return company_id in self._running


def is_fresh(record: Dict[str, Any]) -> bool:
    ts = record.get("last_researched_at")
    if not ts or record.get("research_status") in ("failed", "not_researched", "pending", "needs_review"):
        return False
    return datetime.fromisoformat(ts) > datetime.now(timezone.utc) - RESEARCH_FRESHNESS
