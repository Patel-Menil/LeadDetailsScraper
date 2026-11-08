"""
Live products for Individual Research.

Company products count as live only when their page loads on the company domain and offers a way to
use or buy them now (sign-up, pricing, download, app-store link, demo...). The person's own projects
count as live only when their homepage actually loads. Pages already fetched by company research are
reused; the person's project checks are capped at MAX_PROJECT_FETCHES requests through the caller's
SSRF-safe fetcher.
"""

import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from .ai_usage import TYPE_ORDER, PURPOSE_ORDER, is_ai_sentence, tag_ai_text

STATUS_LABELS = {
    "live": "Live",
    "beta": "Live (beta)",
    "not_live": "Not live",
    "discontinued": "Discontinued",
    "unknown": "Could not confirm live",
}
_REASONS = {
    "not_live": "Page says it is not available yet",
    "discontinued": "Page says it is discontinued",
    "unknown": "No sign-up, pricing, download or demo route found",
}

_LIVE = re.compile(
    r"\b(sign ?up|get started|start (?:your |a )?free trial|start for free|try (?:it )?(?:for )?free|free trial|"
    r"pricing|buy now|add to cart|download|book a demo|request a demo|get a demo|"
    r"talk to sales|contact sales|available now|now available|generally available|install)\b",
    re.I,
)
# Site-wide navigation ("Log in") or newsletters ("Subscribe"): used only when nothing stronger is found.
_WEAK_LIVE = re.compile(r"\b(log ?in|sign in|subscribe)\b", re.I)
_BETA = re.compile(r"\b(beta|early access|public preview|in preview)\b", re.I)
_NOT_LIVE = re.compile(
    r"\b(coming soon|join (?:the |our )?wait ?list|wait ?list|waiting list|launching soon|request early access|"
    r"private beta|notify me|sign up to be notified|get notified)\b",
    re.I,
)
_DISCONTINUED = re.compile(
    r"\b(discontinued|deprecated|sunset(?:ting|ted)?|end[- ]of[- ](?:life|sale)|"
    r"no longer (?:available|supported|offered|sold)|has been retired|is being retired|shut(?:ting)? down)\b",
    re.I,
)
_PRODUCT_REF = re.compile(r"\b(this|the) (product|service|app|feature|version|plan)\b", re.I)
_APP_STORES = ("apps.apple.com", "play.google.com", "chromewebstore.google.com", "chrome.google.com",
               "marketplace.visualstudio.com", "microsoft.com/store", "apps.microsoft.com")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

MAX_LIVE_PRODUCTS = 10
MAX_PROJECT_FETCHES = 6
MAX_REPO_CHECKS = 3
MAX_PROJECTS_SHOWN = 6
MAX_SITE_PROJECTS = 5
_SOCIAL_HOSTS = {"linkedin.com", "x.com", "twitter.com", "facebook.com", "instagram.com", "youtube.com",
                 "github.com", "t.co", "medium.com", "threads.net", "bsky.app", "mastodon.social", "tiktok.com"}
_INDEX_PATH = re.compile(r"^/(projects|work|portfolio|apps|products|showcase)$", re.I)
_INDEX_TEXT = {"projects", "my projects", "portfolio", "work", "my work", "apps", "products", "showcase"}


def _quote(text: str, limit: int = 200) -> str:
    s = re.sub(r"\s+", " ", text or "").strip()
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


# ---------------------------------------------------------------- liveness
def classify_liveness(page: Optional[dict], product_name: str = "") -> Dict[str, str]:
    """Live / beta / not_live / discontinued / unknown, with the quoted text that decided it."""
    if not page or not page.get("success"):
        return {"status": "unknown", "signal": "Product page could not be loaded"}
    text = f"{page.get('meta_description') or ''}\n{page.get('text') or ''}"
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    name = (product_name or "").strip().lower()

    for s in sentences:
        if _DISCONTINUED.search(s) and ((name and name in s.lower()) or _PRODUCT_REF.search(s)):
            return {"status": "discontinued", "signal": _quote(s)}
    for s in sentences:
        if _NOT_LIVE.search(s):
            return {"status": "not_live", "signal": _quote(s)}

    signal = _find_signal(page, sentences, _LIVE, app_stores=True) or _find_signal(page, sentences, _WEAK_LIVE)
    if not signal:
        return {"status": "unknown", "signal": _REASONS["unknown"]}
    beta = any(_BETA.search(s) for s in sentences)
    return {"status": "beta" if beta else "live", "signal": signal}


def _find_signal(page: dict, sentences: List[str], rx: "re.Pattern[str]", app_stores: bool = False) -> str:
    for href, link_text in _links(page):
        if app_stores and any(store in href.lower() for store in _APP_STORES):
            return f"App store link: {_quote(href, 120)}"
        if link_text and len(link_text) <= 60 and rx.search(link_text):
            return f'Link: "{_quote(link_text, 60)}"'
    return next((_quote(s) for s in sentences if rx.search(s)), "")


def _links(page: dict) -> Iterable[Tuple[str, str]]:
    for link in page.get("links") or []:
        if isinstance(link, (list, tuple)) and len(link) >= 2:
            yield str(link[0] or ""), str(link[1] or "").strip()


# ---------------------------------------------------------------- company products
def _first_sentence(page: dict) -> str:
    text = page.get("meta_description") or next(
        (s for s in _SENTENCE_SPLIT.split(page.get("text") or "") if len(s.strip()) > 20), "")
    return _quote(text, 400)


def _candidates(products: List[dict], pages: List[dict]) -> List[dict]:
    """Products found by company research, plus AI pages that are not already a product."""
    by_url = {}
    for p in pages or []:
        if isinstance(p, dict):
            by_url.setdefault(p.get("normalized_url") or p.get("url") or "", p)
            by_url.setdefault(p.get("url") or "", p)
    out: List[dict] = []
    seen_urls, seen_names = set(), set()
    for prod in products or []:
        if not isinstance(prod, dict) or not prod.get("name"):
            continue
        url = prod.get("url_normalized") or prod.get("url") or ""
        out.append({"name": prod["name"], "url": prod.get("url") or url, "page": by_url.get(url) or by_url.get(prod.get("url") or ""),
                    "source": "company_level" if prod.get("inferred") else "product_page",
                    "description": prod.get("description") or "", "features": list(prod.get("features") or [])[:6]})
        seen_urls.update({url, prod.get("url") or ""})
        seen_names.add(prod["name"].strip().lower())
    for p in pages or []:
        if not isinstance(p, dict) or p.get("category") != "ai" or not p.get("success"):
            continue
        url = p.get("normalized_url") or p.get("url") or ""
        name = _quote(((p.get("headings") or [""])[0] or p.get("title") or ""), 100)
        if not name or url in seen_urls or (p.get("url") or "") in seen_urls or name.lower() in seen_names:
            continue
        out.append({"name": name, "url": p.get("url") or url, "page": p, "source": "ai_page",
                    "description": _first_sentence(p),
                    "features": [h for h in (p.get("headings") or [])[1:] if 3 <= len(h) <= 90][:6]})
        seen_urls.add(url)
        seen_names.add(name.lower())
    return out


def product_name_map(products: List[dict], pages: List[dict]) -> Dict[str, str]:
    """Page URL -> product name, so AI sentences can be linked to the product page they came from."""
    out: Dict[str, str] = {}
    for c in _candidates(products, pages):
        page = c["page"] or {}
        for url in (c["url"], page.get("normalized_url"), page.get("url")):
            if url:
                out.setdefault(url, c["name"])
    return out


def _ordered_union(lists: Iterable[List[str]], order: List[str]) -> List[str]:
    found = {x for lst in lists for x in (lst or [])}
    return [x for x in order if x in found]


def build_company_live_products(products: List[dict], pages: List[dict], use_cases: List[dict]) -> dict:
    live: List[dict] = []
    excluded: List[dict] = []
    for c in _candidates(products, pages):
        verdict = classify_liveness(c["page"], c["name"])
        mine = [u for u in use_cases or [] if u.get("product") == c["name"]]
        item = {
            "name": c["name"], "url": c["url"], "description": c["description"], "features": c["features"],
            "source": c["source"], "status": verdict["status"], "status_label": STATUS_LABELS[verdict["status"]],
            "signal": verdict["signal"],
            "ai_types": _ordered_union((u.get("types") for u in mine), TYPE_ORDER),
            "ai_purposes": _ordered_union((u.get("purposes") for u in mine), PURPOSE_ORDER),
        }
        if verdict["status"] in ("live", "beta"):
            live.append(item)
        else:
            excluded.append({**item, "reason": _REASONS[verdict["status"]]})
    return {"live": live[:MAX_LIVE_PRODUCTS], "excluded": excluded[:MAX_LIVE_PRODUCTS]}


# ---------------------------------------------------------------- person projects
def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _is_excluded_host(host: str) -> bool:
    return not host or any(host == s or host.endswith("." + s) for s in _SOCIAL_HOSTS)


def _normalize_homepage(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        if "://" in url or url.lower().startswith(("mailto:", "javascript:")):
            return ""
        url = "https://" + url
    return url if not _is_excluded_host(_host(url)) else ""


def _repo_ai_tags(repo: dict) -> Dict[str, List[str]]:
    topics = [str(t) for t in repo.get("topics") or [] if isinstance(t, str)]
    blob = " ".join([str(repo.get("description") or "")] + [t.replace("-", " ").replace("_", " ") for t in topics])
    if not is_ai_sentence(blob) and not {"ai", "ml", "llm", "machine-learning", "agents"} & {t.lower() for t in topics}:
        return {"ai_types": [], "ai_purposes": []}
    tags = tag_ai_text(blob)
    return {"ai_types": list(tags["types"]), "ai_purposes": list(tags["purposes"])}


def build_person_projects(
    repos: List[dict],
    fetch: Callable[[str], Any],
    website: str = "",
    max_fetches: int = MAX_PROJECT_FETCHES,
    max_repo_checks: int = MAX_REPO_CHECKS,
) -> dict:
    """The person's own repos and personal-site projects, live ones first. At most max_fetches requests."""
    used = 0

    def get(url: str) -> Any:
        nonlocal used
        used += 1
        try:
            return fetch(url)
        except Exception:  # noqa: BLE001 - a failed check means "not live", never a crashed job
            return None

    def loads(res: Any) -> bool:
        return bool(res is not None and getattr(res, "success", False))

    own = [r for r in repos or [] if isinstance(r, dict) and not r.get("fork") and not r.get("archived")]
    own.sort(key=lambda r: str(r.get("pushed_at") or ""), reverse=True)
    live, code_only = [], []
    repo_checks = 0
    for r in own:
        homepage = _normalize_homepage(r.get("homepage"))
        if not homepage:
            status = "code_only"
        elif repo_checks < max_repo_checks and used < max_fetches:
            repo_checks += 1
            status = "live" if loads(get(homepage)) else "down"
        else:
            status = "not_checked"
        item = {
            "name": _quote(str(r.get("name") or ""), 100), "description": _quote(str(r.get("description") or "")),
            "language": r.get("language") or "", "topics": [str(t) for t in (r.get("topics") or [])][:6],
            "stars": int(r.get("stargazers_count") or 0), "pushed_at": str(r.get("pushed_at") or ""),
            "repo_url": str(r.get("html_url") or ""), "homepage": homepage, "status": status, **_repo_ai_tags(r),
        }
        (live if status == "live" else code_only).append(item)

    site: List[dict] = []
    if website and used < max_fetches:
        site = _site_projects(website, get, loads, lambda: max_fetches - used)
    return {"live": live[:MAX_PROJECTS_SHOWN], "code_only": code_only[:MAX_PROJECTS_SHOWN], "site": site,
            "checks_used": used}


def _site_projects(website: str, get: Callable[[str], Any], loads: Callable[[Any], bool],
                   remaining: Callable[[], int]) -> List[dict]:
    """Project sites linked from the personal site's projects page; only those that load are returned."""
    url = _normalize_homepage(website) or website
    home = get(url)
    if not loads(home):
        return []
    site_host = _host(getattr(home, "url", "") or url)
    index = next((href for href, text in _result_links(home)
                  if _host(href) == site_host and (_INDEX_PATH.match(urlparse(href).path.rstrip("/") or "/")
                                                   or text.strip().lower() in _INDEX_TEXT)), "")
    if not index or remaining() <= 0:
        return []
    page = get(index)
    if not loads(page):
        return []
    candidates: List[Tuple[str, str]] = []
    hosts = set()
    for href, text in _result_links(page):
        host = _host(href)
        if (not href.lower().startswith(("http://", "https://")) or host == site_host or _is_excluded_host(host)
                or host in hosts or not 2 <= len(text.strip()) <= 80):
            continue
        hosts.add(host)
        candidates.append((href, text.strip()))
        if len(candidates) >= MAX_SITE_PROJECTS:
            break
    out = []
    for href, text in candidates:
        if remaining() <= 0:
            break
        if loads(get(href)):
            out.append({"name": _quote(text, 80), "url": href, "status": "live"})
    return out


def _result_links(res: Any) -> Iterable[Tuple[str, str]]:
    for link in getattr(res, "links", None) or []:
        if isinstance(link, (list, tuple)) and len(link) >= 2:
            yield str(link[0] or ""), str(link[1] or "")
