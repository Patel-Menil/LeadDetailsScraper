"""Individual research: parse raw discovery hits into identity candidates and decide whether one is clear."""
import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Protocol, Tuple
from urllib.parse import urlparse

import httpx

from .company_intel import normalize_company_name, normalize_domain
from .identity import extract_domain, names_compatible
from .scraper import ScrapeResult, ScraplingScraper, decode_ddg_url

AUTO_SELECT_MIN = 0.75
AUTO_SELECT_MARGIN = 0.25
CANDIDATE_MIN = 0.35
MAX_TEXT = 300
MAX_FIELD = 120
MAX_QUERIES = 5
MAX_GITHUB_LOOKUPS = 3  # /users/{login} calls per search; the unauthenticated core API allows 60 requests/hour

_GITHUB_RESERVED = {
    "orgs", "topics", "search", "features", "pricing", "about", "login", "join", "explore", "marketplace",
    "sponsors", "settings", "notifications", "collections", "events", "trending", "enterprise", "site", "apps",
}
_TITLE_SPLIT = re.compile(r"\s+[-–—|]\s+")
_END = r"(?:[^,;|·•\n.]|\.(?=\S))+"
_ROLE_VERB = re.compile(r"\b(?:is|as|was)\s+(?:an?\s+|the\s+)?(?P<role>[^,.;|·•\n]+?)\s+at\s+(?P<co>" + _END + ")", re.I)
_ROLE_BARE = re.compile(r"(?:^|[·|•]\s*)(?P<role>[A-Z][\w&/ ]*?)\s+at\s+(?P<co>" + _END + ")")
_SENIORITY = r"(?:(?:senior|sr\.?|staff|principal|lead|founding)\s+)?"
_BIO_ROLE = re.compile(
    r"\b(?:"
    r"(?:co-?)?founder(?:\s*(?:&|and|/|,)\s*(?:ceo|cto|cpo|coo))?"
    r"|chief(?:\s+[a-z&]+){1,3}?\s+officer"
    r"|ceo|cto|ciso|coo|cpo|cfo"
    r"|(?:vp|vice president|head|director)(?:\s+of)?(?:\s+(?!at\b)[a-z&/-]{2,}){1,2}"
    r"|" + _SENIORITY + r"(?:(?!(?:a|an|the|and|i|im|i'm)\s)[a-z+#/-]{2,}\s+)?engineer"
    r")\b",
    re.I,
)
SEARCH_EMPTY_MSG = ("Web search returned no results for any query (DuckDuckGo may be blocking or throttling automated "
                    "requests); results come from GitHub and supplied URLs only.")
GITHUB_RATE_LIMIT_MSG = "GitHub API rate limit reached"
_STOPWORDS = {
    "a", "an", "and", "the", "of", "in", "on", "at", "for", "to", "with", "by", "from", "or", "as", "is", "was", "are",
    "be", "who", "that", "this", "he", "she", "they", "his", "her", "their", "works", "worked", "working", "met",
    "maybe", "possibly", "probably", "about", "some", "something", "someone", "person", "think", "know", "known",
}
# Hosting platforms whose subdomains belong to different owners, and two-part country suffixes.
_HOSTED_SUFFIXES = ("vercel.app", "netlify.app", "github.io", "herokuapp.com", "pages.dev", "web.app",
                    "firebaseapp.com", "azurewebsites.net", "wordpress.com", "blogspot.com")
_MULTI_SUFFIXES = ("co.uk", "org.uk", "ac.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp", "co.in", "com.br",
                   "com.cn", "co.za", "com.sg", "com.mx", "co.kr", "com.tr", "co.il")
_NOT_TLDS = {"js", "ts", "py", "rb", "rs"}  # "Next.js" is a product name, not a domain


@dataclass
class IndividualInput:
    name: str
    company: str = ""
    linkedin_url: str = ""
    x_url: str = ""
    github_url: str = ""
    website: str = ""
    location: str = ""
    context: str = ""


@dataclass
class Observation:
    source_id: str
    source_type: str  # search | github | website
    url: str
    name: str
    title: str = ""
    company: str = ""
    location: str = ""
    avatar_url: str = ""
    snippet: str = ""
    linkedin_slug: str = ""
    github_login: str = ""
    website: str = ""
    query: str = ""
    company_domain: str = ""  # domain from a GitHub company field such as "https://vercel.com"


@dataclass
class Candidate:
    candidate_id: str
    name: str
    title: str
    company: str
    location: str
    avatar_url: str
    profile_url: str
    description: str
    linkedin_slug: str
    github_login: str
    website: str
    observations: List[Observation]
    confidence: float = 0.0
    confidence_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class IdentityDecision:
    mode: str  # auto | select | low_confidence
    selected_id: str
    candidates: List[Candidate]
    message: str


def _trunc(text: str, n: int = MAX_TEXT) -> str:
    return (text or "").strip()[:n]


def _sha(text: str, n: int) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def registrable_label(domain: str) -> str:
    """The label just left of the public suffix: vercel.com, blog.vercel.com, vercel.app -> "vercel"."""
    d = normalize_domain(domain)
    parts = d.split(".")
    if len(parts) < 2:
        return d
    for suffix in _HOSTED_SUFFIXES + _MULTI_SUFFIXES:
        if d.endswith("." + suffix):
            return parts[-len(suffix.split(".")) - 1]
    return parts[-2]


def context_tokens(context: str, min_len: int = 2) -> List[str]:
    """Distinct non-stopword tokens of the free-text context hint, in order."""
    out: List[str] = []
    for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9+#.-]*[A-Za-z0-9+#]|[A-Za-z0-9]", context or ""):
        low = t.lower()
        if len(t) >= min_len and low not in _STOPWORDS and low not in {o.lower() for o in out}:
            out.append(t)
    return out


def build_discovery_queries(inp: IndividualInput) -> List[str]:
    name = inp.name.strip()
    queries = [f'"{name}"', f'"{name}" linkedin', f'"{name}" (CEO OR CTO OR founder OR engineer)']
    if inp.company.strip():
        queries.append(f'"{name}" "{inp.company.strip()}"')
    if inp.location.strip():
        queries.append(f'"{name}" {inp.location.strip()}')
    ctx = context_tokens(inp.context)[:3]
    if ctx:
        queries.append(f'"{name}" {" ".join(ctx)}')
    queries += [f'"{name}" github', f'"{name}" twitter OR x.com']
    out: List[str] = []
    for q in queries:
        if q not in out:
            out.append(q)
    return out[:MAX_QUERIES]


def parse_linkedin_title(title: str) -> Tuple[str, str, str]:
    t = re.sub(r"\s*[|\-–—]\s*LinkedIn\s*$", "", (title or "").strip(), flags=re.I)
    parts = [p.strip() for p in _TITLE_SPLIT.split(t) if p.strip()]
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        # "Name - CEO at Vercel | LinkedIn": the middle part is "<role> at <company>"
        role, sep, company = parts[1].partition(" at ")
        if sep and role.strip() and company.strip():
            return parts[0], role.strip(), company.strip()
        return parts[0], "", parts[1]
    return parts[0], parts[1], " - ".join(parts[2:])


def parse_role_at_company(text: str) -> Tuple[str, str]:
    text = (text or "")[:MAX_TEXT]
    for rx in (_ROLE_VERB, _ROLE_BARE):
        m = rx.search(text)
        if m:
            return _trunc(m.group("role"), MAX_FIELD), _trunc(m.group("co"), MAX_FIELD)
    return "", ""


def linkedin_slug(url: str) -> str:
    try:
        p = urlparse(url if "//" in url else f"https://{url}")
    except ValueError:
        return ""
    host = p.netloc.lower()
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return ""
    m = re.match(r"^/(?:in|pub)/([^/?#]+)", p.path)
    return m.group(1).lower() if m else ""


def github_login_from_url(url: str) -> str:
    if extract_domain(url) != "github.com":
        return ""
    try:
        p = urlparse(url if "//" in url else f"https://{url}")
    except ValueError:
        return ""
    seg = [s for s in p.path.split("/") if s]
    if not seg or seg[0].lower() in _GITHUB_RESERVED:
        return ""
    return seg[0].lower()


def _full_name_in(text: str, name: str) -> bool:
    return bool(name.strip()) and bool(re.search(r"(?<!\w)" + re.escape(name.strip()) + r"(?!\w)", text or "", re.I))


def parse_search_hit(hit: Dict[str, str], name: str, query: str) -> Optional[Observation]:
    title = (hit.get("title") or "").strip()
    url = (hit.get("url") or "").strip()
    snippet = (hit.get("snippet") or "").strip()
    if not url:
        return None
    slug = linkedin_slug(url)
    login = github_login_from_url(url)
    role = company = location = ""
    if slug:
        parsed_name, role, company = parse_linkedin_title(title)
    elif login:
        m = re.search(r"\(([^)]+)\)", title)
        parsed_name = m.group(1).strip() if m else ""
    else:
        parsed_name = _TITLE_SPLIT.split(title)[0].strip()
    if parsed_name and names_compatible(name, parsed_name)[0]:
        final_name = parsed_name
    elif _full_name_in(title, name):
        final_name = name.strip()
    else:
        return None
    role, company = _trunc(role, MAX_FIELD), _trunc(company, MAX_FIELD)
    if not (role and company):
        r2, c2 = parse_role_at_company(snippet)
        role, company = role or r2, company or c2
    if slug and "·" in snippet:
        first = snippet.split("·")[0].strip()
        if first and " at " not in first and len(first) < 60:
            location = first
    return Observation(
        source_id=f"search:{_sha(url, 10)}", source_type="search", url=url, name=_trunc(final_name, MAX_FIELD), title=role,
        company=company, location=_trunc(location, MAX_FIELD), snippet=_trunc(snippet), linkedin_slug=slug, github_login=login,
        query=query,
    )


def parse_github_company(raw: str) -> Tuple[str, str]:
    """GitHub's free-text company field -> (company name, company domain).

    "https://vercel.com" / "vercel.com" -> ("Vercel", "vercel.com"); "@vercel @nextjs" -> ("vercel", "");
    "@Acme AI" -> ("Acme AI", "").
    """
    raw = (raw or "").strip()
    if not raw:
        return "", ""
    if " " not in raw:
        explicit = bool(re.match(r"^(?:https?://|www\.)", raw, re.I))
        looks_like = explicit or bool(re.match(r"^[\w-]+(?:\.[\w-]+)+(?:/\S*)?$", raw))
        domain = normalize_domain(raw) if looks_like else ""
        if domain and (explicit or domain.rsplit(".", 1)[-1] not in _NOT_TLDS):
            label = registrable_label(domain)
            return label[:1].upper() + label[1:], domain
    orgs = re.findall(r"@([\w.-]+)", raw)
    if len(orgs) >= 2:
        return orgs[0], ""
    return raw.lstrip("@").strip(), ""


def title_from_bio(bio: str) -> str:
    """A short role phrase from a GitHub bio ("@vercel CEO" -> "CEO"), or ""."""
    m = _BIO_ROLE.search((bio or "")[:MAX_TEXT])
    return _trunc(re.sub(r"\s+", " ", m.group(0)), MAX_FIELD) if m else ""


def github_user_to_observation(user: dict) -> Optional[Observation]:
    name = (user.get("name") or "").strip()
    login = (user.get("login") or "").strip()
    if not name and not login:
        return None
    company, company_domain = parse_github_company(user.get("company") or "")
    bio = user.get("bio") or ""
    return Observation(
        source_id=f"github:{login or name}", source_type="github", url=user.get("html_url") or "",
        name=_trunc(name or login, MAX_FIELD), title=title_from_bio(bio), company=_trunc(company, MAX_FIELD),
        location=_trunc(user.get("location") or "", MAX_FIELD),
        avatar_url=user.get("avatar_url") or "", snippet=_trunc(bio),
        github_login=login.lower(), website=(user.get("blog") or "").strip(), company_domain=company_domain,
    )


def merge_observations(observations: List[Observation], name: str) -> List[Candidate]:
    n = len(observations)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def handles(root: int, attr: str) -> set:
        return {getattr(observations[i], attr) for i in range(n) if find(i) == root and getattr(observations[i], attr)}

    def union(a: int, b: int, check_conflict: bool) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if check_conflict:
            for attr in ("linkedin_slug", "github_login"):
                if len(handles(ra, attr) | handles(rb, attr)) > 1:
                    return
        parent[rb] = ra

    for attr in ("linkedin_slug", "github_login"):
        seen: Dict[str, int] = {}
        for i, o in enumerate(observations):
            v = getattr(o, attr)
            if v:
                if v in seen:
                    union(seen[v], i, False)
                else:
                    seen[v] = i
    company_seen: Dict[str, int] = {}
    for i, o in enumerate(observations):
        key = normalize_company_name(o.company)
        if key:
            if key in company_seen:
                union(company_seen[key], i, True)
            else:
                company_seen[key] = i

    def is_bare(o: Observation) -> bool:
        return not (normalize_company_name(o.company) or o.linkedin_slug or o.github_login)

    bare = [i for i, o in enumerate(observations) if is_bare(o)]
    anchored_roots = {find(i) for i in range(n) if not is_bare(observations[i])}
    if len(anchored_roots) == 1:
        root = next(iter(anchored_roots))
        for i in bare:
            parent[find(i)] = root

    groups: Dict[int, List[Observation]] = {}
    for i, o in enumerate(observations):
        groups.setdefault(find(i), []).append(o)
    return [_build_candidate(obs, name) for obs in groups.values()]


def _first(values) -> str:
    return next((v for v in values if v), "")


def _build_candidate(obs: List[Observation], name: str) -> Candidate:
    ordered = sorted(obs, key=lambda o: 0 if o.linkedin_slug else (1 if o.source_type == "search" else 2))
    slug = _first(o.linkedin_slug for o in ordered)
    gh = [o for o in ordered if o.source_type == "github"]
    login = _first(o.github_login for o in ordered)
    company_key = _first(normalize_company_name(o.company) for o in ordered)
    if slug:
        key = f"li:{slug}"
    elif login:
        key = f"gh:{login}"
    elif company_key:
        key = f"co:{company_key}"
    else:
        key = f"url:{_first(o.url for o in ordered)}"
    if slug:
        profile = _first(o.url for o in ordered if o.linkedin_slug == slug)
    elif login:
        profile = _first(o.url for o in ordered if o.github_login == login)
    else:
        profile = ""
    profile = profile or _first(o.url for o in ordered)
    best_name = max((o.name for o in ordered if o.name), key=len, default=name)
    return Candidate(
        candidate_id="cand_" + _sha(key, 10),
        name=_trunc(best_name, MAX_FIELD),
        title=_trunc(_first(o.title for o in ordered), MAX_FIELD),
        company=_trunc(_first(o.company for o in ordered), MAX_FIELD),
        location=_trunc(_first(o.location for o in ordered), MAX_FIELD),
        avatar_url=_first(o.avatar_url for o in ordered),
        profile_url=profile,
        description=_trunc(_first(o.snippet for o in ordered)),
        linkedin_slug=slug,
        github_login=login,
        website=_first([_first(o.website for o in gh)] + [o.website for o in ordered]),
        observations=list(obs),
    )


def _company_hint_matches(hint: str, company: str) -> bool:
    a, b = normalize_company_name(hint), normalize_company_name(company)
    return bool(a and b and (a == b or a in b or b in a))


def score_candidate(c: Candidate, inp: IndividualInput) -> Candidate:
    score = 0.0
    reasons: List[str] = []
    ok, boost = names_compatible(inp.name, c.name)
    if ok:
        pts = 0.30 if boost >= 0.30 else 0.15
        score += pts
        reasons.append(f"name matches (+{pts:.2f})")
    if c.title:
        score += 0.10
        reasons.append("job title found (+0.10)")
    if c.company:
        score += 0.15
        reasons.append("company found (+0.15)")
    sources = {(o.source_type, o.url) for o in c.observations if o.url}
    extra = min(max(len(sources) - 1, 0), 3)
    if extra:
        score += 0.12 * extra
        reasons.append(f"{extra} corroborating source(s) (+{0.12 * extra:.2f})")
    if inp.company and _company_hint_matches(inp.company, c.company):
        score += 0.20
        reasons.append("matches company hint (+0.20)")
    loc_hint = inp.location.strip().lower()
    if loc_hint and (loc_hint in c.location.lower() or loc_hint in c.description.lower()):
        score += 0.10
        reasons.append("matches location hint (+0.10)")
    blob = " ".join((c.title, c.company, c.description))
    ctx_hit = next((t for t in context_tokens(inp.context, min_len=3)
                    if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", blob, re.I)), "")
    if ctx_hit:
        score += 0.10
        reasons.append(f"matches context hint '{_trunc(ctx_hit, 40)}' (+0.10)")
    score = min(score, 1.0)
    want_li = linkedin_slug(inp.linkedin_url) if inp.linkedin_url else ""
    want_gh = github_login_from_url(inp.github_url) if inp.github_url else ""
    if (want_li and want_li == c.linkedin_slug) or (want_gh and want_gh == c.github_login):
        score = max(score, 0.95)
        reasons.append("url_match: supplied profile URL matches")
    c.confidence = round(score, 2)
    c.confidence_reasons = reasons
    return c


def _is_url_match(c: Candidate) -> bool:
    return any(r.startswith("url_match") for r in c.confidence_reasons)


def resolve_identity(observations: List[Observation], inp: IndividualInput) -> IdentityDecision:
    cands = [score_candidate(c, inp) for c in merge_observations(observations, inp.name)]
    cands.sort(key=lambda c: (_is_url_match(c), c.confidence), reverse=True)
    if not cands:
        return IdentityDecision("low_confidence", "", [], f"No public profiles found for {inp.name}.")
    plausible = [c for c in cands if c.confidence >= CANDIDATE_MIN]
    if not plausible:
        return IdentityDecision("low_confidence", "", cands[:3],
                                f"Only weak matches found for {inp.name}; add a company, location or profile URL.")
    top = plausible[0]
    runner_up = plausible[1].confidence if len(plausible) > 1 else 0.0
    url_matched = _is_url_match(top)
    if url_matched or (top.confidence >= AUTO_SELECT_MIN and top.confidence - runner_up >= AUTO_SELECT_MARGIN):
        return IdentityDecision("auto", top.candidate_id, plausible, f"Identified {top.name} with high confidence.")
    return IdentityDecision("select", "", plausible, f"Select which {inp.name} you mean.")


class SearchSource(Protocol):
    def search(self, query: str) -> List[Dict[str, str]]: ...


class DuckDuckGoSource:
    def __init__(self, scraper: Optional[ScraplingScraper] = None):
        self.scraper = scraper or ScraplingScraper(use_browser=False, use_tor=False)

    def search(self, query: str) -> List[Dict[str, str]]:
        hits = self.scraper.search_person("", "", custom_query=query) or []
        # DuckDuckGo Lite may return redirect links (//duckduckgo.com/l/?uddg=...); keep the real destination.
        return [{**h, "url": decode_ddg_url(h.get("url") or "")} for h in hits if isinstance(h, dict)]


class GitHubSource:
    HEADERS = {"User-Agent": "SealAPIResearchBot/1.0", "Accept": "application/vnd.github+json"}

    def __init__(self, client: Optional[httpx.Client] = None, base_url: str = "https://api.github.com"):
        self.client = client or httpx.Client(timeout=10.0)
        self.base_url = base_url.rstrip("/")
        self.errors: List[str] = []
        self.rate_limited = False

    @staticmethod
    def _rate_limit_error(r: httpx.Response) -> str:
        try:
            reset = datetime.fromtimestamp(int(r.headers.get("X-RateLimit-Reset", "")), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            return GITHUB_RATE_LIMIT_MSG
        return f"{GITHUB_RATE_LIMIT_MSG}; resets at {reset:%H:%M} UTC"

    def _get(self, path: str, params: Optional[dict] = None):
        if self.rate_limited:  # quota exhausted: further calls would only fail and burn time
            return None
        try:
            r = self.client.get(self.base_url + path, params=params, headers=self.HEADERS, timeout=10.0)
        except Exception as e:  # noqa: BLE001 - network errors must never propagate
            self.errors.append(f"github {path}: {type(e).__name__}")
            return None
        if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
            self.rate_limited = True
            self.errors.append(self._rate_limit_error(r))
            return None
        if r.status_code != 200:
            self.errors.append(f"github {path}: HTTP {r.status_code}")
            return None
        try:
            return r.json()
        except ValueError:
            self.errors.append(f"github {path}: invalid JSON")
            return None

    def search_users(self, name: str, limit: int = 5) -> List[dict]:
        data = self._get("/search/users", {"q": f'"{name}" in:name type:user', "per_page": limit})
        items = data.get("items") if isinstance(data, dict) else None
        return [i for i in (items or []) if isinstance(i, dict)][:limit]

    def get_user(self, login: str) -> Optional[dict]:
        data = self._get(f"/users/{login}")
        return data if isinstance(data, dict) else None

    def get_repos(self, login: str, limit: int = 10) -> List[dict]:
        data = self._get(f"/users/{login}/repos", {"sort": "pushed", "per_page": limit})
        return [r for r in data if isinstance(r, dict)][:limit] if isinstance(data, list) else []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_social(url: str) -> bool:
    d = extract_domain(url)
    return d in ("linkedin.com", "x.com", "twitter.com") or d.endswith((".linkedin.com", ".x.com", ".twitter.com"))


def website_to_observation(url: str, page: ScrapeResult, name: str) -> Optional[Observation]:
    if not getattr(page, "success", False):
        return None
    text = page.extracted_text or ""
    if not (_full_name_in(text, name) or _full_name_in(page.title or "", name)):
        return None
    blob = " ".join(x for x in (page.title, page.meta_description, text[:2000]) if x)
    role, company = parse_role_at_company(blob)
    return Observation(
        source_id=f"website:{_sha(url, 10)}", source_type="website", url=url, name=_trunc(name, MAX_FIELD),
        title=role, company=company, snippet=_trunc(page.meta_description or text), website=url,
    )


def collect_observations(
    inp: IndividualInput, search: SearchSource, github: GitHubSource, fetch: Callable[[str], ScrapeResult],
) -> Tuple[List[Observation], List[dict], List[str]]:
    observations: List[Observation] = []
    sources: List[dict] = []
    errors: List[str] = []
    seen_ids: set = set()

    def add(o: Observation, title: str = "") -> None:
        if o.source_id in seen_ids:
            return
        seen_ids.add(o.source_id)
        observations.append(o)
        sources.append({"source_id": o.source_id, "url": o.url, "source_type": o.source_type,
                        "title": _trunc(title or o.name, MAX_FIELD), "retrieved_at": _now(), "query": o.query})

    total_hits = 0
    for q in build_discovery_queries(inp):
        try:
            hits = search.search(q) or []
        except Exception as e:  # noqa: BLE001
            errors.append(f"search failed for {q}: {type(e).__name__}: {_trunc(str(e), 100)}")
            continue
        total_hits += len(hits)
        for hit in hits:
            o = parse_search_hit(hit, inp.name, q)
            if o:
                add(o, hit.get("title") or "")
    if total_hits == 0:  # search_person swallows errors and bot challenges, so silence is the only signal
        errors.append(SEARCH_EMPTY_MSG)

    supplied = github_login_from_url(inp.github_url) if inp.github_url else ""
    logins: List[Tuple[str, bool]] = []
    if supplied:
        logins.append((supplied, True))
    for u in github.search_users(inp.name, limit=MAX_GITHUB_LOOKUPS)[:MAX_GITHUB_LOOKUPS]:
        login = (u.get("login") or "").strip().lower()
        if login and login not in {l for l, _ in logins}:
            logins.append((login, False))
    for login, is_supplied in logins:
        user = github.get_user(login)
        if not user:
            continue
        if not is_supplied and not names_compatible(inp.name, (user.get("name") or ""))[0]:
            continue
        o = github_user_to_observation(user)
        if o:
            add(o)

    site = (inp.website or "").strip()
    if site and not _is_social(site):
        try:
            page = fetch(site)
        except Exception as e:  # noqa: BLE001
            errors.append(f"website fetch failed: {type(e).__name__}: {_trunc(str(e), 100)}")
        else:
            o = website_to_observation(site, page, inp.name)
            if o:
                add(o, page.title or "")
            elif not page.success:
                errors.append(f"website fetch failed: {_trunc(page.error, 100)}")

    errors.extend(getattr(github, "errors", []))
    return observations, sources, errors
