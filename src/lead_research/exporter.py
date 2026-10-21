"""CSV and JSON exporter with atomic writes, safe filenames, and sorted priority output."""

import csv
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .schemas import LeadInput, LeadProfile

logger = logging.getLogger("lead_research.exporter")


def sanitize_filename(name: str, max_length: int = 50) -> str:
    """Sanitize string for safe filenames and prevent path traversal."""
    if not name:
        return "unnamed"
    clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.strip().lower())
    clean = re.sub(r"_+", "_", clean).strip("_")
    return clean[:max_length] or "unnamed"


class BatchLock:
    """
    Cross-platform OS-level advisory file lock for batch export reservation.
    Held open for the duration of batch export and released on completion or failure.
    If the holding process terminates unexpectedly, the OS kernel automatically releases the lock.
    """
    _thread_locks_guard = threading.Lock()
    _active_thread_locks: set = set()

    def __init__(self, lock_file: Path, batch_id: str):
        self.lock_file = lock_file
        self.batch_id = batch_id
        self.fd: Optional[int] = None
        self._thread_locked = False

    def acquire(self) -> None:
        norm_key = str(self.lock_file.resolve())
        with self._thread_locks_guard:
            if norm_key in self._active_thread_locks:
                raise RuntimeError(
                    f"Concurrent export lock detected: another active process or thread is "
                    f"currently publishing batch '{self.batch_id}'. Lock reservation: {self.lock_file}"
                )
            self._active_thread_locks.add(norm_key)
            self._thread_locked = True

        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(str(self.lock_file), os.O_RDWR | os.O_CREAT, 0o666)

            if os.fstat(self.fd).st_size == 0:
                os.write(self.fd, b" ")
                try:
                    os.fsync(self.fd)
                except OSError:
                    pass

            if sys.platform == "win32":
                import msvcrt
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Safely record diagnostic metadata after byte 0
            try:
                os.lseek(self.fd, 1, os.SEEK_SET)
                meta = f"pid={os.getpid()}\ntime={time.time()}\nbatch={self.batch_id}\n".encode("utf-8")
                os.write(self.fd, meta)
                os.ftruncate(self.fd, 1 + len(meta))
            except Exception:
                pass

        except (BlockingIOError, PermissionError, OSError) as err:
            self._cleanup_on_failure()
            raise RuntimeError(
                f"Concurrent export lock detected: another active process is currently "
                f"publishing batch '{self.batch_id}'. Lock reservation: {self.lock_file}"
            ) from err
        except Exception:
            self._cleanup_on_failure()
            raise

    def _cleanup_on_failure(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self._thread_locked:
            norm_key = str(self.lock_file.resolve())
            with self._thread_locks_guard:
                self._active_thread_locks.discard(norm_key)
            self._thread_locked = False

    def release(self) -> None:
        if self.fd is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    try:
                        os.lseek(self.fd, 0, os.SEEK_SET)
                        msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl
                    try:
                        fcntl.flock(self.fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
            finally:
                try:
                    os.close(self.fd)
                except OSError:
                    pass
                self.fd = None

        if self._thread_locked:
            norm_key = str(self.lock_file.resolve())
            with self._thread_locks_guard:
                self._active_thread_locks.discard(norm_key)
            self._thread_locked = False

    def __enter__(self) -> "BatchLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


class LeadExporter:
    """Exports prioritized CSV, individual per-lead JSON profiles, batch manifests, and audit files."""

    def __init__(self, output_base_dir: Path):
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(parents=True, exist_ok=True)

    def acquire_batch_lock(self, batch_id: str) -> BatchLock:
        """Acquire exclusive OS-level advisory lock for batch."""
        clean_id = sanitize_filename(batch_id)
        lock_file = self.output_base_dir / f".lock_{clean_id}"
        lock = BatchLock(lock_file=lock_file, batch_id=batch_id)
        lock.acquire()
        return lock

    def _acquire_batch_lock(self, lock_file: Path, batch_id: str, clean_id: str) -> BatchLock:
        """Internal helper for acquiring lock."""
        lock = BatchLock(lock_file=lock_file, batch_id=batch_id)
        lock.acquire()
        return lock

    def get_batch_dir(self, batch_id: str) -> Path:
        """Get directory for a specific batch."""
        b_dir = self.output_base_dir / sanitize_filename(batch_id)
        b_dir.mkdir(parents=True, exist_ok=True)
        return b_dir

    def export_batch(
        self,
        batch_id: str,
        leads_with_profiles: List[Tuple[LeadInput, LeadProfile]],
        errors: Optional[List[Dict[str, Any]]] = None,
        batch_metadata: Optional[Dict[str, Any]] = None,
        allow_overwrite: bool = False,
    ) -> Dict[str, str]:
        """Export all assets for a batch: CSVs, profiles, JSONL logs, and manifest."""
        clean_id = sanitize_filename(batch_id)
        lock_file = self.output_base_dir / f".lock_{clean_id}"
        batch_lock = self._acquire_batch_lock(lock_file, batch_id, clean_id)
        lock_acquired = True

        staging_dir = None
        try:
            batch_dir = self.output_base_dir / clean_id
            manifest_file = batch_dir / "manifest.json"

            # Check existing batch directory and manifest immutability under exclusive reservation
            if batch_dir.exists() and any(batch_dir.iterdir()):
                if manifest_file.exists():
                    try:
                        with open(manifest_file, "r", encoding="utf-8") as mf:
                            existing_m = json.load(mf)
                            st = existing_m.get("status")
                            # Completed and finalized batches are strictly immutable regardless of allow_overwrite
                            if st in ("completed", "finalized"):
                                raise ValueError(
                                    f"Batch '{batch_id}' is finalized (status: {st}) and immutable. "
                                    "Cannot overwrite an existing batch."
                                )
                            if not allow_overwrite:
                                raise ValueError(
                                    f"Batch '{batch_id}' has existing state (status: {st}) and is immutable. "
                                    "Cannot overwrite without explicit allow_overwrite=True."
                                )
                    except json.JSONDecodeError:
                        raise ValueError(
                            f"Batch '{batch_id}' contains an unreadable or corrupted manifest. "
                            "Refusing to overwrite existing batch directory."
                        )
                    except OSError as e:
                        raise ValueError(
                            f"Batch '{batch_id}' manifest could not be read: {e}. "
                            "Refusing to overwrite existing batch directory."
                        )
                else:
                    if not allow_overwrite:
                        raise ValueError(
                            f"Batch directory '{batch_id}' already exists and contains files. "
                            "Cannot overwrite without explicit allow_overwrite=True."
                        )

            # Isolated staging directory for atomic finalization
            staging_dir = self.output_base_dir / f".staging_{clean_id}_{os.getpid()}_{int(time.time() * 1000)}"
            staging_dir.mkdir(parents=True, exist_ok=True)
            staging_profiles_dir = staging_dir / "profiles"
            staging_profiles_dir.mkdir(parents=True, exist_ok=True)
            exported_profiles: List[str] = []
            csv_rows: List[Dict[str, Any]] = []
            outreach_ready_rows: List[Dict[str, Any]] = []
            needs_review_rows: List[Dict[str, Any]] = []
            jsonl_profiles: List[Dict[str, Any]] = []
            all_sources: List[Dict[str, Any]] = []
            all_claims: List[Dict[str, Any]] = []
            input_snapshot_rows: List[Dict[str, Any]] = []

            # Sort leads primarily by numeric priority ascending (0, 1, 2)
            # Secondarily by score descending, then sources examined descending
            def sort_key(item: Tuple[LeadInput, LeadProfile]):
                p = item[1].priority.numeric_priority
                score = item[1].priority.score
                sources = item[1].research_metadata.sources_examined
                return (p, -score, -sources)

            sorted_items = sorted(leads_with_profiles, key=sort_key)

            for idx, (lead, profile) in enumerate(sorted_items, start=1):
                name_slug = sanitize_filename(profile.identity.get("name") or "lead")
                filename = f"person_{idx:03d}_{sanitize_filename(lead.lead_id)}_{name_slug}.json"
                profile_file = staging_profiles_dir / filename

                profile_dict = profile.model_dump()
                jsonl_profiles.append(profile_dict)

                # Collect sources & claims
                for s in profile.sources:
                    all_sources.append({"lead_id": lead.lead_id, **s.model_dump()})
                for c in profile.claims:
                    all_claims.append({"lead_id": lead.lead_id, **c.model_dump()})

                # Collect input snapshot
                raw_snap = dict(lead.raw_data) if lead.raw_data else dict(lead.model_dump())
                raw_snap["lead_id"] = lead.lead_id
                input_snapshot_rows.append(raw_snap)

                # Write JSON profile to staging
                with open(profile_file, "w", encoding="utf-8") as f:
                    json.dump(profile_dict, f, indent=2, ensure_ascii=False)

                exported_profiles.append(filename)

                # Build enriched CSV row preserving original fields
                row_data = dict(lead.raw_data) if lead.raw_data else {}
                row_data["lead_id"] = lead.lead_id
                row_data["name"] = profile.identity.get("name") or lead.name
                row_data["job_title"] = profile.identity.get("job_title") or lead.job_title or ""
                row_data["company"] = profile.identity.get("company") or lead.company or ""
                row_data["industry"] = profile.identity.get("industry") or lead.industry or ""
                row_data["linkedin_url"] = profile.identity.get("linkedin_url") or lead.linkedin_url or ""
                row_data["company_website"] = profile.identity.get("company_website") or lead.company_website or ""
                row_data["professional_email"] = profile.identity.get("professional_email") or lead.professional_email or ""
                row_data["priority"] = profile.priority.numeric_priority
                row_data["priority_reason"] = profile.priority.reason
                row_data["relevance_evidence"] = " | ".join(profile.priority.supporting_evidence)
                row_data["profile_json_path"] = f"profiles/{filename}"
                row_data["research_status"] = profile.research_metadata.research_status
                row_data["last_researched_at"] = profile.research_metadata.last_research_timestamp
                
                # V2 columns
                readiness_status = getattr(profile.contact_readiness, "status", "needs_research")
                row_data["contact_readiness"] = readiness_status
                row_data["icebreaker_text"] = profile.icebreaker.text or ""
                row_data["icebreaker_type"] = profile.icebreaker.icebreaker_type or ""
                row_data["icebreaker_status"] = profile.icebreaker.personalization_status
                row_data["verification_confidence"] = profile.priority.confidence

                csv_rows.append(row_data)

                # Categorize outreach readiness
                if readiness_status == "ready":
                    outreach_ready_rows.append(row_data)
                else:
                    needs_review_rows.append(row_data)

            # 1. Write leads_prioritized.csv & leads_enriched.csv
            csv_path = staging_dir / "leads_prioritized.csv"
            self._write_csv(csv_path, csv_rows)
            shutil.copy2(csv_path, staging_dir / "leads_enriched.csv")

            # 2. Write outreach_ready.csv
            outreach_ready_path = staging_dir / "outreach_ready.csv"
            self._write_csv(outreach_ready_path, outreach_ready_rows)

            # 3. Write needs_review.csv
            needs_review_path = staging_dir / "needs_review.csv"
            self._write_csv(needs_review_path, needs_review_rows)

            # 4. Write leads_input_snapshot.csv
            input_snap_path = staging_dir / "leads_input_snapshot.csv"
            self._write_csv(input_snap_path, input_snapshot_rows)

            # 5. Write lead_profiles.jsonl
            jsonl_path = staging_dir / "lead_profiles.jsonl"
            with open(jsonl_path, "w", encoding="utf-8") as f:
                for item in jsonl_profiles:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")

            # 6. Write sources.jsonl & claims.jsonl
            sources_jsonl = staging_dir / "sources.jsonl"
            with open(sources_jsonl, "w", encoding="utf-8") as f:
                for s in all_sources:
                    f.write(json.dumps(s, ensure_ascii=False) + "\n")

            claims_jsonl = staging_dir / "claims.jsonl"
            with open(claims_jsonl, "w", encoding="utf-8") as f:
                for c in all_claims:
                    f.write(json.dumps(c, ensure_ascii=False) + "\n")

            # 7. Write errors.csv & errors.jsonl
            errors_path = staging_dir / "errors.csv"
            error_rows = self._prepare_error_rows(errors or [], sorted_items)
            self._write_csv(errors_path, error_rows)

            errors_jsonl = staging_dir / "errors.jsonl"
            with open(errors_jsonl, "w", encoding="utf-8") as f:
                for err in (errors or []):
                    f.write(json.dumps(err, ensure_ascii=False) + "\n")

            # 8. Compute Counts and Dynamic Batch Status
            completed_c = sum(1 for _, p in sorted_items if p.research_metadata.research_status == "completed")
            partial_c = sum(1 for _, p in sorted_items if p.research_metadata.research_status == "partial")
            failed_c = sum(1 for _, p in sorted_items if p.research_metadata.research_status == "failed")
            outreach_ready_c = len(outreach_ready_rows)
            needs_review_c = len(needs_review_rows)

            meta_status = (batch_metadata or {}).get("status")
            if meta_status:
                batch_status = meta_status
            elif failed_c == len(leads_with_profiles) and len(leads_with_profiles) > 0:
                batch_status = "failed"
            elif failed_c > 0:
                batch_status = "partial"
            else:
                batch_status = "completed"

            # 9. Write summary.json
            summary_path = staging_dir / "summary.json"
            summary_data = {
                "batch_id": batch_id,
                "status": batch_status,
                "total_leads": len(leads_with_profiles),
                "completed_count": completed_c,
                "partial_count": partial_c,
                "failed_count": failed_c,
                "outreach_ready_count": outreach_ready_c,
                "needs_review_count": needs_review_c,
                "priority_counts": {
                    "0": sum(1 for _, p in sorted_items if p.priority.numeric_priority == 0),
                    "1": sum(1 for _, p in sorted_items if p.priority.numeric_priority == 1),
                    "2": sum(1 for _, p in sorted_items if p.priority.numeric_priority == 2),
                },
                "exported_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary_data, f, indent=2)

            # 10. Write manifest.json
            manifest_path = staging_dir / "manifest.json"
            final_batch_dir = batch_dir
            manifest_data = {
                "batch_id": batch_id,
                "schema_version": "2.0.0",
                "pipeline_version": "2.0.0",
                "started_at": (batch_metadata or {}).get("started_at") or datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "status": batch_status,
                "input_file": (batch_metadata or {}).get("input_filename") or "leads_input_snapshot.csv",
                "input_sha256": (batch_metadata or {}).get("input_sha256") or "",
                "total_processed": len(leads_with_profiles),
                "counts": {
                    "total": len(leads_with_profiles),
                    "processed": len(leads_with_profiles),
                    "completed": completed_c,
                    "partial": partial_c,
                    "failed": failed_c,
                    "outreach_ready": outreach_ready_c,
                    "needs_review": needs_review_c,
                    "identity_conflicts": sum(1 for _, p in sorted_items if "identity_not_verified" in p.contact_readiness.blockers),
                },
                "priority_distribution": {
                    "0": sum(1 for _, p in sorted_items if p.priority.numeric_priority == 0),
                    "1": sum(1 for _, p in sorted_items if p.priority.numeric_priority == 1),
                    "2": sum(1 for _, p in sorted_items if p.priority.numeric_priority == 2),
                },
                "research_status_distribution": {
                    "completed": completed_c,
                    "partial": partial_c,
                    "failed": failed_c,
                },
                "contact_readiness_distribution": {
                    "ready": outreach_ready_c,
                    "needs_review": needs_review_c,
                },
                "csv_path": str(final_batch_dir / "leads_prioritized.csv"),
                "errors_path": str(final_batch_dir / "errors.csv"),
                "profiles_count": len(exported_profiles),
                "files": {
                    "leads_prioritized_csv": str(final_batch_dir / "leads_prioritized.csv"),
                    "outreach_ready_csv": str(final_batch_dir / "outreach_ready.csv"),
                    "needs_review_csv": str(final_batch_dir / "needs_review.csv"),
                    "input_snapshot_csv": str(final_batch_dir / "leads_input_snapshot.csv"),
                    "lead_profiles_jsonl": str(final_batch_dir / "lead_profiles.jsonl"),
                    "sources_jsonl": str(final_batch_dir / "sources.jsonl"),
                    "claims_jsonl": str(final_batch_dir / "claims.jsonl"),
                    "errors_csv": str(final_batch_dir / "errors.csv"),
                    "manifest_json": str(final_batch_dir / "manifest.json"),
                    "summary_json": str(final_batch_dir / "summary.json"),
                },
                "metadata": batch_metadata or {},
            }
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, indent=2)

            # 11. Staging Deliverables Validation
            staged_profile_count = len(list(staging_profiles_dir.glob("*.json")))
            if staged_profile_count != len(leads_with_profiles):
                raise ValueError(
                    f"Batch staging validation error: expected {len(leads_with_profiles)} profiles, "
                    f"staged {staged_profile_count}"
                )

            for req_file in ["leads_prioritized.csv", "outreach_ready.csv", "needs_review.csv", "manifest.json", "summary.json"]:
                if not (staging_dir / req_file).exists():
                    raise ValueError(f"Batch staging validation error: missing required deliverable '{req_file}'")

            # 12. Publish to Target Batch Directory (Manifest moved last to ensure atomic batch completion)
            batch_dir.mkdir(parents=True, exist_ok=True)
            target_profiles = batch_dir / "profiles"
            target_profiles.mkdir(parents=True, exist_ok=True)

            manifest_staged = staging_dir / "manifest.json"
            for item in staging_dir.iterdir():
                if item.name == "manifest.json":
                    continue
                elif item.name == "profiles":
                    for pf in item.iterdir():
                        dest_pf = target_profiles / pf.name
                        if dest_pf.exists():
                            dest_pf.unlink()
                        shutil.move(str(pf), str(dest_pf))
                else:
                    dest_item = batch_dir / item.name
                    if dest_item.exists():
                        dest_item.unlink()
                    shutil.move(str(item), str(dest_item))

            if manifest_staged.exists():
                dest_mf = batch_dir / "manifest.json"
                if dest_mf.exists():
                    dest_mf.unlink()
                shutil.move(str(manifest_staged), str(dest_mf))

            shutil.rmtree(staging_dir, ignore_errors=True)

            # 13. Atomic latest.json update (only after successful publishing while holding exclusive reservation)
            final_manifest_path = batch_dir / "manifest.json"
            final_summary_path = batch_dir / "summary.json"
            latest_data = {
                "batch_id": batch_id,
                "manifest_path": str(final_manifest_path),
                "summary": summary_data,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                targets = [self.output_base_dir / "latest.json"]
                if self.output_base_dir.parent.exists() and self.output_base_dir.name == "batches":
                    targets.append(self.output_base_dir.parent / "latest.json")

                for t in targets:
                    tmp_t = t.parent / f"{t.name}.{os.getpid()}.{time.time()}.tmp"
                    with open(tmp_t, "w", encoding="utf-8") as f:
                        json.dump(latest_data, f, indent=2)
                    os.replace(str(tmp_t), str(t))
            except Exception as l_err:
                logger.debug(f"Notice writing latest.json: {l_err}")

            # 14. Top-level mirroring only when operating in canonical data/output
            try:
                alt_root = Path("output")
                if (
                    alt_root.resolve() != batch_dir.resolve()
                    and self.output_base_dir in (Path("data/output/batches"), Path("data/output"))
                ):
                    alt_root.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(batch_dir / "leads_prioritized.csv", alt_root / "leads_prioritized.csv")
                    shutil.copy2(batch_dir / "manifest.json", alt_root / "manifest.json")
                    if (batch_dir / "errors.csv").exists():
                        shutil.copy2(batch_dir / "errors.csv", alt_root / "errors.csv")
                    alt_profiles = alt_root / "profiles"
                    alt_profiles.mkdir(parents=True, exist_ok=True)
                    for p_file in target_profiles.glob("*.json"):
                        shutil.copy2(p_file, alt_profiles / p_file.name)
            except Exception as copy_err:
                logger.debug(f"Notice on legacy output mirror: {copy_err}")

            return {
                "batch_dir": str(batch_dir),
                "csv_path": str(batch_dir / "leads_prioritized.csv"),
                "outreach_ready_path": str(batch_dir / "outreach_ready.csv"),
                "needs_review_path": str(batch_dir / "needs_review.csv"),
                "errors_path": str(batch_dir / "errors.csv"),
                "manifest_path": str(final_manifest_path),
                "summary_path": str(final_summary_path),
                "profiles_dir": str(target_profiles),
                "jsonl_path": str(batch_dir / "lead_profiles.jsonl"),
            }

        except Exception as export_err:
            if staging_dir and staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            raise export_err
        finally:
            if lock_acquired and batch_lock:
                batch_lock.release()

    def _write_csv(self, file_path: Path, rows: List[Dict[str, Any]]) -> None:
        """Write CSV atomically with UTF-8 encoding."""
        if not rows:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                f.write("lead_id,name,company,job_title,status\n")
            return

        # Determine all unique fieldnames preserving first seen order
        fieldnames: List[str] = []
        for r in rows:
            for k in r.keys():
                if k not in fieldnames:
                    fieldnames.append(k)

        temp_path = file_path.parent / f"{file_path.name}.tmp"
        with open(temp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                cleaned_row = {
                    k: (str(v) if v is not None else "") for k, v in row.items()
                }
                writer.writerow(cleaned_row)

        temp_path.replace(file_path)

    def _prepare_error_rows(
        self,
        validation_errors: List[Dict[str, Any]],
        leads_with_profiles: List[Tuple[LeadInput, LeadProfile]],
    ) -> List[Dict[str, Any]]:
        """Combine CSV import validation errors and research errors into single report."""
        error_rows: List[Dict[str, Any]] = []

        for ve in validation_errors:
            error_rows.append({
                "source": "import_validation",
                "row_index": ve.get("row_index", ""),
                "lead_id": ve.get("lead_id", ""),
                "name": ve.get("name", ""),
                "error_type": ve.get("type", "validation_error"),
                "description": ve.get("error", "Malformed or incomplete row"),
            })

        for lead, profile in leads_with_profiles:
            meta = profile.research_metadata
            if meta.research_status == "failed" or meta.errors_and_limitations:
                for limitation in meta.errors_and_limitations:
                    error_rows.append({
                        "source": "research_pipeline",
                        "row_index": "",
                        "lead_id": lead.lead_id,
                        "name": lead.name,
                        "error_type": meta.research_status,
                        "description": limitation,
                    })

        return error_rows
