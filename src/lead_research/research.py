"""Core lead research engine extracting verifiable facts, claims, SealAPI relevance, and profiles."""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from .icebreaker import build_icebreaker, extract_public_signals
from .identity import build_targeted_queries, extract_domain, identity_match_score, is_abbreviated_name
from .schemas import (
    ColdEmailContext,
    ContactReadiness,
    Icebreaker,
    LeadClaim,
    LeadInput,
    LeadProfile,
    PriorityInfo,
    ProfessionalContext,
    PublicSignal,
    ResearchMetadata,
    ScoringBreakdown,
    SealAPIRelevance,
    SourceEvidence,
)
from .scraper import ScraplingScraper, ScrapeResult
from .scoring import LeadScorer

logger = logging.getLogger("lead_research.research")


def is_company_corroborated(
    lead_company: str,
    original_url: str,
    final_url: str,
    title: str,
    meta_desc: str,
    extracted_text: str,
) -> Tuple[bool, str]:
    """
    Verifies that the fetched destination actually corresponds to the target company.
    Requires meaningful evidence connecting the requested company name to the fetched site.
    Never treats domain equality alone as company verification.
    """
    if not lead_company:
        return False, "No target company specified."

    orig_dom = extract_domain(original_url)
    final_dom = extract_domain(final_url)
    is_domain_redirected = bool(orig_dom and final_dom and orig_dom != final_dom)

    combined_text = f"{title} {meta_desc} {extracted_text[:2000]}".lower()

    # Reject parked, inactive, or generic placeholder error pages immediately
    parked_or_error_indicators = [
        "domain for sale", "buy this domain", "parked domain", "404 not found",
        "under construction", "website coming soon", "domain parked", "godaddy",
        "namecheap", "dan.com", "sedo", "huge domains", "page not found",
        "error 404", "apache2 ubuntu default page", "nginx default page",
        "welcome to nginx", "welcome to openresty", "default web site page",
        "server error", "502 bad gateway", "503 service unavailable", "dns error",
        "this domain is registered", "inquire about this domain"
    ]
    if any(parked in combined_text for parked in parked_or_error_indicators):
        return False, f"Domain '{orig_dom or final_dom}' appears parked, inactive, or a generic placeholder error page."

    # Normalize company name for matching
    clean_company = re.sub(r"[^\w\s]", "", lead_company.lower()).strip()
    company_tokens = clean_company.split()
    generic_company_tokens = {
        "inc", "llc", "corp", "corporation", "ltd", "limited", "technologies", "technology",
        "group", "co", "the", "company", "solutions", "services", "systems", "global",
        "consulting", "digital", "data", "tech", "software", "partners", "holdings",
        "capital", "ventures", "management", "network", "associates", "enterprises",
        "security", "financial", "health", "care", "labs", "studio", "studios", "design",
        "creative", "cloud", "ai", "app", "apps", "web", "interactive", "media", "international",
        "agency", "consultants", "platform", "online"
    }
    distinctive_tokens = [
        t for t in company_tokens
        if t not in generic_company_tokens and len(t) >= 3
    ]

    has_company_mention = False
    # 1. Exact full clean company phrase appears in page
    if clean_company and clean_company in combined_text:
        has_company_mention = True
    # 2. Distinctive brand token appears in title or meta description
    elif any(token in f"{title} {meta_desc}".lower() for token in distinctive_tokens):
        has_company_mention = True
    # 3. If multiple distinctive tokens exist, at least two distinctive tokens appear in the text
    elif len(distinctive_tokens) >= 2 and sum(1 for token in distinctive_tokens if token in combined_text) >= 2:
        has_company_mention = True
    # 4. If single distinctive token exists (>= 4 chars), and domain contains it AND page contains it
    elif len(distinctive_tokens) == 1 and len(distinctive_tokens[0]) >= 4:
        token = distinctive_tokens[0]
        if token in combined_text and (orig_dom and token in orig_dom.lower()):
            has_company_mention = True

    # If redirected to an unrelated domain without company mention
    if is_domain_redirected and not has_company_mention:
        return False, f"Redirected from {orig_dom} to unrelated host {final_dom} without company corroboration."

    # Never treat domain equality alone as company verification
    if not has_company_mention:
        return False, f"Destination page on '{orig_dom or final_dom}' does not contain corroborating evidence for '{lead_company}'."

    return True, f"Company identity corroborated on official domain for '{lead_company}'."


HISTORICAL_ROLE_PATTERNS = [
    r"\bformer\b", r"\bpreviously\b", r"\bpast\b", r"\bex-", r"\bretired\b",
    r"\bserv(ed|ing)\s+as\b", r"\bwas\s+the\b", r"\buntil\s+20\d\d\b",
    r"\bprior\s+to\b", r"\bheld\s+roles?\s+at\b"
]


def check_person_role_association(
    person_name: str,
    job_title: str,
    text: str,
    is_bio_page: bool,
) -> Tuple[bool, bool, str]:
    """
    Evaluates whether inspected destination text connects the person to the organization and specifically to the role.
    Returns: (name_verified, role_verified, explanation)
    """
    if not person_name or not text:
        return False, False, "Missing person name or page text"

    p_lower = person_name.lower().strip()
    t_lower = text.lower()

    # Name must appear in the text
    if p_lower not in t_lower:
        return False, False, f"Name '{person_name}' not found on page"

    # Abbreviated name (e.g. 'Jon B.') cannot be verified without full surname corroboration
    if is_abbreviated_name(person_name):
        return False, False, f"Name '{person_name}' is abbreviated; requires full surname evidence"

    # Context check: reject acknowledgement / testimonial / customer quote context
    name_pos = t_lower.find(p_lower)
    while name_pos != -1:
        start_idx = max(0, name_pos - 150)
        end_idx = min(len(t_lower), name_pos + len(p_lower) + 150)
        surrounding = t_lower[start_idx:end_idx]
        if any(ack in surrounding for ack in [
            "acknowledgement", "acknowledgments", "special thanks to", "donor", "donors",
            "customer review", "testimonial", "client testimonial", "what our clients say",
            "quoted by", "user review", "sponsor", "client quote", "user story"
        ]):
            return False, False, f"Mention of '{person_name}' is in an acknowledgement or testimonial context, not employment"
        name_pos = t_lower.find(p_lower, name_pos + 1)

    # Name is on the page. Is it an official bio / team page?
    if not is_bio_page:
        return False, False, f"Mention of '{person_name}' on general page does not establish employment or role"

    # On an official team/bio page:
    name_verified = True
    role_verified = False
    explanation = f"Name '{person_name}' confirmed on official team/leadership page"

    if job_title and len(job_title) > 2:
        j_lower = job_title.lower().strip()
        name_indices = [m.start() for m in re.finditer(re.escape(p_lower), t_lower)]
        for idx in name_indices:
            window = t_lower[max(0, idx - 180):min(len(t_lower), idx + len(p_lower) + 180)]
            role_matched_in_window = False
            if j_lower in window:
                role_matched_in_window = True
            else:
                role_tokens = [tok.strip() for tok in re.split(r"[,|\-/()]", j_lower) if len(tok.strip()) >= 3 and tok.strip() not in ("the", "and", "for", "with")]
                if role_tokens and all(tok in window for tok in role_tokens[:2]):
                    role_matched_in_window = True

            if role_matched_in_window:
                # Check for historical or past role indicators
                if any(re.search(pat, window) for pat in HISTORICAL_ROLE_PATTERNS):
                    explanation = f"Role '{job_title}' appears in historical or past context for '{person_name}', not current employment"
                    role_verified = False
                else:
                    role_verified = True
                    explanation = f"Confirmed '{person_name}' in role '{job_title}' on official team page"
                    break

        if not role_verified and "historical" not in explanation:
            explanation = f"Name '{person_name}' found on team page, but role '{job_title}' is not connected to this person"

    return name_verified, role_verified, explanation


def validate_claims_provenance(claims: List[LeadClaim], sources: List[SourceEvidence]) -> List[LeadClaim]:
    """
    Enforces that every verified claim has traceable, eligible supporting evidence.
    Downgrades any unsupported verified claims to unverified or needs_review.
    """
    source_map = {s.source_id: s for s in sources}

    for clm in claims:
        if clm.status == "verified":
            valid_sources = [source_map[sid] for sid in clm.source_ids if sid in source_map]
            if not valid_sources:
                clm.status = "needs_review"
                clm.confidence = min(clm.confidence, 0.40)
                clm.review_reason = "Missing source provenance: referenced source does not exist"
                continue

            all_snippet_or_input = all(s.source_type in ("user_input", "search_snippet") for s in valid_sources)
            if all_snippet_or_input:
                clm.status = "needs_review"
                clm.confidence = min(clm.confidence, 0.50)
                clm.review_reason = "Search snippets or imported input alone cannot independently establish a verified claim"
                continue

            if clm.field == "name":
                has_eligible_name_source = any(
                    s.source_type in ("official_company", "biography", "team_page", "public_professional_profile", "public_web_bio") and
                    s.evidence_quality >= 0.70
                    for s in valid_sources
                )
                if not has_eligible_name_source:
                    clm.status = "partially_verified"
                    clm.confidence = min(clm.confidence, 0.50)
                    clm.review_reason = "Name claim lacks eligible inspected source evidence"

            elif clm.field == "job_title":
                has_eligible_bio_source = any(
                    s.source_type in ("official_company", "biography", "team_page", "public_professional_profile") and
                    s.evidence_quality >= 0.70 and
                    any("role verification" in f.lower() or "confirmed" in f.lower() for f in s.facts_supported)
                    for s in valid_sources
                )
                if not has_eligible_bio_source:
                    clm.status = "unverified"
                    clm.confidence = min(clm.confidence, 0.40)
                    clm.review_reason = "Role claim lacks inspected destination-page evidence connecting person to role"

            elif clm.field == "company":
                has_corroborated_company = any(
                    s.source_type in ("official_company", "company_registry", "verified_profile") and
                    s.evidence_quality >= 0.70 and
                    any("company identity" in f.lower() or "website title" in f.lower() for f in s.facts_supported)
                    for s in valid_sources
                )
                if not has_corroborated_company:
                    clm.status = "unverified"
                    clm.confidence = min(clm.confidence, 0.50)
                    clm.review_reason = "Company claim lacks corroborated official domain evidence"

            elif clm.field == "professional_email":
                has_corroborated_email = any(
                    s.source_type in ("official_company", "biography", "team_page", "public_professional_profile", "public_web_bio") and
                    s.evidence_quality >= 0.70 and
                    (
                        (clm.value and clm.value.lower() in (s.relevant_excerpt or "").lower()) or
                        any("email corroborated" in f.lower() or "email verification" in f.lower() for f in s.facts_supported)
                    )
                    for s in valid_sources
                )
                if not has_corroborated_email:
                    clm.status = "input_provided"
                    clm.confidence = min(clm.confidence, 0.50)
                    clm.review_reason = "Email claim lacks eligible inspected source evidence containing the exact address"

    return claims


class LeadResearcher:
    """Researches professional data and produces traceable, grounded lead profiles."""

    def __init__(self, scraper: Optional[ScraplingScraper] = None, scorer: Optional[LeadScorer] = None):
        self.scraper = scraper or ScraplingScraper()
        self.scorer = scorer or LeadScorer()

    def research_lead(
        self,
        lead: LeadInput,
        skip_web_scrape: bool = False,
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> LeadProfile:
        """Conduct comprehensive public-web research and compile a validated LeadProfile."""
        sources: List[SourceEvidence] = []
        claims: List[LeadClaim] = []
        limitations: List[str] = []
        researched_snippets: List[str] = []
        candidate_bio_snippets: List[Dict[str, str]] = []

        now_iso = datetime.now(timezone.utc).isoformat()
        if log_fn:
            log_fn(f"🎯 Target: {lead.name} ({lead.job_title or 'Leadership'}) @ {lead.company}")

        # 1. Baseline source from imported input record (isolated from verified research)
        input_src_id = f"src_input_{lead.lead_id[:8]}"
        input_facts = []
        if lead.name:
            input_facts.append(f"Imported Name: {lead.name}")
        if lead.job_title:
            input_facts.append(f"Imported Job Title: {lead.job_title}")
        if lead.company:
            input_facts.append(f"Imported Company: {lead.company}")
        if lead.industry:
            input_facts.append(f"Imported Industry: {lead.industry}")
        if lead.professional_email:
            input_facts.append(f"Imported Professional Email: {lead.professional_email}")
        if lead.company_website:
            input_facts.append(f"Imported Company Website: {lead.company_website}")

        sources.append(
            SourceEvidence(
                source_id=input_src_id,
                source_url="lead_import_record",
                source_type="user_input",
                retrieval_timestamp=now_iso,
                evidence_quality=0.60,
                facts_supported=input_facts,
            )
        )

        # Base Claims from Input (Provenance: imported facts are not independently web-verified)
        claims.append(
            LeadClaim(
                claim_id="clm_name",
                field="name",
                value=lead.name,
                status="needs_review" if is_abbreviated_name(lead.name) else "input_provided",
                source_ids=[input_src_id],
                confidence=0.50 if not is_abbreviated_name(lead.name) else 0.30,
                review_reason="Surname is abbreviated; requires full name evidence" if is_abbreviated_name(lead.name) else "Imported from input dataset; web verification pending",
            )
        )
        claims.append(
            LeadClaim(
                claim_id="clm_company",
                field="company",
                value=lead.company,
                status="input_provided" if lead.company else "unverified",
                source_ids=[input_src_id],
                confidence=0.50 if lead.company else 0.0,
                review_reason="Imported from input dataset",
            )
        )
        if lead.job_title:
            claims.append(
                LeadClaim(
                    claim_id="clm_title",
                    field="job_title",
                    value=lead.job_title,
                    status="input_provided",
                    source_ids=[input_src_id],
                    confidence=0.50,
                    review_reason="Imported from input dataset",
                )
            )
        if lead.professional_email:
            is_valid_syntax = "@" in lead.professional_email and "." in lead.professional_email.split("@")[-1] and not any(c in lead.professional_email for c in [" ", "\t", "\n"])
            claims.append(
                LeadClaim(
                    claim_id="clm_email",
                    field="professional_email",
                    value=lead.professional_email,
                    status="input_provided" if is_valid_syntax else "unverified",
                    source_ids=[input_src_id],
                    confidence=0.50 if is_valid_syntax else 0.10,
                    review_reason="Syntax valid from import; deliverability probe not performed" if is_valid_syntax else "Malformed email address syntax from import",
                )
            )

        # 2. LinkedIn access limitation notice
        if lead.linkedin_url:
            limitations.append(
                f"LinkedIn URL ({lead.linkedin_url}) is behind an authentication wall; public domain records used for verified evidence."
            )

        # 3. Company Website Extraction
        company_site_url = lead.company_website or ""
        if company_site_url and not company_site_url.startswith(("http://", "https://")):
            company_site_url = f"https://{company_site_url}"

        company_site_fetched = False
        company_corroborated = False
        company_final_url = company_site_url
        company_mentions_person = False
        company_src_id = f"src_web_{lead.lead_id[:8]}"

        if company_site_url and not skip_web_scrape:
            try:
                if log_fn:
                    log_fn(f"🌐 [Web Scraper] Fetching company website: {company_site_url}")
                res: ScrapeResult = self.scraper.fetch_url(company_site_url)
                if res.success:
                    company_site_fetched = True
                    company_final_url = res.url
                    web_facts: List[str] = []
                    if res.title:
                        web_facts.append(f"Website Title: {res.title}")
                    if res.meta_description:
                        web_facts.append(f"Company Mission: {res.meta_description}")
                    if res.headings:
                        web_facts.append(f"Core Capabilities: {', '.join(res.headings[:4])}")

                    # Check if company homepage explicitly mentions the target person
                    company_corroborated, comp_reason = is_company_corroborated(
                        lead_company=lead.company or "",
                        original_url=company_site_url,
                        final_url=res.url,
                        title=res.title or "",
                        meta_desc=res.meta_description or "",
                        extracted_text=res.extracted_text,
                    )

                    web_facts: List[str] = []
                    if company_corroborated:
                        web_facts.append(f"Company Identity: {comp_reason}")
                    if res.title:
                        web_facts.append(f"Website Title: {res.title}")
                    if res.meta_description:
                        web_facts.append(f"Company Mission: {res.meta_description}")
                    if res.headings:
                        web_facts.append(f"Core Capabilities: {', '.join(res.headings[:4])}")

                    from urllib.parse import urlparse
                    parsed_u = urlparse(res.url)
                    path_l = (parsed_u.path or "").lower()
                    has_bio_path = any(p in path_l for p in ["/team", "/leadership", "/executives", "/management", "/about/leadership", "/about/team", "/people"])
                    is_leadership_bio = has_bio_path and any(k in (res.title or "").lower() or k in path_l for k in ["leadership", "executive", "team", "people", "management", "board"])

                    name_verified, role_verified, assoc_reason = check_person_role_association(
                        person_name=lead.name or "",
                        job_title=lead.job_title or "",
                        text=res.extracted_text,
                        is_bio_page=is_leadership_bio,
                    )
                    if name_verified:
                        web_facts.append(f"Person Verification: {assoc_reason}")
                    if role_verified:
                        web_facts.append(f"Role Verification: {assoc_reason}")

                    for clm in claims:
                        if clm.field == "name":
                            if name_verified:
                                clm.status = "verified"
                                clm.confidence = 0.90
                                if company_src_id not in clm.source_ids:
                                    clm.source_ids.append(company_src_id)
                            elif is_abbreviated_name(lead.name):
                                clm.status = "needs_review"
                                clm.confidence = 0.30
                                clm.review_reason = "Surname is abbreviated; requires full name evidence"
                            elif lead.name and lead.name.lower() in res.extracted_text.lower():
                                # Mentioned on company site, but role not corroborated on team/bio page
                                clm.status = "partially_verified"
                                clm.confidence = 0.65
                                clm.review_reason = "Name mentioned on company site but role not corroborated on team/bio page"
                                if company_src_id not in clm.source_ids:
                                    clm.source_ids.append(company_src_id)
                            else:
                                clm.status = "input_provided"
                                clm.confidence = 0.50
                                clm.review_reason = assoc_reason
                        elif clm.field == "job_title":
                            if role_verified:
                                clm.status = "verified"
                                clm.confidence = 0.85
                                if company_src_id not in clm.source_ids:
                                    clm.source_ids.append(company_src_id)
                            else:
                                clm.status = "unverified"
                                clm.confidence = 0.40
                                clm.review_reason = assoc_reason
                        elif clm.field == "professional_email":
                            if lead.professional_email and lead.professional_email.lower() in res.extracted_text.lower() and company_corroborated:
                                clm.status = "verified"
                                clm.confidence = 0.90
                                clm.review_reason = "Professional email corroborated on official company domain"
                                if company_src_id not in clm.source_ids:
                                    clm.source_ids.append(company_src_id)
                                if f"Email Corroborated: {lead.professional_email}" not in web_facts:
                                    web_facts.append(f"Email Corroborated: {lead.professional_email}")

                    researched_snippets.append(res.extracted_text)

                    sources.append(
                        SourceEvidence(
                            source_id=company_src_id,
                            source_url=res.url,
                            source_type="official_company",
                            title=res.title,
                            retrieval_timestamp=res.timestamp,
                            evidence_quality=0.90 if company_corroborated else 0.50,
                            relevant_excerpt=res.meta_description or res.extracted_text[:400],
                            facts_supported=web_facts,
                        )
                    )

                    # Update company claim with corroborated source
                    for clm in claims:
                        if clm.field == "company":
                            if company_corroborated:
                                clm.status = "verified"
                                clm.confidence = 0.95
                                if company_src_id not in clm.source_ids:
                                    clm.source_ids.append(company_src_id)
                            else:
                                clm.status = "unverified"
                                clm.confidence = 0.40
                                clm.review_reason = comp_reason

                    claims.append(
                        LeadClaim(
                            claim_id="clm_website",
                            field="company_website",
                            value=res.url,
                            status="verified" if company_corroborated else "unverified",
                            source_ids=[company_src_id],
                            confidence=0.95 if company_corroborated else 0.40,
                            review_reason="Verified official company website" if company_corroborated else comp_reason,
                        )
                    )

                    if log_fn:
                        t_preview = f' "{res.title[:45]}..."' if res.title else ""
                        log_fn(f"   ↳ [Status {res.status_code}] Extracted content from {res.url}{t_preview} ({res.engine})")
                else:
                    limitations.append(f"Company website notice for {company_site_url}: {res.error}")
                    if log_fn:
                        log_fn(f"   ↳ [Notice] Company website response: {res.error[:60]}")
            except Exception as e:
                limitations.append(f"Exception during web research on {company_site_url}: {str(e)}")
                if log_fn:
                    log_fn(f"   ↳ [Error] Company site error: {str(e)[:60]}")
        elif not company_site_url:
            limitations.append("No company website URL provided in lead record.")

        # 4. Identity-Filtered Targeted Public Search
        max_identity_score = 0.40
        matched_candidates = []
        if not skip_web_scrape and lead.name and lead.company:
            try:
                # Build targeted queries
                queries = build_targeted_queries(lead)
                primary_query = queries[0] if queries else f"{lead.name} {lead.company}"

                if log_fn:
                    log_fn(f"🧅 [Tor + DuckDuckGo] Searching '{primary_query}' via Tor SOCKS5...")

                raw_candidates = self.scraper.search_person(lead.name, lead.company, custom_query=primary_query)

                for cand in raw_candidates:
                    # Identity resolution check
                    m_score = identity_match_score(lead, cand)
                    if m_score >= 0.50:
                        matched_candidates.append((cand, m_score))
                        if m_score > max_identity_score:
                            max_identity_score = m_score
                    else:
                        logger.debug(f"Rejected candidate '{cand.get('title')}' for {lead.name}: score={m_score}")

                if log_fn:
                    log_fn(f"   ↳ [Tor Results] Found {len(raw_candidates)} results, {len(matched_candidates)} verified matches")

                top_candidate_fetched = False
                for idx, (cand, cand_score) in enumerate(matched_candidates[:4], 1):
                    src_id = f"src_bio_{lead.lead_id[:6]}_{idx}"
                    p_facts = [
                        f"Search Snippet: {cand['title']}",
                        f"Contextual Snippet: {cand['snippet'][:250]}",
                    ]
                    sources.append(
                        SourceEvidence(
                            source_id=src_id,
                            source_url=cand["url"],
                            source_type="search_snippet",
                            title=cand["title"],
                            retrieval_timestamp=datetime.now(timezone.utc).isoformat(),
                            evidence_quality=min(0.65, cand_score),
                            relevant_excerpt=cand["snippet"],
                            facts_supported=p_facts,
                        )
                    )
                    researched_snippets.append(cand["snippet"])
                    candidate_bio_snippets.append({
                        "source_id": src_id,
                        "title": cand["title"],
                        "url": cand["url"],
                        "snippet": cand["snippet"],
                    })

                    # If candidate strongly matched the person and company, update candidate bio evidence
                    if cand_score >= 0.70:
                        for clm in claims:
                            if clm.field == "name" and clm.status in ("input_provided", "unverified"):
                                if not is_abbreviated_name(lead.name):
                                    clm.status = "partially_verified"
                                    clm.confidence = max(clm.confidence, cand_score)
                                    if src_id not in clm.source_ids:
                                        clm.source_ids.append(src_id)
                                else:
                                    # Abbreviated name requires full surname corroboration; keep in review
                                    clm.status = "needs_review"
                                    clm.review_reason = "Surname is abbreviated; requires full name evidence"
                            elif clm.field == "job_title":
                                # Search snippets alone cannot verify current role; destination page inspection required
                                if src_id not in clm.source_ids:
                                    clm.source_ids.append(src_id)

                    # Fetch the top candidate source page to verify person and role against actual page content
                    cand_url = cand.get("url")
                    if cand_url and not skip_web_scrape and not top_candidate_fetched and cand_score >= 0.60:
                        try:
                            if log_fn:
                                log_fn(f"🌐 [Web Scraper] Inspecting candidate profile page: {cand_url}")
                            cand_res = self.scraper.fetch_url(cand_url)
                            if cand_res.success:
                                top_candidate_fetched = True
                                from urllib.parse import urlparse
                                cand_parsed = urlparse(cand_res.url)
                                cand_path = (cand_parsed.path or "").lower()
                                is_cand_bio = any(p in cand_path for p in ["/team", "/leadership", "/executives", "/management", "/about", "/people", "/profile", "/bio", "/speakers", "/author"]) or any(k in (cand_res.title or "").lower() for k in ["leadership", "executive", "team", "people", "profile", "bio"])

                                c_name_ver, c_role_ver, c_reason = check_person_role_association(
                                    person_name=lead.name or "",
                                    job_title=lead.job_title or "",
                                    text=cand_res.extracted_text,
                                    is_bio_page=is_cand_bio,
                                )

                                fetched_cand_src_id = f"src_bio_page_{lead.lead_id[:6]}_{idx}"
                                cand_facts = [
                                    f"Candidate Page Title: {cand_res.title}",
                                    f"Person Corroboration: {c_reason}",
                                ]
                                if c_role_ver:
                                    cand_facts.append(f"Role Verification: {c_reason}")

                                sources.append(
                                    SourceEvidence(
                                        source_id=fetched_cand_src_id,
                                        source_url=cand_res.url,
                                        source_type="biography" if is_cand_bio else "public_web_bio",
                                        title=cand_res.title,
                                        retrieval_timestamp=cand_res.timestamp,
                                        evidence_quality=0.85 if (c_name_ver and c_role_ver) else 0.70,
                                        relevant_excerpt=cand_res.extracted_text[:400],
                                        facts_supported=cand_facts,
                                    )
                                )
                                researched_snippets.append(cand_res.extracted_text)

                                if c_name_ver:
                                    for clm in claims:
                                        if clm.field == "name":
                                            clm.status = "verified"
                                            clm.confidence = 0.90
                                            if fetched_cand_src_id not in clm.source_ids:
                                                clm.source_ids.append(fetched_cand_src_id)
                                if c_role_ver:
                                    for clm in claims:
                                        if clm.field == "job_title":
                                            clm.status = "verified"
                                            clm.confidence = 0.85
                                            if fetched_cand_src_id not in clm.source_ids:
                                                clm.source_ids.append(fetched_cand_src_id)

                                if (c_name_ver or c_role_ver) and lead.professional_email and lead.professional_email.lower() in cand_res.extracted_text.lower():
                                    if f"Email Corroborated: {lead.professional_email}" not in cand_facts:
                                        cand_facts.append(f"Email Corroborated: {lead.professional_email}")
                                    for clm in claims:
                                        if clm.field == "professional_email":
                                            clm.status = "verified"
                                            clm.confidence = 0.90
                                            clm.review_reason = "Professional email corroborated on candidate profile page"
                                            if fetched_cand_src_id not in clm.source_ids:
                                                clm.source_ids.append(fetched_cand_src_id)
                            else:
                                limitations.append(f"Candidate source URL {cand_url} could not be retrieved: {cand_res.error}")
                        except Exception as c_err:
                            limitations.append(f"Exception fetching candidate page {cand_url}: {c_err}")

                if matched_candidates and log_fn:
                    top_cand, top_score = matched_candidates[0]
                    log_fn(f"   ↳ Top Match ({top_score:.2f}): {top_cand['title'][:45]}")

            except Exception as e:
                logger.debug(f"Public person search notice for {lead.name}: {e}")
                if log_fn:
                    log_fn(f"   ↳ [Search notice] {lead.name}: {str(e)[:50]}")

        # Removed company-fetch identity shortcut completely:
        # A homepage mention must not independently verify person identity, role, or raise identity score
        if not matched_candidates:
            max_identity_score = min(max_identity_score, 0.40)

        # 5. Public Signals & Icebreaker Synthesis
        public_signals = extract_public_signals(
            lead=lead,
            fetched_sources=sources,
            candidate_bio_snippets=candidate_bio_snippets,
        )

        # Enforce claim provenance validation before identity check and scoring:
        # Downgrades any verified claims lacking genuine corroborating evidence
        claims = validate_claims_provenance(claims, sources)

        # Verified identity requires a verified person claim backed by inspected source evidence
        # Numerical candidate-match score alone never verifies identity
        identity_verified = any(
            clm.field == "name" and clm.status == "verified" and bool(clm.source_ids)
            for clm in claims
        )
        icebreaker = build_icebreaker(
            lead=lead,
            signals=public_signals,
            sources=sources,
            identity_verified=identity_verified,
        )

        # 6. Synthesize Grounded Professional Context
        prof_context = self._synthesize_professional_context(
            lead=lead,
            sources=sources,
            snippets=researched_snippets,
            signals=public_signals,
        )

        # 7. Decoupled Scoring & Contact Readiness
        priority_info, scoring_breakdown, readiness = self.scorer.evaluate_lead(
            lead=lead,
            prof_context=prof_context,
            sources=sources,
            identity_score=max_identity_score,
            icebreaker=icebreaker,
            researched_text=" ".join(researched_snippets),
            claims=claims,
        )

        if log_fn:
            log_fn(
                f"⭐ [Scoring] {lead.name} -> Priority {priority_info.numeric_priority} "
                f"(Fit: {scoring_breakdown.lead_fit_score:.0f}, Readiness: {readiness.status})"
            )

        # 8. Cold Email Context (No hardcoded Tuesday dates, fact-grounded only)
        cold_email = self._synthesize_cold_email_context(lead, icebreaker, prof_context)

        # 9. Clean Identity Snapshot & Contact Record
        identity = {
            "name": lead.name,
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "job_title": lead.job_title,
            "company": lead.company,
            "industry": lead.industry,
            "linkedin_url": lead.linkedin_url,
            "company_website": lead.company_website,
            "professional_email": lead.professional_email,
            "city": lead.city,
            "state": lead.state,
            "country": lead.country,
        }

        email_claim = next((c for c in claims if c.field == "professional_email"), None)
        email_status = "missing"
        if lead.professional_email:
            if email_claim and email_claim.status == "verified":
                email_status = "corroborated_on_verified_source"
            elif email_claim and email_claim.status == "unverified":
                email_status = "syntax_invalid"
            else:
                email_status = "syntax_valid_unprobed"

        contact = {
            "email": lead.professional_email,
            "email_type": "work" if lead.professional_email and not any(f in lead.professional_email for f in ["@gmail.", "@yahoo.", "@hotmail."]) else "generic",
            "email_verification_status": email_status,
            "linkedin_url": lead.linkedin_url,
            "contact_channel_status": "available" if (lead.professional_email or lead.linkedin_url) else "missing",
        }

        company_dict = {
            "name": lead.company,
            "website": company_site_url,
            "final_url": company_final_url,
            "domain": extract_domain(company_site_url),
            "industry": lead.industry,
            "verified": bool(company_site_fetched and company_corroborated),
        }

        # 10. Honest Research & Execution Metadata
        if company_site_fetched and len(sources) >= 2:
            exec_status = "completed"
            verif_status = "verified" if max_identity_score >= 0.70 else "partially_verified"
        elif len(sources) > 1:
            exec_status = "partial"
            verif_status = "partially_verified"
        else:
            exec_status = "partial"
            verif_status = "unverified"

        metadata = ResearchMetadata(
            schema_version="2.0.0",
            pipeline_version="2.0.0",
            researched_at=now_iso,
            execution_status=exec_status,
            verification_status=verif_status,
            source_count=len(sources),
            review_required=bool(readiness.status in ("needs_research", "not_ready") or readiness.blockers),
            errors_and_limitations=limitations,
            research_status=exec_status,
            last_research_timestamp=now_iso,
            sources_examined=len(sources),
        )

        return LeadProfile(
            schema_version="2.0.0",
            lead_id=lead.lead_id,
            input_snapshot=lead.raw_data or dict(lead.model_dump()),
            identity=identity,
            contact=contact,
            company=company_dict,
            professional_context=prof_context,
            priority=priority_info,
            sources=sources,
            claims=claims,
            public_signals=public_signals,
            icebreaker=icebreaker,
            scoring=scoring_breakdown,
            contact_readiness=readiness,
            cold_email_context=cold_email,
            research_metadata=metadata,
        )

    def _synthesize_professional_context(
        self,
        lead: LeadInput,
        sources: List[SourceEvidence],
        snippets: List[str],
        signals: List[PublicSignal],
    ) -> ProfessionalContext:
        """Derive grounded responsibilities, tech interests, and SealAPI relevance."""
        title = (lead.job_title or "").lower()
        industry = (lead.industry or "").lower()
        comp = lead.company or "the organization"
        combined_text = f"{title} {industry} {' '.join(snippets)}".lower()

        responsibilities = []
        if any(k in title for k in ["cto", "chief technology officer", "head of ai", "chief ai officer"]):
            responsibilities.append(f"Architecting and directing AI strategy and core engineering infrastructure at {comp}")
            responsibilities.append("Evaluating enterprise technology vendors, API architectures, and data integrations")
        elif any(k in title for k in ["ciso", "security"]):
            responsibilities.append(f"Enforcing cybersecurity, data compliance, and API security policies across {comp}")
            responsibilities.append("Safeguarding sensitive data and managing third-party vendor access risk")
        elif any(k in title for k in ["ceo", "founder"]):
            responsibilities.append(f"Leading executive direction, product vision, and operational growth for {comp}")
        else:
            responsibilities.append(f"Managing technology operations and solution architecture at {comp}")

        # Highlights from verified public signals
        recent_devs = []
        for sig in signals:
            recent_devs.append(f"{sig.headline}: {sig.summary}")
        if not recent_devs:
            recent_devs.append(f"Active technical and executive oversight at {comp}")

        # Technical interests
        tech_interests = []
        if any(k in combined_text for k in ["ai", "machine learning", "llm", "agent", "generative"]):
            tech_interests.append("Generative AI & LLM Infrastructure")
        if any(k in combined_text for k in ["api", "cloud", "software", "microservices"]):
            tech_interests.append("API Security & Microservices")
        if any(k in combined_text for k in ["hipaa", "health", "hospital"]):
            tech_interests.append("Healthcare Data Privacy (HIPAA) & Safe Exchange")
        if any(k in combined_text for k in ["finance", "fintech", "banking"]):
            tech_interests.append("Financial Data Governance & Compliance")
        if not tech_interests:
            tech_interests.append("Enterprise Cloud Systems & Platform Scalability")

        public_projects = []
        if lead.company:
            public_projects.append(f"Platform development and operations for {lead.company}")

        # SealAPI Relevance
        use_cases = []
        evidence_points = []

        if any(k in title for k in ["ai", "cto", "ciso"]):
            use_cases.append("Secure AI Integration & LLM Guardrails")
            evidence_points.append(f"Role '{lead.job_title}' makes architecture decisions for emerging AI capabilities")

        if any(ind in industry for ind in ["health", "hospital", "financial", "banking", "insurance"]):
            use_cases.append("Privacy-Preserving Data Exchange & Compliance")
            evidence_points.append(f"Regulated vertical '{lead.industry}' mandates strict API access controls and audited data flow")

        if not use_cases:
            use_cases.append("Zero-Trust API Gateway & Enterprise Infrastructure Protection")
            evidence_points.append(f"Technology infrastructure at {comp} benefits from automated API defense and credentials security")

        summary = (
            f"Strong relevance to SealAPI for {lead.name} ({lead.job_title} at {comp}) to securely orchestrate APIs, "
            f"protect enterprise AI endpoints, and ensure strict compliance without operational bottlenecks."
        )

        return ProfessionalContext(
            responsibilities=responsibilities,
            technical_interests=tech_interests,
            public_projects=public_projects,
            recent_developments=recent_devs[:4],
            sealapi_relevance=SealAPIRelevance(
                summary=summary,
                relevant_use_cases=use_cases,
                evidence_points=evidence_points,
            ),
        )

    def _synthesize_cold_email_context(
        self,
        lead: LeadInput,
        icebreaker: Icebreaker,
        prof: ProfessionalContext,
    ) -> ColdEmailContext:
        """Create fact-grounded personalization hooks and value propositions without fake dates."""
        comp = lead.company or "your team"
        role = lead.job_title or "leadership"

        personalization = [
            f"Acknowledging leadership as {role} at {comp}.",
            f"Focus on {', '.join(prof.technical_interests[:2])}.",
        ]
        if icebreaker.text:
            personalization.append(f"Evidence-based opener: {icebreaker.text}")

        value_props = [
            "SealAPI provides automated security guardrails for AI models and API gateways.",
            f"Enables privacy-preserving data exchange tailored for {lead.industry or 'enterprise applications'}.",
            "Zero-trust credential shielding and audit-ready governance without slowing down developer velocity.",
        ]

        # Natural, low-pressure ask (NO fixed dates)
        cta = (
            icebreaker.conversation_question
            or f"Would you be open to a brief conversation to explore how SealAPI shields AI and API endpoints for teams like {comp}?"
        )

        claims_to_avoid = [
            "Do not claim existing commercial relationship or prior unrecorded discussions.",
            "Do not make unsubstantiated claims regarding internal vulnerabilities or specific budget numbers.",
            "Do not state specific private tech stack components that were not verified publicly.",
            "Do not assume delivered email address guarantees personal inbox delivery without validation.",
        ]

        missing = []
        if not lead.professional_email:
            missing.append("Verified email address pending confirmation.")
        if not lead.company_website:
            missing.append("Direct company domain needs manual review.")
        if icebreaker.personalization_status != "ready":
            missing.append(f"Icebreaker status: {icebreaker.personalization_status} (human review recommended).")

        return ColdEmailContext(
            verified_personalization_points=personalization,
            suggested_value_propositions=value_props,
            suggested_call_to_action=cta,
            claims_to_avoid=claims_to_avoid,
            missing_verification_points=missing,
        )
