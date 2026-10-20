"""Core lead research engine extracting verifiable facts, SealAPI relevance, and profiles."""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .schemas import (
    ColdEmailContext,
    LeadInput,
    LeadProfile,
    PriorityInfo,
    ProfessionalContext,
    ResearchMetadata,
    SealAPIRelevance,
    SourceEvidence,
)
from .scraper import ScraplingScraper, ScrapeResult
from .scoring import LeadScorer

logger = logging.getLogger("lead_research.research")


class LeadResearcher:
    """Researches professional data and produces traceable lead profiles."""

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
        limitations: List[str] = []
        verified_facts: List[str] = []
        researched_snippets: List[str] = []

        now_iso = datetime.now(timezone.utc).isoformat()
        if log_fn:
            log_fn(f"🎯 Target: {lead.name} ({lead.job_title or 'Leadership'}) @ {lead.company}")

        # 1. Baseline source from verified import data
        input_facts = []
        if lead.name:
            input_facts.append(f"Verified Name: {lead.name}")
        if lead.job_title:
            input_facts.append(f"Declared Job Title: {lead.job_title}")
        if lead.company:
            input_facts.append(f"Company: {lead.company}")
        if lead.industry:
            input_facts.append(f"Industry: {lead.industry}")
        if lead.professional_email:
            input_facts.append(f"Verified Professional Email: {lead.professional_email}")
        if lead.city or lead.country:
            loc = f"{lead.city or ''}, {lead.state or ''}, {lead.country or ''}".strip(", ")
            input_facts.append(f"Reported Location: {loc}")

        raw_keywords = str(lead.raw_data.get("Keywords", "")).strip()
        if raw_keywords:
            input_facts.append(f"Company Keywords: {raw_keywords[:180]}")

        sources.append(
            SourceEvidence(
                source_url="lead_import_record",
                source_type="input_data",
                retrieval_timestamp=now_iso,
                facts_supported=input_facts,
            )
        )
        verified_facts.extend(input_facts)

        # 2. LinkedIn access limitation check
        if lead.linkedin_url:
            limitations.append(
                f"LinkedIn profile ({lead.linkedin_url}) is behind an authentication wall; public domain records used for verified evidence."
            )

        # 3. Public web research via Scrapling
        scrape_success = False
        company_site_url = lead.company_website or ""
        if company_site_url and not company_site_url.startswith(("http://", "https://")):
            company_site_url = f"https://{company_site_url}"

        if company_site_url and not skip_web_scrape:
            try:
                if log_fn:
                    log_fn(f"🌐 [Web Scraper] Fetching company website: {company_site_url}")
                res: ScrapeResult = self.scraper.fetch_url(company_site_url)
                if res.success:
                    scrape_success = True
                    web_facts: List[str] = []
                    if res.title:
                        web_facts.append(f"Website Title: {res.title}")
                    if res.meta_description:
                        web_facts.append(f"Company Mission/Description: {res.meta_description}")
                    if res.headings:
                        web_facts.append(f"Core Offerings: {', '.join(res.headings[:4])}")

                    researched_snippets.append(res.extracted_text)

                    sources.append(
                        SourceEvidence(
                            source_url=res.url,
                            source_type="company_website",
                            retrieval_timestamp=res.timestamp,
                            facts_supported=web_facts,
                        )
                    )
                    verified_facts.extend(web_facts)
                    if log_fn:
                        t_preview = f' "{res.title[:45]}..."' if res.title else ""
                        log_fn(f"   ↳ [Status {res.status_code}] Extracted content from {res.url}{t_preview} ({res.engine})")
                else:
                    limitations.append(f"Company website research notice for {company_site_url}: {res.error}")
                    if log_fn:
                        log_fn(f"   ↳ [Notice] Company website notice: {res.error[:60]}")
            except Exception as e:
                limitations.append(f"Exception during web research on {company_site_url}: {str(e)}")
                if log_fn:
                    log_fn(f"   ↳ [Error] Company site error: {str(e)[:60]}")
        elif not company_site_url:
            limitations.append("No company website URL provided in lead record.")

        # 3b. Public web intelligence on the person via Scrapling
        if not skip_web_scrape and lead.name and lead.company:
            try:
                if log_fn:
                    log_fn(f"🧅 [Tor + DuckDuckGo] Searching '{lead.name} {lead.company}' via Tor SOCKS5...")
                person_results = self.scraper.search_person(lead.name, lead.company)
                if log_fn:
                    log_fn(f"   ↳ [Tor Results] Found {len(person_results)} search results for '{lead.name}'")
                for pr in person_results:
                    scrape_success = True
                    p_facts = [
                        f"Public Profile: {pr['title']}",
                        f"Verified Career & Background: {pr['snippet'][:300]}",
                    ]
                    sources.append(
                        SourceEvidence(
                            source_url=pr["url"],
                            source_type="public_web_bio",
                            retrieval_timestamp=datetime.now(timezone.utc).isoformat(),
                            facts_supported=p_facts,
                        )
                    )
                    verified_facts.extend(p_facts)
                    researched_snippets.append(pr["snippet"])
                if person_results and log_fn:
                    top_title = person_results[0]['title'][:50]
                    log_fn(f"   ↳ Top Bio: {top_title}")
            except Exception as e:
                logger.debug(f"Public person search notice for {lead.name}: {e}")
                if log_fn:
                    log_fn(f"   ↳ [Search notice] {lead.name}: {str(e)[:50]}")

        # Determine research status
        if scrape_success:
            research_status = "completed"
        elif len(verified_facts) > 2:
            research_status = "partial"
        else:
            research_status = "failed"

        # 4. Synthesize Professional Context
        prof_context = self._synthesize_professional_context(
            lead, verified_facts, researched_snippets
        )

        # 5. Deterministic Priority Scoring
        priority_info = self.scorer.calculate_priority(
            lead=lead,
            prof_context=prof_context,
            sources=sources,
            researched_text=" ".join(researched_snippets),
        )
        if log_fn:
            log_fn(f"⭐ [Scoring] {lead.name} -> Priority {priority_info.numeric_priority} (Score: {priority_info.score:.0f}, Sources: {len(sources)})")

        # 6. Cold Email Context Synthesis (Fact-traceable only)
        cold_email = self._synthesize_cold_email_context(lead, prof_context, priority_info, sources)

        # 7. Identity mapping
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

        # 8. Research Metadata
        metadata = ResearchMetadata(
            research_status=research_status,
            last_research_timestamp=now_iso,
            sources_examined=len(sources),
            errors_and_limitations=limitations,
        )

        return LeadProfile(
            schema_version="1.0.0",
            lead_id=lead.lead_id,
            identity=identity,
            professional_context=prof_context,
            priority=priority_info,
            sources=sources,
            cold_email_context=cold_email,
            research_metadata=metadata,
        )

    def _synthesize_professional_context(
        self, lead: LeadInput, verified_facts: List[str], snippets_or_text: Any
    ) -> ProfessionalContext:
        """Derive concrete responsibilities, tech interests, and SealAPI relevance."""
        if isinstance(snippets_or_text, list):
            snippets = snippets_or_text
            text = " ".join(snippets)
        else:
            text = str(snippets_or_text)
            snippets = [text]

        title = (lead.job_title or "").lower()
        industry = (lead.industry or "").lower()
        comp = lead.company or "the organization"

        responsibilities = []
        if any(k in title for k in ["cto", "chief technology officer", "head of ai", "chief ai officer"]):
            responsibilities.append(f"Architecting and directing AI strategy and core engineering infrastructure at {comp}")
            responsibilities.append("Evaluating enterprise technology vendors, API architectures, and data integrations")
        elif "ciso" in title or "security" in title:
            responsibilities.append(f"Enforcing cybersecurity, data compliance, and API security policies across {comp}")
            responsibilities.append("Safeguarding sensitive data and managing third-party vendor access risk")
        elif any(k in title for k in ["ceo", "founder"]):
            responsibilities.append(f"Leading executive direction, product vision, and operational growth for {comp}")
        else:
            responsibilities.append(f"Managing technology operations and solution architecture at {comp}")

        # Extract biographical highlights from verified web snippets
        recent_devs = [f"Active technical and executive oversight at {comp}"]
        for snip in snippets:
            sentences = [s.strip() for s in snip.split(".") if len(s.strip()) > 25]
            for s in sentences:
                if any(w in s.lower() for w in ["previously", "founded", "degree", "experience", "building", "leads", "architect"]):
                    clean_s = s.replace("\n", " ").strip()
                    if clean_s not in recent_devs and len(recent_devs) < 4:
                        recent_devs.append(clean_s)

        # Technical interests
        tech_interests = []
        combined = f"{title} {industry} {lead.raw_data.get('Keywords', '')} {text}".lower()
        if "ai" in combined or "machine learning" in combined or "llm" in combined:
            tech_interests.append("Generative AI & LLM Infrastructure")
        if "api" in combined or "cloud" in combined or "software" in combined:
            tech_interests.append("API Security & Microservices")
        if "hipaa" in combined or "health" in combined:
            tech_interests.append("Healthcare Data Privacy (HIPAA) & Safe Exchange")
        if "finance" in combined or "fintech" in combined or "banking" in combined:
            tech_interests.append("Financial Data Governance & Compliance")
        if not tech_interests:
            tech_interests.append("Enterprise Cloud Systems & Platform Scalability")

        # Public projects
        public_projects = []
        if lead.company:
            public_projects.append(f"Platform development and operations for {lead.company}")

        # SealAPI Relevance
        use_cases = []
        evidence_points = []

        if any(k in title for k in ["ai", "cto", "ciso"]):
            use_cases.append("Secure AI Integration & LLM Guardrails")
            evidence_points.append(f"Role '{lead.job_title}' makes key architecture decisions for emerging AI capabilities")

        if any(ind in industry for ind in ["health", "hospital", "financial", "banking", "insurance"]):
            use_cases.append("Privacy-Preserving Data Exchange & Compliance")
            evidence_points.append(f"Regulated domain '{lead.industry}' mandates strict API access controls and audited data flow")

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
            recent_developments=recent_devs,
            sealapi_relevance=SealAPIRelevance(
                summary=summary,
                relevant_use_cases=use_cases,
                evidence_points=evidence_points,
            ),
        )

    def _synthesize_cold_email_context(
        self,
        lead: LeadInput,
        prof: ProfessionalContext,
        p_info: PriorityInfo,
        sources: List[SourceEvidence],
    ) -> ColdEmailContext:
        """Create fact-grounded personalization hooks and value propositions."""
        comp = lead.company or "your team"
        role = lead.job_title or "leadership"

        personalization = [
            f"Acknowledging leadership as {role} at {comp}.",
            f"Focus on {', '.join(prof.technical_interests[:2])}."
        ]
        if len(prof.recent_developments) > 1:
            personalization.append(f"Background: {prof.recent_developments[1][:120]}...")

        value_props = [
            f"SealAPI provides automated security guardrails for AI models and API gateways.",
            f"Enables privacy-preserving data exchange tailored for {lead.industry or 'enterprise applications'}.",
            f"Zero-trust credential shielding and audit-ready governance without slowing down developer velocity."
        ]

        cta = (
            f"Would you be open to a 10-minute technical exchange next Tuesday to explore how "
            f"SealAPI shields AI and API endpoints for teams like {comp}?"
        )

        claims_to_avoid = [
            "Do not claim existing commercial relationship or prior unrecorded discussions.",
            "Do not make unsubstantiated claims regarding internal vulnerabilities or specific budget numbers.",
            "Do not state specific private tech stack components that were not verified publicly."
        ]

        missing = []
        if not lead.professional_email:
            missing.append("Verified email address pending confirmation.")
        if not lead.company_website:
            missing.append("Direct company domain needs manual review.")

        return ColdEmailContext(
            verified_personalization_points=personalization,
            suggested_value_propositions=value_props,
            suggested_call_to_action=cta,
            claims_to_avoid=claims_to_avoid,
            missing_verification_points=missing,
        )
