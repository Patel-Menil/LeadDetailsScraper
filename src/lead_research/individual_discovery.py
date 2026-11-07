"""Individual research: parse raw discovery hits into identity candidates and decide whether one is clear."""
import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .company_intel import normalize_company_name
from .identity import extract_domain, names_compatible

AUTO_SELECT_MIN = 0.75
AUTO_SELECT_MARGIN = 0.25
CANDIDATE_MIN = 0.35
MAX_TEXT = 300
MAX_QUERIES = 5

_GITHUB_RESERVED = {
    "orgs", "topics", "search", "features", "pricing", "about", "login", "join", "explore", "marketplace",
    "sponsors", "settings", "notifications", "collections", "events", "trending", "enterprise", "site", "apps",
}
_TITLE_SPLIT = re.compile(r"\s+[-–—|]\s+")
_END = r"(?:[^,;|·•\n.]|\.(?=\S))+"
_ROLE_VERB = re.compile(r"\b(?:is|as|was)\s+(?:an?\s+|the\s+)?(?P<role>[^,.;|·•\n]+?)\s+at\s+(?P<co>" + _END + ")", re.I)
_ROLE_BARE = re.compile(r"(?:^|[·|•]\s*)(?P<role>[A-Z][\w&/ ]*?)\s+at\s+(?P<co>" + _END + ")")


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


def build_discovery_queries(inp: IndividualInput) -> List[str]:
    name = inp.name.strip()
    queries = [f'"{name}"', f'"{name}" linkedin']
    if inp.company.strip():
        queries.append(f'"{name}" "{inp.company.strip()}"')
    if inp.location.strip():
        queries.append(f'"{name}" {inp.location.strip()}')
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
        return parts[0], "", parts[1]
    return parts[0], parts[1], " - ".join(parts[2:])


def parse_role_at_company(text: str) -> Tuple[str, str]:
    for rx in (_ROLE_VERB, _ROLE_BARE):
        m = rx.search(text or "")
        if m:
            return m.group("role").strip(), m.group("co").strip()
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
    if not (role and company):
        r2, c2 = parse_role_at_company(snippet)
        role, company = role or r2, company or c2
    if slug and "·" in snippet:
        first = snippet.split("·")[0].strip()
        if first and " at " not in first and len(first) < 60:
            location = first
    return Observation(
        source_id=f"search:{_sha(url, 10)}", source_type="search", url=url, name=final_name, title=role,
        company=company, location=location, snippet=_trunc(snippet), linkedin_slug=slug, github_login=login,
        query=query,
    )


def github_user_to_observation(user: dict) -> Optional[Observation]:
    name = (user.get("name") or "").strip()
    login = (user.get("login") or "").strip()
    if not name and not login:
        return None
    company = (user.get("company") or "").strip().lstrip("@").strip()
    return Observation(
        source_id=f"github:{login or name}", source_type="github", url=user.get("html_url") or "",
        name=name or login, company=company, location=(user.get("location") or "").strip(),
        avatar_url=user.get("avatar_url") or "", snippet=_trunc(user.get("bio") or ""),
        github_login=login.lower(), website=(user.get("blog") or "").strip(),
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
        name=best_name,
        title=_first(o.title for o in ordered),
        company=_first(o.company for o in ordered),
        location=_first(o.location for o in ordered),
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
    score = min(score, 1.0)
    want_li = linkedin_slug(inp.linkedin_url) if inp.linkedin_url else ""
    want_gh = github_login_from_url(inp.github_url) if inp.github_url else ""
    if (want_li and want_li == c.linkedin_slug) or (want_gh and want_gh == c.github_login):
        score = max(score, 0.95)
        reasons.append("url_match: supplied profile URL matches")
    c.confidence = round(score, 2)
    c.confidence_reasons = reasons
    return c


def resolve_identity(observations: List[Observation], inp: IndividualInput) -> IdentityDecision:
    cands = [score_candidate(c, inp) for c in merge_observations(observations, inp.name)]
    cands.sort(key=lambda c: c.confidence, reverse=True)
    if not cands:
        return IdentityDecision("low_confidence", "", [], f"No public profiles found for {inp.name}.")
    plausible = [c for c in cands if c.confidence >= CANDIDATE_MIN]
    if not plausible:
        return IdentityDecision("low_confidence", "", cands[:3],
                                f"Only weak matches found for {inp.name}; add a company, location or profile URL.")
    top = plausible[0]
    runner_up = plausible[1].confidence if len(plausible) > 1 else 0.0
    if top.confidence >= AUTO_SELECT_MIN and top.confidence - runner_up >= AUTO_SELECT_MARGIN:
        return IdentityDecision("auto", top.candidate_id, plausible, f"Identified {top.name} with high confidence.")
    return IdentityDecision("select", "", plausible, f"Select which {inp.name} you mean.")
