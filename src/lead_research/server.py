"""FastAPI backend server for SealAPI Lead Research application."""

import io
import json
import logging
import os
import re
import shutil
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .exporter import LeadExporter, sanitize_filename
from .fingerprint import create_batch_id
from .importer import LeadImporter
from .pipeline import ResearchPipeline
from .schemas import BatchProgress, LeadProfile
from .tor_manager import TorManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("lead_research.server")

# Base directory configuration
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "output"
BATCHES_DIR = OUTPUT_DIR / "batches"
LEGACY_BATCHES_DIR = DATA_DIR / "batches"
STATIC_DIR = BASE_DIR / "static"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
BATCHES_DIR.mkdir(parents=True, exist_ok=True)
LEGACY_BATCHES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="SealAPI Lead Research Engine",
    description="Enterprise Lead Research, Enrichment & Prioritization Pipeline using Scrapling",
    version="1.0.0",
)

# Explicit CORS origins (reject wildcard with credentials)
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000",
)
allowed_origins_list = [o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Secret Key Authorization for Destructive/Mutation Operations
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "").strip()
APP_ENV = os.getenv("APP_ENV", os.getenv("NODE_ENV", "development")).strip().lower()


def is_production() -> bool:
    """Check if server is executing under production or staging environments."""
    return APP_ENV in ("production", "prod", "staging")


def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Enforce API key on sensitive/destructive mutations.
    - In production/staging: Fails closed. If API_SECRET_KEY is not configured or key is invalid, reject.
    - In local development mode (APP_ENV=development): Allow permissive access only if API_SECRET_KEY is unset.
    """
    if is_production():
        if not API_SECRET_KEY:
            raise HTTPException(
                status_code=500,
                detail="Server configuration error: API_SECRET_KEY must be configured in production mode.",
            )
    else:
        # Development mode
        if not API_SECRET_KEY:
            return True

    key = x_api_key
    if not key and authorization:
        if authorization.lower().startswith("bearer "):
            key = authorization[7:].strip()
        else:
            key = authorization.strip()
    if not key or key != API_SECRET_KEY:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid or missing API key.",
        )
    return True


# Batch ID Validation
BATCH_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")


def validate_batch_id(batch_id: str) -> str:
    """Validate that a batch ID contains only safe alphanumeric, underscore, and hyphen characters."""
    if not batch_id or not BATCH_ID_REGEX.match(batch_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid batch ID: Batch IDs must only contain alphanumeric characters, underscores, and hyphens.",
        )
    return batch_id


# In-memory batch progress tracking
active_batches: Dict[str, BatchProgress] = {}
batch_locks: Dict[str, threading.Lock] = {}


class StartBatchRequest(BaseModel):
    mapping_override: Optional[Dict[str, str]] = None
    dry_run: bool = False
    max_leads: Optional[int] = None
    concurrency: int = 2
    resume: bool = True
    use_browser: bool = True
    use_tor: bool = True
    tor_proxy: Optional[str] = None


def resolve_batch_dir(batch_id: str) -> Path:
    """Resolve directory in canonical data/output/batches/ or legacy data/batches/."""
    clean_id = sanitize_filename(batch_id)
    v2_dir = BATCHES_DIR / clean_id
    if v2_dir.exists():
        return v2_dir
    legacy_dir = LEGACY_BATCHES_DIR / clean_id
    if legacy_dir.exists():
        return legacy_dir
    return v2_dir


def load_all_batches_metadata() -> List[Dict[str, Any]]:
    """Scan batches directories and return summary for all batches."""
    batches = []
    seen_ids = set()

    for b_parent in [BATCHES_DIR, LEGACY_BATCHES_DIR]:
        if not b_parent.exists():
            continue
        for b_dir in b_parent.iterdir():
            if not b_dir.is_dir() or b_dir.name in seen_ids:
                continue
            seen_ids.add(b_dir.name)
            batch_id = b_dir.name
            manifest_file = b_dir / "manifest.json"
            metadata: Dict[str, Any] = {
                "batch_id": batch_id,
                "status": "completed",
                "total_leads": 0,
                "completed_count": 0,
                "partial_count": 0,
                "failed_count": 0,
                "outreach_ready_count": 0,
                "needs_review_count": 0,
                "priority_counts": {"0": 0, "1": 0, "2": 0},
                "created_at": datetime.fromtimestamp(b_dir.stat().st_ctime, timezone.utc).isoformat(),
                "csv_exists": (b_dir / "leads_prioritized.csv").exists(),
                "outreach_ready_exists": (b_dir / "outreach_ready.csv").exists(),
                "needs_review_exists": (b_dir / "needs_review.csv").exists(),
                "errors_exists": (b_dir / "errors.csv").exists(),
                "profiles_count": len(list((b_dir / "profiles").glob("*.json"))) if (b_dir / "profiles").exists() else 0,
            }

            if manifest_file.exists():
                try:
                    with open(manifest_file, "r", encoding="utf-8") as f:
                        m_data = json.load(f)
                        counts = m_data.get("counts", {})
                        s_dist = m_data.get("research_status_distribution", {})
                        c_dist = m_data.get("contact_readiness_distribution", {})
                        metadata.update({
                            "total_leads": counts.get("total", m_data.get("total_processed", 0)),
                            "completed_count": counts.get("completed", s_dist.get("completed", 0)),
                            "partial_count": counts.get("partial", s_dist.get("partial", 0)),
                            "failed_count": counts.get("failed", s_dist.get("failed", 0)),
                            "outreach_ready_count": counts.get("outreach_ready", c_dist.get("ready", 0)),
                            "needs_review_count": counts.get("needs_review", c_dist.get("needs_review", 0)),
                            "priority_counts": m_data.get("priority_distribution", {"0": 0, "1": 0, "2": 0}),
                            "status_distribution": s_dist,
                            "input_filename": m_data.get("metadata", {}).get("input_filename", m_data.get("input_file", "Uploaded File")),
                        })
                except Exception as e:
                    logger.warning(f"Error reading manifest for {batch_id}: {e}")

            # If batch is currently running in memory, override with live state
            if batch_id in active_batches:
                live = active_batches[batch_id]
                metadata.update({
                    "status": live.status,
                    "total_leads": live.total_leads,
                    "processed_leads": live.processed_leads,
                    "completed_count": live.completed_count,
                    "partial_count": live.partial_count,
                    "failed_count": live.failed_count,
                    "outreach_ready_count": live.outreach_ready_count,
                    "needs_review_count": live.needs_review_count,
                    "priority_counts": live.priority_counts,
                    "updated_at": live.updated_at,
                })

            batches.append(metadata)

    batches.sort(key=lambda b: b.get("created_at", ""), reverse=True)
    return batches


@app.get("/api/health")
def health_check():
    """Verify application API and storage health without exposing internal file paths."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "storage": {
            "uploads_writable": os.access(UPLOADS_DIR, os.W_OK),
            "batches_writable": os.access(BATCHES_DIR, os.W_OK),
        },
        "active_batches_count": sum(1 for b in active_batches.values() if b.status == "processing"),
    }


@app.get("/api/tor/status", dependencies=[Depends(verify_api_key)])
def get_tor_status(verify_routing: bool = False):
    """
    Check Tor proxy health, active port, and availability.
    If verify_routing=True, executes an external probe through Tor to verify exit routing.
    """
    manager = TorManager()
    return manager.get_status(verify_routing=verify_routing)


@app.post("/api/tor/start", dependencies=[Depends(verify_api_key)])
def start_tor_proxy():
    """Ensure local Tor daemon is running."""
    manager = TorManager()
    success, message, port = manager.ensure_tor_running()
    return {"success": success, "message": message, "port": port}


@app.get("/api/dashboard/stats", dependencies=[Depends(verify_api_key)])
def get_dashboard_stats():
    """Aggregated metrics across all batches for the dashboard."""
    all_batches = load_all_batches_metadata()
    total_imported = sum(b.get("total_leads", 0) for b in all_batches)
    total_completed = sum(b.get("completed_count", 0) for b in all_batches)
    total_partial = sum(b.get("partial_count", 0) for b in all_batches)
    total_failed = sum(b.get("failed_count", 0) for b in all_batches)
    total_p0 = sum(b.get("priority_counts", {}).get("0", 0) for b in all_batches)
    total_p1 = sum(b.get("priority_counts", {}).get("1", 0) for b in all_batches)
    total_p2 = sum(b.get("priority_counts", {}).get("2", 0) for b in all_batches)

    return {
        "total_leads": total_imported,
        "completed_count": total_completed,
        "review_required_count": total_partial,
        "failed_count": total_failed,
        "priority_0_count": total_p0,
        "priority_1_count": total_p1,
        "priority_2_count": total_p2,
        "total_batches": len(all_batches),
        "recent_batches": all_batches[:5],
    }


MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


@app.post("/api/batches/upload", dependencies=[Depends(verify_api_key)])
async def upload_leads_file(file: UploadFile = File(...)):
    """Upload CSV or XLSX, inspect columns, detect mapping, and preview data."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing")

    filename = Path(file.filename).name  # Prevent directory traversal in filename
    ext = Path(filename).suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Please upload a .csv or .xlsx file."
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File size exceeds maximum allowed limit of 50 MB.",
        )

    # Save to uploads directory using collision-resistant batch ID
    batch_id = create_batch_id()
    while (BATCHES_DIR / batch_id).exists() or (LEGACY_BATCHES_DIR / batch_id).exists():
        batch_id = create_batch_id()

    saved_path = UPLOADS_DIR / f"{batch_id}{ext}"
    with open(saved_path, "wb") as f:
        f.write(content)

    # Inspect file
    importer = LeadImporter()
    try:
        inspection = importer.inspect_file(saved_path, filename=filename, preview_limit=8)
        leads, summary = importer.import_leads(saved_path, filename=filename)
    except Exception as e:
        logger.error(f"Error inspecting uploaded file: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

    # Initialize batch entry
    active_batches[batch_id] = BatchProgress(
        batch_id=batch_id,
        filename=filename,
        status="pending",
        total_leads=len(leads),
        recent_logs=[f"File uploaded: {filename} ({len(leads)} valid leads detected)"],
    )

    return {
        "batch_id": batch_id,
        "filename": filename,
        "size_bytes": len(content),
        "headers": inspection.get("headers", []),
        "detected_mapping": inspection.get("detected_mapping", {}),
        "preview_rows": inspection.get("preview_rows", []),
        "total_rows": summary.total_input_rows,
        "valid_leads_count": summary.valid_leads,
        "duplicate_count": summary.duplicate_records,
        "malformed_count": summary.malformed_rows,
        "validation_errors": summary.validation_errors[:10],
    }


def _run_research_in_thread(
    batch_id: str,
    input_file: Path,
    req: StartBatchRequest,
):
    """Background worker function executing the Scrapling research pipeline."""
    pipeline = ResearchPipeline(output_dir=BATCHES_DIR, concurrency=req.concurrency)

    def on_progress(p: BatchProgress):
        active_batches[batch_id] = p

    try:
        pipeline.run_batch(
            batch_id=batch_id,
            input_file=input_file,
            mapping_override=req.mapping_override,
            max_leads=req.max_leads,
            dry_run=req.dry_run,
            resume=req.resume,
            use_browser=req.use_browser,
            use_tor=req.use_tor,
            tor_proxy=req.tor_proxy,
            progress_callback=on_progress,
        )
    except Exception as e:
        logger.error(f"Batch {batch_id} execution error: {e}", exc_info=True)
        if batch_id in active_batches:
            active_batches[batch_id].status = "failed"
            active_batches[batch_id].errors.append(f"Fatal error: {str(e)}")


@app.post("/api/batches/{batch_id}/start", dependencies=[Depends(verify_api_key)])
def start_research_batch(batch_id: str, req: StartBatchRequest):
    """Initiate research pipeline for an uploaded batch in background."""
    validate_batch_id(batch_id)

    # Prevent concurrent execution
    if batch_id in active_batches and active_batches[batch_id].status == "processing":
        raise HTTPException(
            status_code=409,
            detail=f"Batch '{batch_id}' is currently running and cannot be started concurrently.",
        )

    # Find uploaded file
    matches = list(UPLOADS_DIR.glob(f"{batch_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"No uploaded file found for batch '{batch_id}'")

    input_file = matches[0]

    # Check if this batch is already completed and cannot be silently restarted without resume=True
    batch_dir = resolve_batch_dir(batch_id)
    manifest_file = batch_dir / "manifest.json"
    if manifest_file.exists() and not req.resume:
        try:
            with open(manifest_file, "r", encoding="utf-8") as mf:
                m_info = json.load(mf)
                if m_info.get("status") in ("completed", "partial"):
                    raise HTTPException(
                        status_code=409,
                        detail=f"Batch '{batch_id}' is already completed and immutable. To resume or re-evaluate, set resume=true or upload as a new batch.",
                    )
        except HTTPException:
            raise
        except Exception as e:
            logger.debug(f"Manifest check notice: {e}")

    if batch_id not in active_batches:
        active_batches[batch_id] = BatchProgress(
            batch_id=batch_id,
            filename=input_file.name,
            status="pending",
        )

    active_batches[batch_id].status = "processing"
    active_batches[batch_id].recent_logs.append("Research job dispatched to worker pool.")

    t = threading.Thread(
        target=_run_research_in_thread,
        args=(batch_id, input_file, req),
        daemon=True,
    )
    t.start()

    return {"message": "Research batch started", "batch_id": batch_id}


@app.get("/api/batches", dependencies=[Depends(verify_api_key)])
def list_batches():
    """List all research batches."""
    return load_all_batches_metadata()


@app.get("/api/batches/{batch_id}", dependencies=[Depends(verify_api_key)])
def get_batch_status(batch_id: str):
    """Get status and live progress of a specific batch."""
    validate_batch_id(batch_id)
    clean_id = sanitize_filename(batch_id)
    if clean_id in active_batches:
        return active_batches[clean_id].model_dump()
    if batch_id in active_batches:
        return active_batches[batch_id].model_dump()

    b_dir = resolve_batch_dir(clean_id)
    if not b_dir.exists():
        raise HTTPException(status_code=404, detail="Batch not found")

    manifest_file = b_dir / "manifest.json"
    recent_logs = []
    log_file = b_dir / "scraping.log"
    if not log_file.exists():
        # Fallback check output/scraping.log or data/output/scraping.log
        for alt_log in [Path("output/scraping.log"), Path("data/output/scraping.log")]:
            if alt_log.exists():
                log_file = alt_log
                break

    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8") as lf:
                lines = [l.strip() for l in lf if l.strip()]
                recent_logs = lines[-120:]
        except Exception:
            pass

    total_leads = 0
    completed_count = 0
    partial_count = 0
    failed_count = 0
    priority_counts = {"0": 0, "1": 0, "2": 0}
    filename = "Uploaded Leads File"

    if manifest_file.exists():
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                m_data = json.load(f)
                total_leads = m_data.get("total_processed", 0)
                priority_counts = m_data.get("priority_distribution", {"0": 0, "1": 0, "2": 0})
                s_dist = m_data.get("research_status_distribution", {})
                completed_count = s_dist.get("completed", 0)
                partial_count = s_dist.get("partial", 0)
                failed_count = s_dist.get("failed", 0)
                filename = m_data.get("metadata", {}).get("input_filename", "Uploaded Leads File")
        except Exception as e:
            logger.warning(f"Error reading manifest for {batch_id}: {e}")

    if not recent_logs:
        recent_logs = [
            f"Batch {batch_id} research successfully completed.",
            f"Processed {total_leads} leads ({completed_count} completed, {partial_count} partial, {failed_count} failed).",
            f"Priorities: P0 (Highest Fit)={priority_counts.get('0', 0)}, P1={priority_counts.get('1', 0)}, P2={priority_counts.get('2', 0)}.",
            f"Deliverables generated: leads_prioritized.csv, JSON profiles, manifest.json.",
        ]

    created_iso = datetime.fromtimestamp(b_dir.stat().st_ctime, timezone.utc).isoformat()
    return {
        "batch_id": batch_id,
        "filename": filename,
        "status": "completed",
        "created_at": created_iso,
        "updated_at": created_iso,
        "total_leads": total_leads,
        "processed_leads": total_leads,
        "completed_count": completed_count,
        "partial_count": partial_count,
        "failed_count": failed_count,
        "priority_counts": priority_counts,
        "current_lead_name": None,
        "recent_logs": recent_logs,
        "errors": [],
    }


@app.delete("/api/batches/{batch_id}", dependencies=[Depends(verify_api_key)])
def delete_batch(batch_id: str):
    """Delete a specific batch and all associated outputs."""
    validate_batch_id(batch_id)
    clean_id = sanitize_filename(batch_id)
    if clean_id in active_batches:
        del active_batches[clean_id]

    b_dir = resolve_batch_dir(clean_id)
    if b_dir.exists():
        shutil.rmtree(b_dir, ignore_errors=True)

    # Clean matching upload files
    for upload in UPLOADS_DIR.glob(f"{clean_id}*"):
        try:
            upload.unlink()
        except OSError:
            pass

    return {"message": f"Batch '{batch_id}' deleted successfully"}


@app.delete("/api/batches", dependencies=[Depends(verify_api_key)])
def clear_all_batches():
    """Clear all batch records, profiles, and history across V2 and legacy stores."""
    active_batches.clear()

    # Wipe batches directories
    for b_parent in [BATCHES_DIR, LEGACY_BATCHES_DIR]:
        if b_parent.exists():
            for item in b_parent.iterdir():
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    try:
                        item.unlink()
                    except OSError:
                        pass

    # Wipe uploads directory
    for item in UPLOADS_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            try:
                item.unlink()
            except OSError:
                pass

    return {"message": "All batch history and outputs cleared successfully"}


@app.get("/api/batches/{batch_id}/leads", dependencies=[Depends(verify_api_key)])
def get_batch_leads(
    batch_id: str,
    priority: Optional[str] = Query(None, description="Filter by priority: 0, 1, 2"),
    status: Optional[str] = Query(None, description="Filter by status: completed, partial, failed"),
    search: Optional[str] = Query(None, description="Search term across name, company, title, industry"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
):
    """Retrieve prioritized leads from the generated leads_prioritized.csv."""
    validate_batch_id(batch_id)
    b_dir = resolve_batch_dir(batch_id)
    csv_path = b_dir / "leads_prioritized.csv"

    if not csv_path.exists():
        return {
            "batch_id": batch_id,
            "total_records": 0,
            "page": page,
            "page_size": page_size,
            "leads": [],
            "message": "Prioritized CSV not yet generated for this batch.",
        }

    leads: List[Dict[str, Any]] = []
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        import csv
        reader = csv.DictReader(f)
        for row in reader:
            leads.append(row)

    # Filter by priority
    if priority is not None and priority != "" and priority != "all":
        leads = [l for l in leads if str(l.get("priority", "")).strip() == str(priority).strip()]

    # Filter by status
    if status is not None and status != "" and status != "all":
        leads = [l for l in leads if str(l.get("research_status", "")).strip().lower() == status.strip().lower()]

    # Filter by search
    if search:
        s_lower = search.strip().lower()
        leads = [
            l for l in leads
            if s_lower in l.get("name", "").lower()
            or s_lower in l.get("company", "").lower()
            or s_lower in l.get("job_title", "").lower()
            or s_lower in l.get("industry", "").lower()
            or s_lower in l.get("professional_email", "").lower()
        ]

    # Calculate pagination
    total_matching = len(leads)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paged_leads = leads[start_idx:end_idx]

    return {
        "batch_id": batch_id,
        "total_records": total_matching,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_matching + page_size - 1) // page_size if total_matching > 0 else 1,
        "leads": paged_leads,
    }


@app.get("/api/batches/{batch_id}/leads/{lead_id}/profile", dependencies=[Depends(verify_api_key)])
def get_lead_profile(batch_id: str, lead_id: str):
    """Retrieve full JSON research profile for an individual person."""
    validate_batch_id(batch_id)
    b_dir = resolve_batch_dir(batch_id)
    profiles_dir = b_dir / "profiles"

    if not profiles_dir.exists():
        raise HTTPException(status_code=404, detail="Profiles directory not found for this batch")

    # Match by sanitized lead_id in filename
    clean_id = sanitize_filename(lead_id)
    matched_file = None
    for pf in profiles_dir.glob("*.json"):
        if clean_id in pf.name:
            matched_file = pf
            break

    if not matched_file:
        # Fallback: inspect JSON files
        for pf in profiles_dir.glob("*.json"):
            try:
                with open(pf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("lead_id") == lead_id:
                        matched_file = pf
                        break
            except Exception:
                continue

    if not matched_file or not matched_file.exists():
        raise HTTPException(status_code=404, detail=f"Profile not found for lead '{lead_id}'")

    with open(matched_file, "r", encoding="utf-8") as f:
        profile_json = json.load(f)

    return {
        "batch_id": batch_id,
        "lead_id": lead_id,
        "filename": matched_file.name,
        "profile": profile_json,
    }


@app.get("/api/leads", dependencies=[Depends(verify_api_key)])
def get_leads_global(
    batch_id: Optional[str] = Query(None, description="Batch ID (defaults to latest)"),
    priority: Optional[str] = Query(None, description="Filter by priority: 0, 1, 2"),
    status: Optional[str] = Query(None, description="Filter by status: completed, partial, failed"),
    search: Optional[str] = Query(None, description="Search term across name, company, title, industry"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
):
    """Retrieve prioritized leads. Defaults to most recent batch if batch_id is omitted."""
    target_batch = batch_id
    if not target_batch:
        all_b = load_all_batches_metadata()
        for b in all_b:
            if b.get("csv_exists"):
                target_batch = b["batch_id"]
                break
    if not target_batch:
        return {
            "batch_id": None,
            "total_records": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 1,
            "leads": [],
            "message": "No batches with prioritized leads found.",
        }
    return get_batch_leads(
        batch_id=target_batch,
        priority=priority,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
    )


@app.get("/api/leads/{lead_id}/profile", dependencies=[Depends(verify_api_key)])
def get_lead_profile_direct(lead_id: str, batch_id: Optional[str] = None):
    """Retrieve full JSON research profile by lead_id (searches all batches if batch_id is omitted)."""
    if batch_id:
        return get_lead_profile(batch_id=batch_id, lead_id=lead_id)

    # Search across all batches
    clean_id = sanitize_filename(lead_id)
    for b_dir in sorted(BATCHES_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not b_dir.is_dir():
            continue
        p_dir = b_dir / "profiles"
        if not p_dir.exists():
            continue
        for pf in p_dir.glob("*.json"):
            if clean_id in pf.name:
                with open(pf, "r", encoding="utf-8") as f:
                    return {
                        "batch_id": b_dir.name,
                        "lead_id": lead_id,
                        "filename": pf.name,
                        "profile": json.load(f),
                    }

    # Deep fallback check by reading lead_id inside files
    for b_dir in sorted(BATCHES_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not b_dir.is_dir():
            continue
        p_dir = b_dir / "profiles"
        if not p_dir.exists():
            continue
        for pf in p_dir.glob("*.json"):
            try:
                with open(pf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("lead_id") == lead_id:
                        return {
                            "batch_id": b_dir.name,
                            "lead_id": lead_id,
                            "filename": pf.name,
                            "profile": data,
                        }
            except Exception:
                continue

    raise HTTPException(status_code=404, detail=f"Profile for lead '{lead_id}' not found across any batches.")


@app.get("/api/batches/latest", dependencies=[Depends(verify_api_key)])
def get_latest_batch_info():
    """Retrieve metadata about the latest completed batch."""
    latest_file = OUTPUT_DIR / "latest.json"
    if not latest_file.exists():
        latest_file = DATA_DIR / "latest.json"

    if not latest_file.exists():
        batches = load_all_batches_metadata()
        if batches:
            return {"latest_batch": batches[0]}
        raise HTTPException(status_code=404, detail="No completed batches found")

    with open(latest_file, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/batches/{batch_id}/exports/manifest.json", dependencies=[Depends(verify_api_key)])
def download_manifest_json(batch_id: str):
    """Download manifest.json for a batch."""
    validate_batch_id(batch_id)
    b_dir = resolve_batch_dir(batch_id)
    manifest_path = b_dir / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="manifest.json not found")

    return FileResponse(
        manifest_path,
        media_type="application/json",
        filename=f"{batch_id}_manifest.json",
    )


@app.get("/api/batches/{batch_id}/exports/summary.json", dependencies=[Depends(verify_api_key)])
def download_summary_json(batch_id: str):
    """Download summary.json for a batch."""
    validate_batch_id(batch_id)
    b_dir = resolve_batch_dir(batch_id)
    summary_path = b_dir / "summary.json"
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="summary.json not found")

    return FileResponse(
        summary_path,
        media_type="application/json",
        filename=f"{batch_id}_summary.json",
    )


@app.get("/api/batches/{batch_id}/exports/prioritized.csv", dependencies=[Depends(verify_api_key)])
def download_prioritized_csv(batch_id: str):
    """Download leads_prioritized.csv."""
    validate_batch_id(batch_id)
    b_dir = resolve_batch_dir(batch_id)
    csv_path = b_dir / "leads_prioritized.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="leads_prioritized.csv not found")

    return FileResponse(
        csv_path,
        media_type="text/csv",
        filename=f"{batch_id}_leads_prioritized.csv",
    )


@app.get("/api/batches/{batch_id}/exports/outreach_ready.csv", dependencies=[Depends(verify_api_key)])
def download_outreach_ready_csv(batch_id: str):
    """Download outreach_ready.csv containing only outreach-ready leads."""
    validate_batch_id(batch_id)
    b_dir = resolve_batch_dir(batch_id)
    csv_path = b_dir / "outreach_ready.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="outreach_ready.csv not found for this batch")

    return FileResponse(
        csv_path,
        media_type="text/csv",
        filename=f"{batch_id}_outreach_ready.csv",
    )


@app.get("/api/batches/{batch_id}/exports/needs_review.csv", dependencies=[Depends(verify_api_key)])
def download_needs_review_csv(batch_id: str):
    """Download needs_review.csv containing leads requiring review or research."""
    validate_batch_id(batch_id)
    b_dir = resolve_batch_dir(batch_id)
    csv_path = b_dir / "needs_review.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="needs_review.csv not found for this batch")

    return FileResponse(
        csv_path,
        media_type="text/csv",
        filename=f"{batch_id}_needs_review.csv",
    )


@app.get("/api/batches/{batch_id}/exports/errors.csv", dependencies=[Depends(verify_api_key)])
def download_errors_csv(batch_id: str):
    """Download errors.csv."""
    validate_batch_id(batch_id)
    b_dir = resolve_batch_dir(batch_id)
    errors_path = b_dir / "errors.csv"
    if not errors_path.exists():
        raise HTTPException(status_code=404, detail="errors.csv not found")

    return FileResponse(
        errors_path,
        media_type="text/csv",
        filename=f"{batch_id}_errors.csv",
    )


@app.get("/api/batches/{batch_id}/exports/scraping.log", dependencies=[Depends(verify_api_key)])
def download_scraping_log(batch_id: str):
    """Download scraping.log containing granular web research logs."""
    validate_batch_id(batch_id)
    b_dir = resolve_batch_dir(batch_id)
    log_path = b_dir / "scraping.log"
    if not log_path.exists():
        for alt in [Path("output/scraping.log"), Path("data/output/scraping.log")]:
            if alt.exists():
                log_path = alt
                break

    if not log_path or not log_path.exists():
        raise HTTPException(status_code=404, detail="scraping.log not found for this batch")

    return FileResponse(
        log_path,
        media_type="text/plain",
        filename=f"{batch_id}_scraping.log",
    )


@app.get("/api/batches/{batch_id}/exports/profiles/{filename}", dependencies=[Depends(verify_api_key)])
def download_single_profile(batch_id: str, filename: str):
    """Download a single JSON profile securely."""
    validate_batch_id(batch_id)
    safe_fn = sanitize_filename(Path(filename).stem) + ".json"
    b_dir = resolve_batch_dir(batch_id)
    profile_path = b_dir / "profiles" / safe_fn

    if not profile_path.exists():
        raise HTTPException(status_code=404, detail="Profile JSON file not found")

    return FileResponse(
        profile_path,
        media_type="application/json",
        filename=safe_fn,
    )


@app.get("/api/batches/{batch_id}/exports/zip", dependencies=[Depends(verify_api_key)])
def download_batch_zip(batch_id: str):
    """Create and stream a ZIP archive of all batch assets."""
    validate_batch_id(batch_id)
    b_dir = resolve_batch_dir(batch_id)
    if not b_dir.exists():
        raise HTTPException(status_code=404, detail="Batch directory not found")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in b_dir.rglob("*"):
            if not file_path.is_file() or file_path.name.endswith(".tmp"):
                continue

            rel_path = file_path.relative_to(b_dir)

            # Skip hidden files or checkpoint directories
            if any(part.startswith(".") for part in rel_path.parts):
                continue

            # In profiles directory, only include official ranked profiles (person_001_... to person_144_...)
            if "profiles" in rel_path.parts:
                if not re.match(r"^person_\d{3}_.*\.json$", file_path.name):
                    continue

            zip_file.write(file_path, arcname=str(rel_path))

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={batch_id}_export.zip"},
    )


@app.get("/")
def serve_index():
    return {
        "service": "SealAPI Lead Research Engine",
        "version": "1.0.0",
        "status": "online",
        "frontend": "Next.js App Router (port 3000)",
        "docs_url": "/docs",
        "api_endpoints": [
            "/api/health",
            "/api/dashboard/stats",
            "/api/batches/upload",
            "/api/batches",
            "/api/leads",
        ],
    }
