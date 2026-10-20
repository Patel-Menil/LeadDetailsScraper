"""Identity resolution, targeted query generation, and candidate matching.

Ensures that public search results and fetched pages belong to the intended
person and company, preventing false positives, marketplace contamination,
and unwarranted name expansion.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .schemas import LeadInput


def extract_domain(url_or_domain: str) -> str:
    """Normalize a URL or domain string to lowercased netloc without www."""
    if not url_or_domain:
        return ""
    u = url_or_domain.strip().lower()
    if not u.startswith(("http://", "https://")):
        u = f"https://{u}"
    try:
        parsed = urlparse(u)
        netloc = parsed.netloc or parsed.path
        netloc = netloc.split(":")[0]  # remove port
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def is_abbreviated_name(name: str) -> bool:
    """Check if the surname in a full name is a single-letter abbreviation (e.g. 'Andrew R', 'Jon B.')."""
    if not name:
        return False
    parts = name.strip().split()
    if len(parts) >= 2:
        last = parts[-1].rstrip(".")
        if len(last) == 1:
            return True
    return False


def names_compatible(lead_name: str, candidate_name: str) -> Tuple[bool, float]:
    """
    Check if a candidate name is compatible with the lead's name.
    Returns (is_compatible, score_boost).
    """
    if not lead_name or not candidate_name:
        return False, 0.0

    ln = re.sub(r"[^\w\s]", "", lead_name.lower()).strip()
    cn = re.sub(r"[^\w\s]", "", candidate_name.lower()).strip()

    if ln == cn:
        return True, 0.35

    lead_parts = ln.split()
    cand_parts = cn.split()

    if not lead_parts or not cand_parts:
        return False, 0.0

    # First name check
    lead_first = lead_parts[0]
    cand_first = cand_parts[0]

    if lead_first != cand_first and not (lead_first.startswith(cand_first) or cand_first.startswith(lead_first)):
        # Completely different first name
        return False, 0.0

    # Surname check
    lead_last = lead_parts[-1]
    cand_last = cand_parts[-1]

    # Abbreviated lead surname (e.g. 'Jon B' vs 'Jon Burlinson' or 'Jon B.')
    if len(lead_last) == 1:
        if cand_last.startswith(lead_last):
            # Compatible initial, but lower confidence without company proof
            return True, 0.20
        return False, 0.0

    # Exact surname match
    if lead_last == cand_last:
        return True, 0.30

    return False, 0.0


def companies_match(lead_company: str, candidate_text: str, candidate_url: str = "", lead_website: str = "") -> Tuple[bool, float]:
    """
    Evaluate company match using company name, text context, and domain matching.
    """
    if not lead_company:
        return False, 0.0

    norm_company = re.sub(r"[^\w\s]", "", lead_company.lower()).strip()
    # Strip common corporate suffixes for matching
    clean_company = re.sub(r"\b(inc|llc|corp|corporation|ltd|limited|technologies|group|co|consulting)\b", "", norm_company).strip()

    text_lower = (candidate_text or "").lower()
    lead_domain = extract_domain(lead_website)
    cand_domain = extract_domain(candidate_url)

    # 1. Exact domain match
    if lead_domain and cand_domain and (lead_domain == cand_domain or cand_domain.endswith(f".{lead_domain}")):
        return True, 0.40

    # 2. Strong company name match in candidate text or title
    if clean_company and len(clean_company) >= 3 and clean_company in text_lower:
        return True, 0.30

    if norm_company in text_lower:
        return True, 0.30

    return False, 0.0


def titles_compatible(lead_title: str, candidate_text: str) -> Tuple[bool, float]:
    """Check if the candidate text reflects senior/engineering role alignment."""
    if not lead_title:
        return True, 0.05  # neutral

    lt = lead_title.lower()
    ct = (candidate_text or "").lower()

    # High-signal title keywords
    role_keywords = ["cto", "ciso", "ceo", "founder", "head of ai", "vp", "director", "architect", "engineer", "lead"]
    matched = [kw for kw in role_keywords if kw in lt and kw in ct]
    if matched:
        return True, 0.15

    # Check for direct contradictions (e.g. freelance copywriter when lead is CTO)
    if any(k in lt for k in ["cto", "vp", "chief", "director"]):
        if any(bad in ct for bad in ["freelance copywriter", "junior developer", "rpa developer", "entry level", "student"]):
            return False, -0.25

    return True, 0.0


def is_marketplace_false_positive(lead: LeadInput, candidate: Dict[str, str]) -> bool:
    """
    Detect when search results return random users/freelancers from the lead's own company marketplace.
    Example: Andrew R (CTO at Upwork) matching upwork.com/freelancers/andrewrandolph.
    """
    url = candidate.get("url", "").lower()
    title = candidate.get("title", "").lower()
    snippet = candidate.get("snippet", "").lower()

    comp = (lead.company or "").lower()
    # If the company operates a public talent or freelancer directory (Upwork, Fiverr, TopTal, etc.)
    if "upwork" in comp and "upwork.com/freelancers" in url:
        # Check if the title or snippet indicates a platform freelancer rather than the company employee/executive
        if "freelancer" in title or "freelancer" in snippet or "developer - upwork" in title:
            return True

    return False


def identity_match_score(lead: LeadInput, candidate: Dict[str, str]) -> float:
    """
    Deterministic identity resolution matching score between a lead and a discovery candidate.
    Score ranges from 0.0 to 1.0.
    """
    # 1. Filter out known marketplace false-positives
    if is_marketplace_false_positive(lead, candidate):
        return 0.0

    title = candidate.get("title", "")
    snippet = candidate.get("snippet", "")
    url = candidate.get("url", "")
    combined_cand = f"{title} {snippet} {url}"

    # Extract likely person name from title if present (e.g. 'Andrew Rabinovich - Upwork | LinkedIn')
    cand_name = title.split("-")[0].split("|")[0].split("—")[0].strip()

    name_ok, name_score = names_compatible(lead.name, cand_name)
    if not name_ok:
        # Fallback check if lead name appears in candidate title/snippet
        ln_lower = lead.name.lower()
        if ln_lower in title.lower():
            name_ok = True
            name_score = 0.25
        elif not is_abbreviated_name(lead.name) and ln_lower in snippet.lower():
            name_ok = True
            name_score = 0.15
        else:
            return 0.0  # Name is incompatible or unverified

    # Company match
    comp_ok, comp_score = companies_match(
        lead_company=lead.company or "",
        candidate_text=combined_cand,
        candidate_url=url,
        lead_website=lead.company_website or "",
    )

    # For abbreviated names (e.g., 'Andrew R'), company match is strictly mandatory!
    if is_abbreviated_name(lead.name) and not comp_ok:
        return 0.0

    # Title match
    title_ok, title_score = titles_compatible(lead.job_title or "", combined_cand)

    total_score = name_score + comp_score + title_score

    # Bonus for official company domain
    cand_domain = extract_domain(url)
    lead_domain = extract_domain(lead.company_website or "")
    if cand_domain and lead_domain and cand_domain == lead_domain:
        total_score += 0.20

    # Bonus for professional profile matching lead
    if "linkedin.com/in/" in url and comp_ok:
        total_score += 0.15

    return max(0.0, min(1.0, round(total_score, 2)))


def build_targeted_queries(lead: LeadInput) -> List[str]:
    """
    Generate a small, highly targeted set of discovery queries.
    Avoids broad or noisy query spam.
    """
    queries: List[str] = []
    name = lead.name.strip() if lead.name else ""
    company = lead.company.strip() if lead.company else ""
    website = lead.company_website or ""
    domain = extract_domain(website)
    title = lead.job_title.strip() if lead.job_title else ""

    # 1. Exact Name + Company
    if name and company:
        queries.append(f'"{name}" "{company}"')

    # 2. Site-targeted query for official company site
    if domain and (lead.first_name or name):
        search_n = lead.first_name or name
        queries.append(f'site:{domain} "{search_n}"')

    # 3. Exact Name + Title (only for non-abbreviated names to prevent massive noise)
    if name and title and not is_abbreviated_name(name):
        # Use primary role token
        role_token = title.split("|")[0].split(",")[0].strip()
        if len(role_token) > 2:
            queries.append(f'"{name}" "{role_token}"')

    # 4. Company AI/API public context signal
    if company:
        queries.append(f'"{company}" API OR AI OR security OR platform')

    # Deduplicate preserving order
    seen = set()
    deduped = []
    for q in queries:
        cleaned = re.sub(r"\s+", " ", q).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            deduped.append(cleaned)

    return deduped[:4]
