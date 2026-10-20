"""Tests for CSV and JSON exporters, sorting, Unicode, and schema compliance."""

import csv
import json
from pathlib import Path
import pytest
from src.lead_research.exporter import LeadExporter, sanitize_filename
from src.lead_research.schemas import (
    ColdEmailContext,
    LeadInput,
    LeadProfile,
    PriorityInfo,
    ProfessionalContext,
    ResearchMetadata,
    SealAPIRelevance,
    SourceEvidence,
)


def test_sanitize_filename():
    assert sanitize_filename("Jane Doe") == "jane_doe"
    assert sanitize_filename("../../etc/passwd") == "etc_passwd"
    assert sanitize_filename("lead#123@special!chars") == "lead_123_special_chars"


def test_export_batch_sorting_and_json_schemas(tmp_path: Path):
    exporter = LeadExporter(tmp_path)

    # Lead 1: Priority 1
    lead1 = LeadInput(lead_id="lead_1", name="Alice Wonderland", job_title="Tech Lead", company="TechCorp")
    profile1 = LeadProfile(
        lead_id="lead_1",
        identity={"name": "Alice Wonderland", "job_title": "Tech Lead", "company": "TechCorp"},
        priority=PriorityInfo(numeric_priority=1, reason="Med fit", score=60.0),
        professional_context=ProfessionalContext(),
        cold_email_context=ColdEmailContext(),
        research_metadata=ResearchMetadata(research_status="completed", sources_examined=1),
    )

    # Lead 2: Priority 0
    lead2 = LeadInput(lead_id="lead_2", name="Bob The Builder", job_title="CISO", company="SecureCloud")
    profile2 = LeadProfile(
        lead_id="lead_2",
        identity={"name": "Bob The Builder", "job_title": "CISO", "company": "SecureCloud"},
        priority=PriorityInfo(numeric_priority=0, reason="High fit", score=90.0),
        professional_context=ProfessionalContext(),
        cold_email_context=ColdEmailContext(),
        research_metadata=ResearchMetadata(research_status="completed", sources_examined=2),
    )

    batch_id = "test_batch_001"
    paths = exporter.export_batch(
        batch_id=batch_id,
        leads_with_profiles=[(lead1, profile1), (lead2, profile2)],
        errors=[],
        batch_metadata={"test": True},
    )

    # Verify CSV was written and sorted: Priority 0 must be first!
    csv_file = Path(paths["csv_path"])
    assert csv_file.exists()

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 2
        assert reader[0]["lead_id"] == "lead_2"
        assert int(reader[0]["priority"]) == 0
        assert reader[1]["lead_id"] == "lead_1"
        assert int(reader[1]["priority"]) == 1

    # Verify per-person JSON profiles
    profiles_dir = Path(paths["profiles_dir"])
    json_files = list(profiles_dir.glob("*.json"))
    assert len(json_files) == 2

    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Must validate against schema
            validated = LeadProfile.model_validate(data)
            assert validated.schema_version == "1.0.0"
            assert validated.lead_id in ("lead_1", "lead_2")
            assert validated.priority.numeric_priority in (0, 1, 2)
