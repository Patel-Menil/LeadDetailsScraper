"""Batch pipeline orchestrator with concurrency, resume support, and progress tracking."""

import concurrent.futures
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .exporter import LeadExporter, sanitize_filename
from .importer import LeadImporter
from .research import LeadResearcher
from .schemas import BatchProgress, LeadInput, LeadProfile

logger = logging.getLogger("lead_research.pipeline")


class ResearchPipeline:
    """Orchestrates end-to-end lead research batches with concurrency and resume support."""

    def __init__(
        self,
        output_dir: Path,
        concurrency: int = 4,
        researcher: Optional[LeadResearcher] = None,
        exporter: Optional[LeadExporter] = None,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.concurrency = max(1, concurrency)
        self.researcher = researcher or LeadResearcher()
        self.exporter = exporter or LeadExporter(self.output_dir)

    def run_batch(
        self,
        batch_id: str,
        input_file: Path,
        mapping_override: Optional[Dict[str, str]] = None,
        max_leads: Optional[int] = None,
        dry_run: bool = False,
        resume: bool = True,
        use_browser: bool = True,
        use_tor: bool = True,
        tor_proxy: Optional[str] = None,
        progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    ) -> Tuple[BatchProgress, Dict[str, str]]:
        """Execute a full lead research batch."""
        from .scraper import ScraplingScraper
        self.researcher = LeadResearcher(
            scraper=ScraplingScraper(
                use_browser=use_browser,
                use_tor=use_tor,
                proxy=tor_proxy,
            )
        )
        importer = LeadImporter()
        leads, summary = importer.import_leads(
            file_path_or_bytes=input_file,
            filename=input_file.name,
            mapping_override=mapping_override,
            max_leads=max_leads,
        )

        progress = BatchProgress(
            batch_id=batch_id,
            filename=input_file.name,
            status="processing",
            total_leads=len(leads),
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        if progress_callback:
            progress_callback(progress)

        batch_dir = self.exporter.get_batch_dir(batch_id)
        profiles_dir = batch_dir / "profiles"
        checkpoints_dir = batch_dir / ".checkpoints"

        # Check existing profiles for resume support (both finalized and live checkpoints)
        existing_profiles: Dict[str, LeadProfile] = {}
        if resume:
            for search_dir in [profiles_dir, checkpoints_dir]:
                if search_dir.exists():
                    for pf in search_dir.glob("*.json"):
                        if pf.is_file() and not pf.name.endswith(".tmp"):
                            try:
                                with open(pf, "r", encoding="utf-8") as f:
                                    data = json.load(f)
                                    if "lead_id" in data:
                                        existing_profiles[data["lead_id"]] = LeadProfile.model_validate(data)
                            except Exception as e:
                                logger.warning(f"Could not read existing profile {pf}: {e}")

        results: List[Tuple[LeadInput, LeadProfile]] = []
        leads_to_process: List[LeadInput] = []

        # Separate leads already cached
        for lead in leads:
            if resume and lead.lead_id in existing_profiles:
                results.append((lead, existing_profiles[lead.lead_id]))
                p_prof = existing_profiles[lead.lead_id]
                progress.processed_leads += 1
                if p_prof.research_metadata.research_status == "completed":
                    progress.completed_count += 1
                elif p_prof.research_metadata.research_status == "partial":
                    progress.partial_count += 1
                else:
                    progress.failed_count += 1
                p_key = str(p_prof.priority.numeric_priority)
                progress.priority_counts[p_key] = progress.priority_counts.get(p_key, 0) + 1
            else:
                leads_to_process.append(lead)

        import threading
        log_lock = threading.Lock()
        scraping_log_path = batch_dir / "scraping.log"

        def log_event(msg: str):
            with log_lock:
                ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
                formatted = f"[{ts}] {msg}"
                progress.recent_logs.append(formatted)
                if len(progress.recent_logs) > 120:
                    progress.recent_logs.pop(0)
                try:
                    with open(scraping_log_path, "a", encoding="utf-8") as lf:
                        lf.write(formatted + "\n")
                except Exception:
                    pass
            if progress_callback:
                progress_callback(progress)

        log_event(
            f"Batch started: {len(leads)} total leads ({len(results)} loaded from resume cache, {len(leads_to_process)} to research)"
        )

        def process_single_lead(lead: LeadInput) -> Tuple[LeadInput, LeadProfile]:
            log_event(f"🎯 Researching: {lead.name} ({lead.company or 'Unknown Co'})")
            profile = self.researcher.research_lead(
                lead,
                skip_web_scrape=dry_run,
                log_fn=log_event,
            )
            return (lead, profile)

        # Process with ThreadPoolExecutor
        if leads_to_process:
            workers = 1 if dry_run else self.concurrency
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(process_single_lead, lead): lead for lead in leads_to_process}
                for future in concurrent.futures.as_completed(futures):
                    lead_item = futures[future]
                    try:
                        lead_res, profile_res = future.result()
                        results.append((lead_res, profile_res))
                        progress.processed_leads += 1

                        status = profile_res.research_metadata.research_status
                        if status == "completed":
                            progress.completed_count += 1
                        elif status == "partial":
                            progress.partial_count += 1
                        else:
                            progress.failed_count += 1

                        p_key = str(profile_res.priority.numeric_priority)
                        progress.priority_counts[p_key] = progress.priority_counts.get(p_key, 0) + 1
                        progress.current_lead_name = lead_res.name

                        log_event(
                            f"✅ Lead completed: {lead_res.name} -> Priority {profile_res.priority.numeric_priority} ({progress.processed_leads}/{progress.total_leads})"
                        )

                        # Incrementally save individual profile JSON to hidden checkpoints directory
                        try:
                            checkpoints_dir.mkdir(parents=True, exist_ok=True)
                            chk_file = checkpoints_dir / f"chk_{lead_res.lead_id}.json"
                            tmp_file = checkpoints_dir / f"chk_{lead_res.lead_id}.tmp"
                            with open(tmp_file, "w", encoding="utf-8") as f:
                                json.dump(profile_res.model_dump(), f, indent=2, ensure_ascii=False)
                            tmp_file.replace(chk_file)
                        except Exception as p_err:
                            logger.warning(f"Failed checkpoint write: {p_err}")

                    except Exception as exc:
                        logger.error(f"Failed processing lead {lead_item.lead_id}: {exc}")
                        progress.failed_count += 1
                        progress.errors.append(f"Lead {lead_item.name} error: {str(exc)}")
                        log_event(f"❌ Lead error ({lead_item.name}): {str(exc)[:60]}")

                    progress.updated_at = datetime.now(timezone.utc).isoformat()
                    if progress_callback:
                        progress_callback(progress)

        # Export outputs
        export_paths = self.exporter.export_batch(
            batch_id=batch_id,
            leads_with_profiles=results,
            errors=summary.validation_errors,
            batch_metadata={
                "input_filename": input_file.name,
                "dry_run": dry_run,
                "resume": resume,
                "total_input_rows": summary.total_input_rows,
                "duplicate_records": summary.duplicate_records,
                "malformed_rows": summary.malformed_rows,
            },
        )

        # Clean up temporary checkpoints
        if checkpoints_dir.exists():
            import shutil
            shutil.rmtree(checkpoints_dir, ignore_errors=True)

        progress.status = "completed"
        progress.updated_at = datetime.now(timezone.utc).isoformat()
        log_event("🏁 Batch completed successfully. All research profiles and exports generated.")
        if progress_callback:
            progress_callback(progress)

        return progress, export_paths
