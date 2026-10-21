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
            assert validated.schema_version in ("1.0.0", "2.0.0")
            assert validated.lead_id in ("lead_1", "lead_2")
            assert validated.priority.numeric_priority in (0, 1, 2)


def test_export_batch_immutability_completed_partial_failed(tmp_path: Path):
    exporter = LeadExporter(output_base_dir=tmp_path / "batches")
    lead = LeadInput(lead_id="lead_1", name="Test Lead", company="Acme")
    profile = LeadProfile(
        schema_version="2.0.0",
        lead_id="lead_1",
        identity={"name": "Test Lead"},
        priority=PriorityInfo(numeric_priority=1, reason="Test", score=50.0),
        research_metadata=ResearchMetadata(research_status="completed", sources_examined=1),
    )

    for status in ("completed", "finalized", "partial", "failed"):
        batch_id = f"batch_{status}_001"
        b_dir = tmp_path / "batches" / batch_id
        b_dir.mkdir(parents=True, exist_ok=True)
        manifest = b_dir / "manifest.json"
        manifest.write_text(json.dumps({"batch_id": batch_id, "status": status}), encoding="utf-8")

        with pytest.raises(ValueError, match="immutable"):
            exporter.export_batch(batch_id=batch_id, leads_with_profiles=[(lead, profile)], allow_overwrite=False)


def test_export_batch_corrupted_manifest_rejected(tmp_path: Path):
    exporter = LeadExporter(output_base_dir=tmp_path / "batches")
    batch_id = "batch_corrupted_001"
    b_dir = tmp_path / "batches" / batch_id
    b_dir.mkdir(parents=True, exist_ok=True)
    manifest = b_dir / "manifest.json"
    manifest.write_text("{corrupted_json_content...", encoding="utf-8")

    lead = LeadInput(lead_id="lead_1", name="Test Lead", company="Acme")
    profile = LeadProfile(
        schema_version="2.0.0",
        lead_id="lead_1",
        identity={"name": "Test Lead"},
        priority=PriorityInfo(numeric_priority=1, reason="Test", score=50.0),
        research_metadata=ResearchMetadata(research_status="completed", sources_examined=1),
    )

    with pytest.raises(ValueError, match="corrupted manifest"):
        exporter.export_batch(batch_id=batch_id, leads_with_profiles=[(lead, profile)], allow_overwrite=False)


def test_export_batch_counts_and_manifest_agree(tmp_path: Path):
    exporter = LeadExporter(output_base_dir=tmp_path / "batches")
    lead = LeadInput(lead_id="lead_cnt_1", name="Count Test", company="Counter Corp")
    profile = LeadProfile(
        schema_version="2.0.0",
        lead_id="lead_cnt_1",
        identity={"name": "Count Test"},
        priority=PriorityInfo(numeric_priority=0, reason="High fit", score=90.0),
        research_metadata=ResearchMetadata(research_status="completed", sources_examined=2),
    )
    batch_id = "batch_counts_agree_01"
    paths = exporter.export_batch(
        batch_id=batch_id,
        leads_with_profiles=[(lead, profile)],
        batch_metadata={"input_filename": "test.csv"},
    )

    manifest_file = Path(paths["manifest_path"])
    summary_file = Path(paths["summary_path"])

    with open(manifest_file, "r", encoding="utf-8") as f:
        m_data = json.load(f)
    with open(summary_file, "r", encoding="utf-8") as f:
        s_data = json.load(f)

    assert m_data["counts"]["total"] == 1
    assert m_data["counts"]["completed"] == 1
    assert m_data["counts"]["failed"] == 0
    assert s_data["total_leads"] == 1
    assert s_data["completed_count"] == 1
    assert m_data["priority_distribution"]["0"] == 1
    assert s_data["priority_counts"]["0"] == 1
    assert m_data["status"] == s_data["status"] == "completed"
