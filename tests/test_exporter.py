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


def test_lock_conflict_raises_error_when_active_process_holds_lock(tmp_path: Path):
    """Test that an active process holding a lock prevents concurrent export."""
    exporter = LeadExporter(output_base_dir=tmp_path / "batches")
    batch_id = "batch_lock_conflict_01"

    # Acquire and hold an active batch lock
    held_lock = exporter.acquire_batch_lock(batch_id)
    try:
        lead = LeadInput(lead_id="l1", name="Lock Test", company="LockCo")
        profile = LeadProfile(
            lead_id="l1",
            identity={"name": "Lock Test"},
            priority=PriorityInfo(numeric_priority=1, reason="Test", score=50.0),
            research_metadata=ResearchMetadata(research_status="completed", sources_examined=1),
        )

        with pytest.raises(RuntimeError, match="Concurrent export lock detected"):
            exporter.export_batch(batch_id=batch_id, leads_with_profiles=[(lead, profile)])
    finally:
        held_lock.release()


def test_stale_lock_of_dead_pid_is_safely_reclaimed(tmp_path: Path):
    """Test that a leftover lock file from a dead process is safely reclaimed without error."""
    exporter = LeadExporter(output_base_dir=tmp_path / "batches")
    batch_id = "batch_stale_lock_01"
    lock_file = (tmp_path / "batches") / f".lock_{batch_id}"
    (tmp_path / "batches").mkdir(parents=True, exist_ok=True)

    # Write a leftover lock file (simulating a dead process that terminated without releasing)
    dead_pid = 9999999
    lock_file.write_text(f"pid={dead_pid}\ntimestamp=1000000.0\ntoken=dead_token\n", encoding="utf-8")

    lead = LeadInput(lead_id="l1", name="Stale Test", company="StaleCo")
    profile = LeadProfile(
        lead_id="l1",
        identity={"name": "Stale Test"},
        priority=PriorityInfo(numeric_priority=1, reason="Test", score=50.0),
        research_metadata=ResearchMetadata(research_status="completed", sources_examined=1),
    )

    # Export must safely succeed because no active process holds the OS advisory lock
    res = exporter.export_batch(batch_id=batch_id, leads_with_profiles=[(lead, profile)])
    assert Path(res["batch_dir"]).exists()


def test_setup_failure_cleans_up_lock(tmp_path: Path, monkeypatch):
    """Test that a failure during setup/staging releases the acquired lock."""
    exporter = LeadExporter(output_base_dir=tmp_path / "batches")
    batch_id = "batch_setup_failure_01"

    lead = LeadInput(lead_id="l1", name="Fail Test", company="FailCo")
    profile = LeadProfile(
        lead_id="l1",
        identity={"name": "Fail Test"},
        priority=PriorityInfo(numeric_priority=1, reason="Test", score=50.0),
        research_metadata=ResearchMetadata(research_status="completed", sources_examined=1),
    )

    # Mock Path.mkdir on the staging dir to fail
    original_mkdir = Path.mkdir
    def mock_mkdir(self, *args, **kwargs):
        if ".staging_" in str(self):
            raise OSError("Simulated disk full / permissions error during staging setup")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mock_mkdir)

    with pytest.raises(OSError, match="Simulated disk full"):
        exporter.export_batch(batch_id=batch_id, leads_with_profiles=[(lead, profile)])

    monkeypatch.undo()

    # Lock must be released even after setup failure: subsequent export succeeds
    res = exporter.export_batch(batch_id=batch_id, leads_with_profiles=[(lead, profile)])
    assert Path(res["batch_dir"]).exists()


def test_cross_process_lock_conflict_and_recovery(tmp_path: Path):
    """Test OS-level locking across separate child processes and recovery after termination."""
    import subprocess
    import sys

    batches_dir = tmp_path / "batches"
    exporter = LeadExporter(output_base_dir=batches_dir)
    batch_id = "batch_cross_proc_01"

    lead = LeadInput(lead_id="l1", name="Proc Test", company="ProcCo")
    profile = LeadProfile(
        lead_id="l1",
        identity={"name": "Proc Test"},
        priority=PriorityInfo(numeric_priority=1, reason="Test", score=50.0),
        research_metadata=ResearchMetadata(research_status="completed", sources_examined=1),
    )

    # Spawn child process that acquires and holds the batch lock
    child_code = (
        "import sys, time; "
        "from pathlib import Path; "
        "from src.lead_research.exporter import LeadExporter; "
        "exp = LeadExporter(output_base_dir=Path(sys.argv[1])); "
        "lock = exp.acquire_batch_lock(sys.argv[2]); "
        "sys.stdout.write('LOCKED\\n'); sys.stdout.flush(); "
        "time.sleep(30)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", child_code, str(batches_dir), batch_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # Wait for child to confirm lock acquisition
        signal_line = proc.stdout.readline()
        assert "LOCKED" in signal_line

        # While child holds the lock, parent export MUST fail
        with pytest.raises(RuntimeError, match="Concurrent export lock detected"):
            exporter.export_batch(batch_id=batch_id, leads_with_profiles=[(lead, profile)])
    finally:
        # Terminate child process (safe handle-based termination)
        proc.kill()
        proc.wait(timeout=5)

    # After child termination, operating system releases lock, parent export succeeds
    res = exporter.export_batch(batch_id=batch_id, leads_with_profiles=[(lead, profile)])
    assert Path(res["batch_dir"]).exists()


def test_malformed_lock_metadata_safely_handled(tmp_path: Path):
    """Test that malformed or corrupted lock files from prior runs do not crash exporter."""
    batches_dir = tmp_path / "batches"
    exporter = LeadExporter(output_base_dir=batches_dir)
    batch_id = "batch_malformed_lock_01"
    lock_file = batches_dir / f".lock_{batch_id}"
    batches_dir.mkdir(parents=True, exist_ok=True)

    # Write corrupt / garbage bytes
    lock_file.write_bytes(b"\x00\xff\xfe\x01\x02\x03 corrupted garbage data")

    lead = LeadInput(lead_id="l1", name="Garbage Lock Test", company="GarbageCo")
    profile = LeadProfile(
        lead_id="l1",
        identity={"name": "Garbage Lock Test"},
        priority=PriorityInfo(numeric_priority=1, reason="Test", score=50.0),
        research_metadata=ResearchMetadata(research_status="completed", sources_examined=1),
    )

    res = exporter.export_batch(batch_id=batch_id, leads_with_profiles=[(lead, profile)])
    assert Path(res["batch_dir"]).exists()


def test_finalized_batch_immutable_even_with_allow_overwrite(tmp_path: Path):
    """Test that completed/finalized batches cannot be overwritten even if allow_overwrite=True."""
    exporter = LeadExporter(output_base_dir=tmp_path / "batches")
    batch_id = "batch_immutable_strict_01"
    b_dir = tmp_path / "batches" / batch_id
    b_dir.mkdir(parents=True, exist_ok=True)
    manifest = b_dir / "manifest.json"
    manifest.write_text(json.dumps({"batch_id": batch_id, "status": "completed"}), encoding="utf-8")

    lead = LeadInput(lead_id="l1", name="Test", company="Acme")
    profile = LeadProfile(
        lead_id="l1",
        identity={"name": "Test"},
        priority=PriorityInfo(numeric_priority=1, reason="Test", score=50.0),
        research_metadata=ResearchMetadata(research_status="completed", sources_examined=1),
    )

    with pytest.raises(ValueError, match="immutable"):
        exporter.export_batch(batch_id=batch_id, leads_with_profiles=[(lead, profile)], allow_overwrite=True)


def test_latest_json_updated_atomically(tmp_path: Path):
    """Test that latest.json is created atomically and points to the valid completed batch."""
    batches_dir = tmp_path / "output" / "batches"
    exporter = LeadExporter(output_base_dir=batches_dir)

    lead = LeadInput(lead_id="l1", name="Latest Test", company="LatestCo")
    profile = LeadProfile(
        lead_id="l1",
        identity={"name": "Latest Test"},
        priority=PriorityInfo(numeric_priority=0, reason="High fit", score=95.0),
        research_metadata=ResearchMetadata(research_status="completed", sources_examined=2),
    )

    batch_id = "batch_latest_test_01"
    res = exporter.export_batch(batch_id=batch_id, leads_with_profiles=[(lead, profile)])

    latest_json = tmp_path / "output" / "latest.json"
    assert latest_json.exists(), "latest.json must exist in parent output dir"

    with open(latest_json, "r", encoding="utf-8") as f:
        latest_data = json.load(f)

    assert latest_data["batch_id"] == batch_id
    assert latest_data["manifest_path"] == res["manifest_path"]
    assert latest_data["summary"]["completed_count"] == 1
    assert latest_data["summary"]["priority_counts"]["0"] == 1
