"""Lead-specific, evidence-grounded icebreaker and outreach draft generator.

Adheres strictly to the principles in fix.md:
1. Every ready icebreaker must reference verifiable source IDs.
2. Never claim an internal vulnerability, secret tech stack, or fabricated relationship.
3. If evidence is sparse or ambiguous, fall back cleanly to a professional question
   marked as 'generic_fallback'.
4. No hardcoded appointment dates (e.g. 'next Tuesday').
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from .schemas import (
    Icebreaker,
    LeadInput,
    PublicSignal,
    SealAPIRelevance,
    SourceEvidence,
)


def extract_public_signals(
    lead: LeadInput,
    fetched_sources: List[SourceEvidence],
    candidate_bio_snippets: List[Dict[str, str]],
) -> List[PublicSignal]:
    """
    Extract factual, verifiable signals from successfully fetched pages and validated sources.
    """
    signals: List[PublicSignal] = []
    comp = lead.company or "the company"

    # 1. Company Website Signals (Product Launches, Platform Capabilities)
    for src in fetched_sources:
        if src.source_type in ("company_website", "official_company", "company_blog", "official_company_blog"):
            text = (src.relevant_excerpt or " ".join(src.facts_supported)).lower()
            title = src.title or ""
            url_lower = src.source_url.lower()

            # Check if source is static API or developer documentation
            is_static_docs = any(d in url_lower for d in ["/docs", "/documentation", "/api-docs", "/api/docs", "/reference", "/developer", "/manual"]) or any(d in text for d in ["api documentation", "api reference", "sdk reference", "endpoint list"])

            # Robust launch / announcement patterns require inspected content (a URL path alone is never proof of launch)
            launch_pattern = r"\b(announc(e|ing|ed|ement|es)?|launch(ed|ing|es)?(\s+of)?|now\s+available|unveil(ed|ing|s)?|introduc(e|ing|ed|es)\s+our\s+new|press\s+release)\b"
            has_launch_event = not is_static_docs and bool(
                re.search(launch_pattern, text) or
                re.search(launch_pattern, title.lower())
            )

            # Check for AI / agent / LLM integration signal
            if re.search(r"\b(ai|agent|agents|llm|llms|generative ai|copilot|chatgpt|artificial intelligence|machine learning)\b", text):
                sig_type = "product_launch" if has_launch_event else "ai_capability"
                headline = (
                    f"Public announcement of AI capabilities at {comp}"
                    if has_launch_event
                    else f"AI and agentic capabilities on {comp}'s platform"
                )
                summary = (
                    f"{comp} publicly announced or introduced AI-driven features ('{title[:60]}')."
                    if has_launch_event
                    else f"{comp}'s official portal details AI-driven features and agent workflows ('{title[:60]}')."
                )
                signals.append(
                    PublicSignal(
                        signal_id=f"sig_{len(signals)+1}",
                        signal_type=sig_type,
                        headline=headline,
                        summary=summary,
                        source_ids=[src.source_id],
                        relevance_to_lead="Architecture and secure API access for AI workflows",
                        verification_status="verified",
                        confidence=0.90 if has_launch_event else 0.85,
                    )
                )

            # Check for API platform / integration signal
            elif any(k in text for k in ["api", "developer", "platform", "integrations", "sdk"]):
                signals.append(
                    PublicSignal(
                        signal_id=f"sig_{len(signals)+1}",
                        signal_type="product_integration",
                        headline=f"Extensible API and developer platform at {comp}",
                        summary=f"{comp} provides developer APIs and integrations documented publicly ('{title[:60]}').",
                        source_ids=[src.source_id],
                        relevance_to_lead="API security, token management, and integration defense",
                        verification_status="verified",
                        confidence=0.85,
                    )
                )

            # General corporate positioning
            elif title:
                signals.append(
                    PublicSignal(
                        signal_id=f"sig_{len(signals)+1}",
                        signal_type="company_positioning",
                        headline=f"Core market positioning for {comp}",
                        summary=f"{comp} public portal describes offerings: '{title[:70]}'.",
                        source_ids=[src.source_id],
                        relevance_to_lead="Operational scaling and digital service delivery",
                        verification_status="verified",
                        confidence=0.75,
                    )
                )

    # 2. Biographical / Leadership Public Signals
    tech_keywords = ["engineering", "architect", "cto", "infrastructure", "software", "developer", "platform", "security", "devops", "cloud", "systems", "technical"]
    for bio in candidate_bio_snippets:
        src_id = bio.get("source_id", "")
        snip = bio.get("snippet", "")
        bio_title = bio.get("title", "")
        if not snip or len(snip) < 30:
            continue

        combined_bio_text = f"{bio_title} {snip}".lower()
        has_tech_evidence = any(k in combined_bio_text for k in tech_keywords)

        if has_tech_evidence:
            signals.append(
                PublicSignal(
                    signal_id=f"sig_{len(signals)+1}",
                    signal_type="technical_work",
                    headline=f"Public technical profile for {lead.name}",
                    summary=f"Public records reference {lead.name}'s technical focus at {comp} ('{bio_title[:50]}').",
                    source_ids=[src_id] if src_id else [],
                    relevance_to_lead="Technology leadership and infrastructure oversight",
                    verification_status="partially_verified",
                    confidence=0.70,
                )
            )
        else:
            signals.append(
                PublicSignal(
                    signal_id=f"sig_{len(signals)+1}",
                    signal_type="professional_background",
                    headline=f"Public professional profile for {lead.name}",
                    summary=f"Public records reference {lead.name}'s professional background at {comp} ('{bio_title[:50]}').",
                    source_ids=[src_id] if src_id else [],
                    relevance_to_lead="Operational management and leadership",
                    verification_status="partially_verified",
                    confidence=0.60,
                )
            )

    return signals


def build_icebreaker(
    lead: LeadInput,
    signals: List[PublicSignal],
    sources: List[SourceEvidence],
    identity_verified: bool = False,
) -> Icebreaker:
    """
    Construct an evidence-grounded icebreaker or a clean professional fallback.
    """
    comp = lead.company or "your team"
    first_name = lead.first_name or (lead.name.split()[0] if lead.name else "there")
    industry = (lead.industry or "").lower()

    # 1. Evaluate eligible signals
    eligible_signals = [s for s in signals if s.source_ids and s.verification_status in ("verified", "partially_verified")]

    if eligible_signals and identity_verified:
        priority_order = {
            "product_launch": 5,
            "ai_capability": 4,
            "product_integration": 3,
            "technical_work": 2,
            "professional_background": 2,
            "company_positioning": 1,
        }
        best_signal = max(eligible_signals, key=lambda s: (priority_order.get(s.signal_type, 0), s.confidence))

        if best_signal.signal_type == "product_launch":
            text = (
                f"I noticed {comp}'s recent announcement regarding new AI and platform capabilities."
            )
            why_it_matters = (
                f"Teams expanding AI capabilities often face new operational challenges managing tool access, "
                f"session tokens, and data boundaries."
            )
            pain_point = (
                "Hypothesis: Ensuring third-party AI agents cannot inadvertently expose internal endpoints or credentials."
            )
            question = (
                "How is your team thinking about credential isolation and access control as these AI capabilities expand?"
            )
            icebreaker_type = "product_launch"

        elif best_signal.signal_type == "ai_capability":
            text = (
                f"I noticed {comp}'s focus on AI agents and platform workflows."
            )
            why_it_matters = (
                "Integrating AI agents with production APIs creates new requirements around token scoping and runtime guardrails."
            )
            pain_point = (
                "Hypothesis: Balancing developer velocity with strict zero-trust boundaries for agentic workflows."
            )
            question = (
                "How is your team approaching tool permissioning and secure API access for those AI workflows?"
            )
            icebreaker_type = "ai_capability"

        elif best_signal.signal_type == "product_integration":
            text = (
                f"I saw that {comp} actively supports developer APIs and third-party integrations as part of its core platform."
            )
            why_it_matters = (
                "Managing growing API surfaces requires robust authentication defense and token governance without adding latency."
            )
            pain_point = (
                "Hypothesis: Monitoring and protecting mission-critical API endpoints from automated credential scraping or abuse."
            )
            question = (
                "How do you currently ensure third-party integrations and internal services remain protected against credential misuse?"
            )
            icebreaker_type = "product_integration"

        elif best_signal.signal_type == "technical_work":
            # Check if leadership is actually corroborated
            lead_title = (lead.job_title or "").lower()
            is_leader = any(k in lead_title for k in ["vp", "director", "head", "lead", "chief", "manager", "principal"])
            if is_leader:
                text = f"I came across public coverage of your technical role at {comp}."
            else:
                text = f"I came across public details regarding your engineering work at {comp}."
            why_it_matters = (
                "Engineering organizations navigating rapid infrastructure growth benefit from automated security guardrails that don't block development."
            )
            pain_point = (
                "Hypothesis: Balancing developer velocity with rigorous zero-trust API protection."
            )
            question = (
                "Are zero-trust API gateways and automated credential protection active discussion topics on your engineering roadmap?"
            )
            icebreaker_type = "technical_work"

        elif best_signal.signal_type == "professional_background":
            text = f"I came across public professional records regarding your work at {comp}."
            why_it_matters = (
                f"As {comp} continues to expand digital services, establishing zero-trust access controls and protecting critical interfaces is essential."
            )
            pain_point = (
                "Hypothesis: Maintaining strict data integrity and governance across internal and customer-facing interfaces."
            )
            question = (
                "Is your team currently exploring automated security guardrails for production APIs this quarter?"
            )
            icebreaker_type = "professional_background"

        else:
            text = (
                f"I reviewed {comp}'s public offerings in {lead.industry or 'the technology space'}."
            )
            why_it_matters = (
                "Modern cloud and data-driven platforms rely on reliable API exchanges to deliver seamless customer experiences."
            )
            pain_point = (
                "Hypothesis: Maintaining strict data integrity across partner and client API touchpoints."
            )
            question = (
                "Is your team exploring new approaches to streamline API access governance and auditability this year?"
            )
            icebreaker_type = "company_positioning"

        status = "ready" if best_signal.confidence >= 0.70 and best_signal.verification_status == "verified" else "needs_review"
        icebreaker = Icebreaker(
            text=text,
            icebreaker_type=icebreaker_type,
            source_ids=best_signal.source_ids,
            confidence=best_signal.confidence,
            why_it_matters=why_it_matters,
            potential_pain_point=pain_point,
            conversation_question=question,
            personalization_status=status,
        )

    # 2. Industry-Specific Fallback if Identity or Specific Evidence is Partial
    elif any(ind in industry for ind in ["health", "hospital", "financial", "banking", "insurance", "fintech"]):
        source_id = sources[0].source_id if sources else "src_import"
        text = (
            f"Given {comp}'s focus in {lead.industry}, data privacy governance and auditable API exchanges are typically paramount."
        )
        why_it_matters = (
            "Regulated verticals require verifiable controls to ensure sensitive data does not cross unauthorized API boundaries."
        )
        pain_point = (
            "Hypothesis: Ensuring third-party integrations and internal models comply with strict compliance audits."
        )
        question = (
            "How does your team currently audit and safeguard sensitive API endpoints against unauthorized data exfiltration?"
        )
        icebreaker = Icebreaker(
            text=text,
            icebreaker_type="general_question",
            source_ids=[source_id],
            confidence=0.60,
            why_it_matters=why_it_matters,
            potential_pain_point=pain_point,
            conversation_question=question,
            personalization_status="needs_review",
        )

    # 3. Clean Professional Generic Fallback
    else:
        source_id = sources[0].source_id if sources else "src_import"
        text = (
            f"I have been following how technology teams in the {lead.industry or 'enterprise software'} sector are managing API and AI endpoint security."
        )
        why_it_matters = (
            "SealAPI helps organizations protect APIs from token leakage, prompt injection, and credential abuse with zero-trust gateways."
        )
        pain_point = (
            "Hypothesis: Preventing credential leakage and unauthorized API consumption in production."
        )
        question = (
            "Would you be open to a brief exchange on how engineering teams automate API token shielding without introducing latency?"
        )
        icebreaker = Icebreaker(
            text=text,
            icebreaker_type="general_question",
            source_ids=[source_id],
            confidence=0.45,
            why_it_matters=why_it_matters,
            potential_pain_point=pain_point,
            conversation_question=question,
            personalization_status="generic_fallback",
        )

    # Attach cold outreach draft
    icebreaker.outreach_draft = create_outreach_draft(lead, icebreaker)
    return icebreaker


def create_outreach_draft(lead: LeadInput, icebreaker: Icebreaker) -> Dict[str, str]:
    """
    Format a complete, natural, and low-pressure first-contact email draft.
    """
    first_name = lead.first_name or (lead.name.split()[0] if lead.name else "there")
    comp = lead.company or "your organization"

    subject = f"API security & AI infrastructure at {comp}"
    greeting = f"Hi {first_name},"
    opener = icebreaker.text or f"I came across {comp}'s recent work in {lead.industry or 'technology'}."
    value_conn = (
        f"At SealAPI, we help engineering teams implement zero-trust credential shielding, "
        f"protect API gateways, and establish strict runtime guardrails for AI endpoints."
    )
    ask = icebreaker.conversation_question or "Would you be open to comparing notes on how other engineering teams tackle this?"
    sign_off = "Best regards,\nSealAPI Research & Partnerships"

    body = f"{greeting}\n\n{opener}\n\n{value_conn}\n\n{ask}\n\n{sign_off}"

    return {
        "subject": subject,
        "greeting": greeting,
        "opener": opener,
        "sealapi_connection": value_conn,
        "low_pressure_ask": ask,
        "full_body": body,
    }
