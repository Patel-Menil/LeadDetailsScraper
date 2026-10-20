"""CSV and JSON exporter with atomic writes, safe filenames, and sorted priority output."""

import csv
import json
import logging
import re
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


class LeadExporter:
    """Exports prioritized CSV, individual per-lead JSON profiles, and error reports."""

    def __init__(self, output_base_dir: Path):
        self.output_base_dir = Path(output_base_dir)

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
    ) -> Dict[str, str]:
        """Export all assets for a batch: CSV, profiles, errors, and manifest."""
        batch_dir = self.get_batch_dir(batch_id)
        profiles_dir = batch_dir / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)

        # Remove unranked live temporary profiles so each lead has exactly one ranked profile
        for old_live in profiles_dir.glob("person_lead_*.json"):
            try:
                old_live.unlink()
            except OSError:
                pass

        exported_profiles = []
        csv_rows: List[Dict[str, Any]] = []

        # Sort leads primarily by numeric priority ascending (0, 1, 2)
        # Secondarily by score descending, then sources examined descending
        def sort_key(item: Tuple[LeadInput, LeadProfile]):
            p = item[1].priority.numeric_priority
            score = item[1].priority.score
            sources = item[1].research_metadata.sources_examined
            return (p, -score, -sources)

        sorted_items = sorted(leads_with_profiles, key=sort_key)

        for idx, (lead, profile) in enumerate(sorted_items, start=1):
            # Stable safe filename: person_{idx:03d}_{lead_id}_{name_slug}.json
            name_slug = sanitize_filename(profile.identity.get("name") or "lead")
            filename = f"person_{idx:03d}_{sanitize_filename(lead.lead_id)}_{name_slug}.json"
            profile_file = profiles_dir / filename

            # Write JSON atomically
            temp_file = profiles_dir / f"{filename}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(profile.model_dump(), f, indent=2, ensure_ascii=False)
            temp_file.replace(profile_file)

            exported_profiles.append(str(profile_file))

            # Build enriched CSV row preserving original fields
            row_data = dict(lead.raw_data)
            # Add/standardize required columns
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

            csv_rows.append(row_data)

        # Write leads_prioritized.csv
        csv_path = batch_dir / "leads_prioritized.csv"
        self._write_csv(csv_path, csv_rows)

        # Write errors.csv
        errors_path = batch_dir / "errors.csv"
        error_rows = self._prepare_error_rows(errors or [], sorted_items)
        self._write_csv(errors_path, error_rows)

        # Write manifest.json
        manifest_path = batch_dir / "manifest.json"
        manifest_data = {
            "batch_id": batch_id,
            "total_processed": len(leads_with_profiles),
            "priority_distribution": {
                "0": sum(1 for _, p in sorted_items if p.priority.numeric_priority == 0),
                "1": sum(1 for _, p in sorted_items if p.priority.numeric_priority == 1),
                "2": sum(1 for _, p in sorted_items if p.priority.numeric_priority == 2),
            },
            "research_status_distribution": {
                "completed": sum(1 for _, p in sorted_items if p.research_metadata.research_status == "completed"),
                "partial": sum(1 for _, p in sorted_items if p.research_metadata.research_status == "partial"),
                "failed": sum(1 for _, p in sorted_items if p.research_metadata.research_status == "failed"),
            },
            "csv_path": str(csv_path),
            "errors_path": str(errors_path),
            "profiles_count": len(exported_profiles),
            "metadata": batch_metadata or {},
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        # Mirror outputs to top-level output directory
        try:
            root_output = self.output_base_dir.parent / "output"
            root_output.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(csv_path, root_output / "leads_prioritized.csv")
            shutil.copy2(manifest_path, root_output / "manifest.json")
            if errors_path.exists():
                shutil.copy2(errors_path, root_output / "errors.csv")
            log_path = batch_dir / "scraping.log"
            if log_path.exists():
                shutil.copy2(log_path, root_output / "scraping.log")
            root_profiles = root_output / "profiles"
            root_profiles.mkdir(parents=True, exist_ok=True)
            for old_f in root_profiles.glob("person_lead_*.json"):
                try:
                    old_f.unlink()
                except OSError:
                    pass
            for p_file in profiles_dir.glob("*.json"):
                shutil.copy2(p_file, root_profiles / p_file.name)

            # Also mirror to workspace root output/ if present
            alt_root = Path("output")
            if alt_root.resolve() != root_output.resolve():
                alt_root.mkdir(parents=True, exist_ok=True)
                shutil.copy2(csv_path, alt_root / "leads_prioritized.csv")
                shutil.copy2(manifest_path, alt_root / "manifest.json")
                if errors_path.exists():
                    shutil.copy2(errors_path, alt_root / "errors.csv")
                if log_path.exists():
                    shutil.copy2(log_path, alt_root / "scraping.log")
                alt_profiles = alt_root / "profiles"
                alt_profiles.mkdir(parents=True, exist_ok=True)
                for old_f in alt_profiles.glob("person_lead_*.json"):
                    try:
                        old_f.unlink()
                    except OSError:
                        pass
                for p_file in profiles_dir.glob("*.json"):
                    shutil.copy2(p_file, alt_profiles / p_file.name)
        except Exception as copy_err:
            logger.warning(f"Failed mirroring to root output directory: {copy_err}")

        return {
            "csv_path": str(csv_path),
            "errors_path": str(errors_path),
            "manifest_path": str(manifest_path),
            "profiles_dir": str(profiles_dir),
        }

    def _prepare_error_rows(
        self,
        validation_errors: List[Dict[str, Any]],
        processed_items: List[Tuple[LeadInput, LeadProfile]],
    ) -> List[Dict[str, Any]]:
        """Consolidate validation and scraping errors."""
        rows: List[Dict[str, Any]] = []

        # From import validation errors
        for err in validation_errors:
            rows.append({
                "lead_id": err.get("lead_id", ""),
                "name": err.get("raw_row", {}).get("Full Name") or err.get("raw_row", {}).get("Name", ""),
                "company": err.get("raw_row", {}).get("Company Name") or err.get("raw_row", {}).get("Company", ""),
                "professional_email": err.get("raw_row", {}).get("Email", ""),
                "error_type": err.get("type", "validation_error"),
                "error_message": err.get("error", "Invalid or malformed lead"),
                "actionable_recommendation": "Check row fields or deduplicate records before import",
            })

        # From research failures
        for lead, profile in processed_items:
            if profile.research_metadata.research_status in ("partial", "failed") and profile.research_metadata.errors_and_limitations:
                for limit in profile.research_metadata.errors_and_limitations:
                    rows.append({
                        "lead_id": lead.lead_id,
                        "name": lead.name,
                        "company": lead.company or "",
                        "professional_email": lead.professional_email or "",
                        "error_type": "research_limitation",
                        "error_message": limit,
                        "actionable_recommendation": "Verify company domain accessibility or verify direct email manually",
                    })

        return rows

    def _write_csv(self, file_path: Path, rows: List[Dict[str, Any]]) -> None:
        """Write rows to CSV atomically with UTF-8 encoding."""
        if not rows:
            # Create empty file with empty headers
            with open(file_path, "w", encoding="utf-8", newline="") as f:
                f.write("lead_id,name,priority,error_message\n")
            return

        # Canonical key order
        core_keys = [
            "lead_id", "name", "job_title", "company", "industry",
            "linkedin_url", "company_website", "professional_email",
            "priority", "priority_reason", "relevance_evidence",
            "profile_json_path", "research_status", "last_researched_at"
        ]
        # Include any extra keys
        all_keys = list(core_keys)
        for r in rows:
            for k in r.keys():
                if k not in all_keys:
                    all_keys.append(k)

        # Write to temporary file first
        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

        temp_path.replace(file_path)
