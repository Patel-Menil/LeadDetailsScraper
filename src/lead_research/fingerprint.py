"""Batch ID generation, input hashing, and cache fingerprinting."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4


def create_batch_id() -> str:
    """Generate a unique UTC timestamp and random suffix batch ID."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid4().hex[:8]
    return f"batch_{timestamp}_{suffix}"


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of an input file for provenance tracking."""
    if not file_path.exists():
        return ""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


HEADER_ALIASES = {
    "name": ["name", "full name", "lead name", "contact name", "person", "full_name"],
    "first_name": ["first name", "firstname", "first_name", "given name"],
    "last_name": ["last name", "lastname", "last_name", "surname"],
    "job_title": ["job title", "job_title", "title", "position", "role"],
    "company": ["company", "company name", "company_name", "organization", "account name"],
    "industry": ["industry", "vertical", "sector", "domain"],
    "linkedin_url": ["linkedin url", "linkedin", "linkedin_url", "person linkedin url", "profile url", "profile_url"],
    "company_website": ["company website", "company_website", "website", "company domain", "domain", "url"],
    "professional_email": ["professional email", "email", "email address", "work email", "contact email", "e-mail"],
    "keywords": ["keywords", "tags", "tech stack", "technologies"],
    "city": ["city", "person city", "location city"],
    "state": ["state", "province", "region", "person state"],
    "country": ["country", "nation", "person country"],
}


def normalize_lead_data(lead_input: Any) -> Dict[str, str]:
    """Normalize input lead data from either a canonical LeadInput model or a raw CSV dict with header aliases."""
    import re
    if hasattr(lead_input, "model_dump"):
        d = lead_input.model_dump()
    elif isinstance(lead_input, dict):
        d = dict(lead_input)
    else:
        d = {}

    # Build lookup of normalized raw keys
    normalized_keys_map: Dict[str, str] = {}
    for k, v in d.items():
        norm_k = re.sub(r"[_\-\s]+", " ", str(k).strip().lower())
        normalized_keys_map[norm_k] = str(v or "").strip().lower()

    clean_lead: Dict[str, str] = {}
    for std_key, aliases in HEADER_ALIASES.items():
        val = ""
        # Direct check on dictionary
        if std_key in d and d[std_key] is not None and str(d[std_key]).strip():
            val = str(d[std_key]).strip().lower()
        else:
            for alias in aliases:
                if alias in normalized_keys_map and normalized_keys_map[alias]:
                    val = normalized_keys_map[alias]
                    break
        clean_lead[std_key] = val

    # Derive name / first_name / last_name consistency
    if not clean_lead["name"] and (clean_lead["first_name"] or clean_lead["last_name"]):
        clean_lead["name"] = f"{clean_lead['first_name']} {clean_lead['last_name']}".strip()
    elif clean_lead["name"] and not clean_lead["first_name"] and not clean_lead["last_name"]:
        parts = clean_lead["name"].split()
        if len(parts) == 1:
            clean_lead["first_name"] = parts[0]
        elif len(parts) > 1:
            clean_lead["first_name"] = parts[0]
            clean_lead["last_name"] = " ".join(parts[1:])

    return clean_lead


def research_fingerprint(
    lead_input: Any,
    pipeline_version: str = "2.0.0",
    schema_version: str = "2.0.0",
    research_config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generate deterministic SHA-256 fingerprint of input data and pipeline configuration.
    Ensures cached research is only reused when inputs, versions, and configs match.
    Normalizes raw CSV header variants (e.g. 'Full Name', 'Company Name', 'Job Title').
    """
    clean_lead = normalize_lead_data(lead_input)
    payload = {
        "lead_input": clean_lead,
        "pipeline_version": pipeline_version,
        "schema_version": schema_version,
        "research_config": research_config or {},
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
