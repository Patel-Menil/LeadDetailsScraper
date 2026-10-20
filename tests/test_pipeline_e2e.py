"""End-to-end tests for the research pipeline and resume behavior."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from src.lead_research.pipeline import ResearchPipeline
from src.lead_research.research import LeadResearcher
from src.lead_research.schemas import LeadProfile, PriorityInfo, ProfessionalContext, ResearchMetadata
from src.lead_research.scraper import ScrapeResult


def test_pipeline_dry_run_and_resume(tmp_path: Path):
    input_csv = tmp_path / "test_leads.csv"
    input_csv.write_text(
        "Full Name,Job Title,Company Name,Industry,Email\n"
        "Elena Rostova,Chief AI Officer,Cognitive Corp,information technology,elena@cognitive.com\n"
        "Marcus Vance,VP Engineering,DataMesh,financial services,marcus@datamesh.io\n",
        encoding="utf-8"
    )

    output_dir = tmp_path / "output"
    pipeline = ResearchPipeline(output_dir=output_dir, concurrency=2)

    # 1. Run batch in dry-run mode
    progress, paths = pipeline.run_batch(
        batch_id="batch_dry_01",
        input_file=input_csv,
        dry_run=True,
    )

    assert progress.status == "completed"
    assert progress.total_leads == 2
    assert progress.processed_leads == 2
    assert Path(paths["csv_path"]).exists()
    assert Path(paths["manifest_path"]).exists()

    # 2. Run again with resume=True: verify existing profiles are loaded
    progress2, paths2 = pipeline.run_batch(
        batch_id="batch_dry_01",
        input_file=input_csv,
        dry_run=True,
        resume=True,
    )
    assert progress2.processed_leads == 2
    assert any("loaded from resume cache" in msg for msg in progress2.recent_logs)
