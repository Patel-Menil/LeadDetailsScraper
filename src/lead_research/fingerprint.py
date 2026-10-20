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


def research_fingerprint(
    lead_input: Dict[str, Any],
    pipeline_version: str = "2.0.0",
    schema_version: str = "2.0.0",
    research_config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generate deterministic SHA-256 fingerprint of input data and pipeline configuration.
    Ensures cached research is only reused when inputs, versions, and configs match.
    """
    clean_lead = {
        "name": str(lead_input.get("name") or "").strip().lower(),
        "first_name": str(lead_input.get("first_name") or "").strip().lower(),
        "last_name": str(lead_input.get("last_name") or "").strip().lower(),
        "company": str(lead_input.get("company") or "").strip().lower(),
        "job_title": str(lead_input.get("job_title") or "").strip().lower(),
        "company_website": str(lead_input.get("company_website") or "").strip().lower(),
        "professional_email": str(lead_input.get("professional_email") or "").strip().lower(),
        "linkedin_url": str(lead_input.get("linkedin_url") or "").strip().lower(),
        "industry": str(lead_input.get("industry") or "").strip().lower(),
        "keywords": str(lead_input.get("keywords") or lead_input.get("Keywords") or "").strip().lower(),
        "city": str(lead_input.get("city") or "").strip().lower(),
        "state": str(lead_input.get("state") or "").strip().lower(),
        "country": str(lead_input.get("country") or "").strip().lower(),
    }
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
