"""
Deterministic AI-usage tagging for Individual Research.

Every AI-related sentence on a company's fetched pages is tagged with its type (generative, agentic,
predictive, retrieval), purpose, stage and context. Rules are keyword patterns; each tag is shown with
the quoted sentence it came from, so a reader can check it. No network access, no LLM.
"""

import re
from typing import Dict, Iterable, List, Optional

# A sentence must match this to count as AI-related. "AI" is case-sensitive so words like "again" don't match.
_AI_UPPER = re.compile(r"(?<![A-Za-z])A\.?I\.?(?![A-Za-z])")
_AI_TERMS = re.compile(
    r"\b(artificial intelligence|machine learning|deep learning|neural networks?|llms?|large language models?|"
    r"chatgpt|gpt[- ]?\d*|gen ?ai|generative|copilots?|chatbots?|ai agents?|agentic|nlp|natural language processing|"
    r"computer vision|embeddings?|vector (search|database|store)s?|rag|retrieval[- ]augmented|openai|anthropic|"
    r"claude|gemini|llama|mistral)\b",
    re.I,
)

TYPE_ORDER = ["generative", "agentic", "predictive", "retrieval", "general"]
TYPE_LABELS = {
    "generative": "Generative",
    "agentic": "Agentic",
    "predictive": "Predictive / analytical ML",
    "retrieval": "Retrieval / search",
    "general": "General AI (type unclear)",
}
_TYPE_RULES = {
    "generative": r"\bgenerat\w*|\bgen ?ai\b|\bdraft\w*|\bsummar\w*|\b(re)?writ(e|es|ing)\b|\bcopilots?\b|\bchat\w*|"
                  r"\bconversational\b|\btext[- ]to[- ]\w+|\bcompos(e|es|ing)\b|\banswers? (questions|queries)\b|"
                  r"\bllms?\b|\blarge language models?\b|\bgpt\b|\bcontent creation\b|\bassistants?\b",
    "agentic": r"\bagentic\b|\bai agents?\b|\bagents? (that|which|can|to|will)\b|\bautonomous(ly)?\b|\bmulti[- ]step\b|"
               r"\btakes? actions?\b|\btool[- ](use|calling|calls)\b|\bfunction calling\b|\bmcp\b|"
               r"\bmodel context protocol\b|\bon (your|their) behalf\b|\borchestrat\w*",
    "predictive": r"\bpredict\w*|\bforecast\w*|\banomal\w*|\bfraud\b|\brisk scor\w*|\bscor(e|es|ing)\b|\brecommend\w*|"
                  r"\bclassif\w*|\bdetect\w*|\bpersonali[sz]\w*|\bchurn\b|\bpropensity\b|\bcomputer vision\b|"
                  r"\bimage recognition\b|\bocr\b",
    "retrieval": r"\bsemantic search\b|\bvector\w*|\bembeddings?\b|\bretriev\w*|\brag\b|\bknowledge (base|graph)s?\b|"
                 r"\benterprise search\b|\bsearch across\b|"
                 r"\banswers? (from|based on) (your|their) (docs|documents|data|content|knowledge)\b|\bgrounded\b",
}

PURPOSE_ORDER = ["customer_support", "coding", "content_marketing", "search_knowledge", "analytics", "security_fraud",
                 "sales_crm", "workflow_automation", "document_processing", "other"]
PURPOSE_LABELS = {
    "customer_support": "Customer support",
    "coding": "Coding / developer tools",
    "content_marketing": "Content & marketing",
    "search_knowledge": "Search & knowledge",
    "analytics": "Analytics & insights",
    "security_fraud": "Security & fraud",
    "sales_crm": "Sales & CRM",
    "workflow_automation": "Workflow automation",
    "document_processing": "Document processing",
    "other": "Other",
}
_PURPOSE_RULES = {
    "customer_support": r"\bcustomer (support|service|success|experience)\b|\bhelp ?desk\b|\bsupport tickets?\b|"
                        r"\btickets?\b|\bcontact cent(er|re)s?\b|\bcall cent(er|re)s?\b",
    "coding": r"\bcod(e|es|ing)\b|\bdevelopers?\b|\bsoftware engineer\w*|\bpull requests?\b|\bides?\b|\bdebug\w*|"
              r"\bprogramming\b",
    "content_marketing": r"\bmarketing\b|\bcontent\b|\bcopywriting\b|\bblog posts?\b|\bsocial media\b|\bcampaigns?\b|"
                         r"\bseo\b|\bad (copy|creative)s?\b|\bbrand\w*",
    "search_knowledge": r"\bsearch\w*|\bknowledge\b|\bdocumentation\b|\bdocs\b|\banswers?\b|\bwiki\b|\bq&a\b",
    "analytics": r"\banalytic\w*|\binsights?\b|\bdashboards?\b|\breporting\b|\breports?\b|\bmetrics\b|"
                 r"\bbusiness intelligence\b|\bdata analysis\b|\bforecast\w*",
    "security_fraud": r"\bsecurity\b|\bfraud\b|\bthreats?\b|\brisks?\b|\bcompliance\b|\bvulnerab\w*|\banomal\w*|"
                      r"\bphishing\b|\bmalware\b",
    "sales_crm": r"\bsales\b|\bcrm\b|\bleads?\b|\bprospect\w*|\bpipelines? (of|for) (deals|leads)\b|\brevenue\b|"
                 r"\bdeals?\b|\boutreach\b",
    "workflow_automation": r"\bautomat\w*|\bworkflows?\b|\boperations\b|\bback[- ]office\b|\btasks?\b",
    "document_processing": r"\bdocuments?\b|\bpdfs?\b|\binvoices?\b|\bcontracts?\b|\bforms\b|\bocr\b|"
                           r"\bextract\w* data\b|\bpaperwork\b|\btranscri\w*",
}
_COMPILED_TYPES = {k: re.compile(v, re.I) for k, v in _TYPE_RULES.items()}
_COMPILED_PURPOSES = {k: re.compile(v, re.I) for k, v in _PURPOSE_RULES.items()}

_BETA = re.compile(r"\b(beta|early access|public preview|private preview|in preview|preview (release|program)|"
                   r"experimental)\b", re.I)
_GA = re.compile(r"\b(generally available|general availability|now available|available now|available today|"
                 r"now live|is live|launched|now shipping)\b", re.I)

CONTEXT_KEYS = ["product", "hiring_internal", "company"]
_PRODUCT_CATEGORIES = {"products", "ai", "developer", "integrations", "homepage"}
_PAGE_PRIORITY = ["ai", "products", "homepage", "developer", "integrations", "news", "about", "security", "careers"]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
MAX_EVIDENCE = 280


def is_ai_sentence(sentence: str) -> bool:
    return bool(_AI_UPPER.search(sentence or "") or _AI_TERMS.search(sentence or ""))


def tag_ai_text(text: str) -> Dict[str, object]:
    """Type, purpose and stage tags for one AI-related piece of text."""
    text = text or ""
    types = [t for t in TYPE_ORDER[:-1] if _COMPILED_TYPES[t].search(text)] or ["general"]
    purposes = [p for p in PURPOSE_ORDER[:-1] if _COMPILED_PURPOSES[p].search(text)] or ["other"]
    stage = "beta" if _BETA.search(text) else "ga" if _GA.search(text) else "unspecified"
    return {"types": types, "purposes": purposes, "stage": stage}


def page_context(category: str) -> str:
    if category == "careers":
        return "hiring_internal"
    return "product" if category in _PRODUCT_CATEGORIES else "company"


def _snippet(sentence: str) -> str:
    s = re.sub(r"\s+", " ", sentence).strip()
    return s if len(s) <= MAX_EVIDENCE else s[:MAX_EVIDENCE - 1].rstrip() + "…"


def _key(sentence: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()


def _priority(page: dict) -> int:
    cat = page.get("category") or ""
    return _PAGE_PRIORITY.index(cat) if cat in _PAGE_PRIORITY else len(_PAGE_PRIORITY)


def extract_ai_use_cases(
    pages: Iterable[dict],
    product_names: Optional[Dict[str, str]] = None,
    per_page: int = 4,
    total: int = 20,
) -> List[dict]:
    """Tagged AI sentences from fetched pages: AI and product pages first, then the rest."""
    product_names = product_names or {}
    out: List[dict] = []
    seen: set = set()
    usable = [p for p in pages or [] if isinstance(p, dict) and p.get("success")]
    for page in sorted(usable, key=_priority):
        if len(out) >= total:
            break
        url = page.get("url") or ""
        product = product_names.get(page.get("normalized_url") or url) or product_names.get(url) or ""
        text = f"{page.get('meta_description') or ''}\n{page.get('text') or ''}"
        taken = 0
        for raw in _SENTENCE_SPLIT.split(text):
            sentence = raw.strip()
            if len(sentence) < 20 or not is_ai_sentence(sentence):
                continue
            key = _key(sentence)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "evidence": _snippet(sentence),
                **tag_ai_text(sentence),
                "context": page_context(page.get("category") or ""),
                "product": product,
                "source_url": url,
                "page_title": (page.get("title") or "")[:160],
            })
            taken += 1
            if taken >= per_page or len(out) >= total:
                break
    return out


def summarize_ai_usage(use_cases: List[dict], providers: List[str]) -> dict:
    type_counts = {t: 0 for t in TYPE_ORDER}
    purpose_counts = {p: 0 for p in PURPOSE_ORDER}
    contexts = {c: 0 for c in CONTEXT_KEYS}
    stages = set()
    for c in use_cases or []:
        for t in c.get("types") or []:
            if t in type_counts:
                type_counts[t] += 1
        for p in c.get("purposes") or []:
            if p in purpose_counts:
                purpose_counts[p] += 1
        if c.get("context") in contexts:
            contexts[c["context"]] += 1
        stages.add(c.get("stage"))
    specific = [t for t in TYPE_ORDER[:-1] if type_counts[t]]
    if specific:
        primary = max(specific, key=lambda t: (type_counts[t], -TYPE_ORDER.index(t)))
    else:
        primary = "general" if type_counts["general"] else ""
    purposes = sorted((p for p in PURPOSE_ORDER if purpose_counts[p]),
                      key=lambda p: (-purpose_counts[p], PURPOSE_ORDER.index(p)))[:5]
    return {
        "type_counts": type_counts,
        "primary_type": primary,
        "purposes": [{"purpose": p, "label": PURPOSE_LABELS[p], "count": purpose_counts[p]} for p in purposes],
        "stage": "ga" if "ga" in stages else "beta" if "beta" in stages else "unspecified",
        "contexts": contexts,
        "providers": list(providers or []),
    }
