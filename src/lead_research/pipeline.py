"""Orchestrates end-to-end lead research batches with concurrency, fingerprinting, and resume support."""

import concurrent.futures
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .exporter import LeadExporter
from .fingerprint import compute_file_sha256, create_batch_id, research_fingerprint
from .importer import LeadImporter
from .research import LeadResearcher
from .schemas import BatchProgress, ContactReadiness, LeadInput, LeadProfile, PriorityInfo, ResearchMetadata

logger = logging.getLogger("lead_research.pipeline")


class ResearchPipeline:
    """Orchestrates end-to-end lead research batches with concurrency, fingerprint validation, and resume support."""

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
        batch_id: str = "",
        input_file: Path = Path(""),
        mapping_override: Optional[Dict[str, str]] = None,
        max_leads: Optional[int] = None,
        dry_run: bool = False,
        resume: bool = True,
        use_browser: bool = True,
        use_tor: bool = True,
        tor_proxy: Optional[str] = None,
        progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    ) -> Tuple[BatchProgress, Dict[str, str]]:
        """Execute a full lead research batch with verifiable provenance."""
        from .scraper import ScraplingScraper

        # Generate unique batch ID if not provided
        batch_id = batch_id.strip() if batch_id else create_batch_id()

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

        input_sha256 = compute_file_sha256(input_file) if input_file.exists() else ""
        started_at = datetime.now(timezone.utc).isoformat()

        progress = BatchProgress(
            batch_id=batch_id,
            filename=input_file.name,
            status="processing",
            total_leads=len(leads),
            created_at=started_at,
            updated_at=started_at,
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

        # Separate leads already cached with fingerprint validation
        for lead in leads:
            lead_raw = lead.raw_data or dict(lead.model_dump())
            expected_fp = research_fingerprint(lead_raw, research_config={"dry_run": dry_run})

            cached_prof = existing_profiles.get(lead.lead_id) if resume else None

            # Only reuse cache if fingerprint matches exactly (legacy profiles without fingerprint are invalidated)
            if cached_prof:
                cached_fp = getattr(cached_prof.research_metadata, "cache_fingerprint", None)
                if cached_fp is not None and cached_fp == expected_fp:
                    results.append((lead, cached_prof))
                    progress.processed_leads += 1
                    status = cached_prof.research_metadata.research_status
                    if status == "completed":
                        progress.completed_count += 1
                    elif status == "partial":
                        progress.partial_count += 1
                    else:
                        progress.failed_count += 1

                    if cached_prof.contact_readiness.status == "ready":
                        progress.outreach_ready_count += 1
                    else:
                        progress.needs_review_count += 1

                    p_key = str(cached_prof.priority.numeric_priority)
                    progress.priority_counts[p_key] = progress.priority_counts.get(p_key, 0) + 1
                    continue

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
            # Tag batch_id and fingerprint
            lead_raw = lead.raw_data or dict(lead.model_dump())
            profile.research_metadata.batch_id = batch_id
            profile.research_metadata.cache_fingerprint = research_fingerprint(
                lead_raw, research_config={"dry_run": dry_run}
            )
            return (lead, profile)

        # Process with ThreadPoolExecutor
        worker_errors: List[Dict[str, Any]] = []
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

                        if profile_res.contact_readiness.status == "ready":
                            progress.outreach_ready_count += 1
                        else:
                            progress.needs_review_count += 1

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
                        progress.processed_leads += 1
                        err_msg = str(exc)[:250]
                        progress.errors.append(f"Lead {lead_item.name} error: {err_msg}")
                        progress.needs_review_count += 1
                        log_event(f"❌ Lead error ({lead_item.name}): {err_msg[:60]}")

                        worker_errors.append({
                            "lead_id": lead_item.lead_id,
                            "lead_name": lead_item.name,
                            "company": lead_item.company,
                            "stage": "research_worker",
                            "error_category": "worker_exception",
                            "error": err_msg,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })

                        # Construct explicit failed profile so lead is not dropped from outcome accounting
                        failed_profile = LeadProfile(
                            schema_version="2.0.0",
                            lead_id=lead_item.lead_id,
                            input_snapshot=lead_item.raw_data or dict(lead_item.model_dump()),
                            identity={
                                "name": lead_item.name,
                                "first_name": lead_item.first_name,
                                "last_name": lead_item.last_name,
                                "job_title": lead_item.job_title,
                                "company": lead_item.company,
                                "industry": lead_item.industry,
                                "linkedin_url": lead_item.linkedin_url,
                                "company_website": lead_item.company_website,
                                "professional_email": lead_item.professional_email,
                            },
                            priority=PriorityInfo(
                                numeric_priority=2,
                                reason=f"Research failed due to worker error: {err_msg}",
                                score=0.0,
                                confidence=0.0,
                                supporting_evidence=[f"Worker error: {err_msg}"],
                            ),
                            contact_readiness=ContactReadiness(
                                status="not_ready",
                                has_name=bool(lead_item.name),
                                has_verified_role=False,
                                has_company_context=bool(lead_item.company),
                                has_usable_contact_channel=bool(lead_item.professional_email or lead_item.linkedin_url),
                                has_evidence_based_icebreaker=False,
                                blockers=["research_worker_exception"],
                            ),
                            research_metadata=ResearchMetadata(
                                schema_version="2.0.0",
                                batch_id=batch_id,
                                pipeline_version="2.0.0",
                                execution_status="failed",
                                verification_status="unverified",
                                research_status="failed",
                                errors_and_limitations=[f"Worker error: {err_msg}"],
                            ),
                        )
                        results.append((lead_item, failed_profile))

                    progress.updated_at = datetime.now(timezone.utc).isoformat()
                    if progress_callback:
                        progress_callback(progress)

        # Determine overall batch status
        if progress.failed_count == progress.total_leads and progress.total_leads > 0:
            overall_status = "failed"
        elif progress.failed_count > 0:
            overall_status = "partial"
        else:
            overall_status = "completed"

        combined_errors = list(summary.validation_errors) + worker_errors

        # Export outputs
        export_paths = self.exporter.export_batch(
            batch_id=batch_id,
            leads_with_profiles=results,
            errors=combined_errors,
            batch_metadata={
                "input_filename": input_file.name,
                "input_sha256": input_sha256,
                "started_at": started_at,
                "dry_run": dry_run,
                "resume": resume,
                "status": overall_status,
                "total_input_rows": summary.total_input_rows,
                "duplicate_records": summary.duplicate_records,
                "malformed_rows": summary.malformed_rows,
            },
        )

        # Clean up temporary checkpoints
        if checkpoints_dir.exists():
            import shutil
            shutil.rmtree(checkpoints_dir, ignore_errors=True)

        progress.status = overall_status
        progress.updated_at = datetime.now(timezone.utc).isoformat()
        log_event(f"🏁 Batch finished with status '{overall_status}'. Research profiles and exports generated.")
        if progress_callback:
            progress_callback(progress)

        return progress, export_paths
