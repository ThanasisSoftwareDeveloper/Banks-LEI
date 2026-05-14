"""
FindLEI  –  FastAPI backend
=============================
Endpoints
---------
POST /api/upload              Upload Excel; returns job_id + preview
POST /api/process/{job_id}    Start async LEI batch check
GET  /api/stream/{job_id}     SSE stream (real-time progress)
GET  /api/status/{job_id}     Poll-based status + results
GET  /api/download/{job_id}   Download enriched Excel
GET  /                        Serve frontend (static/index.html)
"""

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from excel_handler import ExcelReadError, read_lei_from_excel, write_results_to_excel
from lei_checker import check_lei_batch
from log_config import setup_logging
from metrics import (
    active_jobs, http_requests_total, job_duration_seconds,
    jobs_total, lei_duration_seconds, leis_checked_total, metrics_response,
)

# ── Per-IP Upload Rate Limiter ──────────────────────────────────────────────
from collections import defaultdict
import threading

RATE_LIMIT_UPLOADS = 5        # max uploads per IP
RATE_LIMIT_WINDOW  = 60       # seconds

_upload_log: dict = defaultdict(list)
_upload_lock = threading.Lock()

def _check_upload_rate_limit(ip: str) -> bool:
    """Returns True if allowed, False if rate limit exceeded."""
    now = time.time()
    with _upload_lock:
        timestamps = _upload_log[ip]
        # κράτα μόνο τα timestamps εντός του window
        _upload_log[ip] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
        if len(_upload_log[ip]) >= RATE_LIMIT_UPLOADS:
            return False
        _upload_log[ip].append(now)
        return True


# ── Logging ───────────────────────────────────────────────────────────────────
setup_logging()
logger = logging.getLogger("findlei.main")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="FindLEI API",
    description="LEI batch lookup for banking compliance",
    version="1.0.0",
)
@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    if request.method == "POST" and "/api/upload" in request.url.path:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 10 * 1024 * 1024:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=413, content={"detail": "File too large (max 10 MB)"})
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── HTTP instrumentation middleware ───────────────────────────────────────────
@app.middleware("http")
async def _instrument(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    http_requests_total.labels(
        method=request.method,
        path=request.url.path,
        status_code=str(response.status_code),
    ).inc()
    logger.debug(
        "http request",
        extra={
            "method":      request.method,
            "path":        request.url.path,
            "status":      response.status_code,
            "duration_ms": round((time.perf_counter() - start) * 1000, 1),
        },
    )
    return response


# ── Health & observability ────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "active_jobs": active_jobs._value.get()}


@app.get("/metrics")
async def prometheus_metrics():
    body, content_type = metrics_response()
    return Response(content=body, media_type=content_type)


# ── In-memory job store (replace with Redis for multi-worker deployments) ─────
# jobs[job_id] = {
#   status:       "pending" | "processing" | "completed" | "error"
#   leis:         List[str]
#   results:      List[dict]
#   progress:     int  (count resolved so far)
#   error_msg:    str
#   original_bytes: bytes
#   filename:     str
#   column_info:  dict
# }
jobs: Dict[str, dict] = {}

# ── Job Limits ────────────────────────────────────────────────────────────────
MAX_JOBS_PER_IP    = 3   # max active jobs per IP
MAX_JOBS_GLOBAL    = 50  # max active jobs globally

def _count_active_jobs_for_ip(ip: str) -> int:
    return sum(
        1 for j in jobs.values()
        if j.get("client_ip") == ip and j.get("status") in ("pending", "processing")
    )

def _count_active_jobs_global() -> int:
    return sum(
        1 for j in jobs.values()
        if j.get("status") in ("pending", "processing")
    )



# ── Helpers ───────────────────────────────────────────────────────────────────
def _get_job(job_id: str) -> dict:
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]

def _validate_file_magic(content: bytes, suffix: str) -> bool:
    """Validate file content matches its extension via magic bytes."""
    if suffix in {".xlsx", ".xlsm", ".ods"}:
        return content[:4] == b"PK\x03\x04"
    if suffix == ".xls":
        return content[:8] == b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
    return False


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_excel(request: Request, file: UploadFile = File(...)):
    """
    Receive an Excel file, detect the LEI column, return a job_id + preview.
    """
    allowed_exts = {".xlsx", ".xlsm", ".xls", ".ods"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Use .xlsx, .ods or .xls",
        )
        
    client_ip = request.client.host if request.client else "unknown"
    if not _check_upload_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many uploads. Please wait before trying again."
        )
    if _count_active_jobs_global() >= MAX_JOBS_GLOBAL:
        raise HTTPException(status_code=503, detail="Server busy. Try again later.")
    if _count_active_jobs_for_ip(client_ip) >= MAX_JOBS_PER_IP:
        raise HTTPException(status_code=429, detail="Too many active jobs. Wait for yours to complete.")



    MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

    # Έλεγχος Content-Length header πριν διαβαστεί το αρχείο
    content_length = file.size
    if content_length is not None and content_length > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    content = await file.read()
    if not _validate_file_magic(content, suffix):
        raise HTTPException(
            status_code=400,
            detail="File content does not match the declared file type."
        )
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    try:
        leis, column_info = read_lei_from_excel(content, file.filename)
    except ExcelReadError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not leis:
        raise HTTPException(status_code=422, detail="No LEI codes found in the file")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status":         "pending",
        "leis":           leis,
        "results":        [],
        "progress":       0,
        "error_msg":      "",
        "original_bytes": content,
        "filename":       file.filename,
        "column_info":    column_info,
        "client_ip":    client_ip,
    }

    # Filter out blanks/invalids for display
    non_blank = [l for l in leis if l.strip()]
    logger.info("Job %s created: %d LEIs from '%s'", job_id, len(non_blank), file.filename)

    return {
        "job_id":    job_id,
        "lei_count": len(non_blank),
        "filename":  file.filename,
        "preview":   non_blank[:8],
    }


@app.post("/api/process/{job_id}")
async def start_processing(job_id: str, background_tasks: BackgroundTasks):
    """Kick off the background LEI-checking task."""
    job = _get_job(job_id)
    if job["status"] not in ("pending",):
        raise HTTPException(status_code=409, detail=f"Job is already {job['status']}")

    job["status"] = "processing"
    background_tasks.add_task(_run_job, job_id)
    return {"status": "processing", "job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """Poll-based status endpoint."""
    job = _get_job(job_id)
    non_blank_total = len([l for l in job["leis"] if l.strip()])
    return {
        "status":    job["status"],
        "progress":  job["progress"],
        "total":     non_blank_total,
        "results":   job["results"],
        "error_msg": job.get("error_msg", ""),
    }


@app.get("/api/stream/{job_id}")
async def stream_progress(job_id: str):
    """
    Server-Sent Events stream.
    Each event carries: status, progress, total, latest_result.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def generator():
        while True:
            job = jobs.get(job_id)
            if job is None:
                break

            non_blank_total = len([l for l in job["leis"] if l.strip()])
            payload = {
                "status":        job["status"],
                "progress":      job["progress"],
                "total":         non_blank_total,
                "latest_result": job["results"][-1] if job["results"] else None,
                "error_msg":     job.get("error_msg", ""),
            }
            yield f"data: {json.dumps(payload)}\n\n"

            if job["status"] in ("completed", "error"):
                break

            await asyncio.sleep(0.6)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":      "no-cache",
            "X-Accel-Buffering":  "no",   # disables nginx proxy buffering
        },
    )


@app.get("/api/download/{job_id}")
async def download_results(job_id: str):
    """Return the enriched Excel file."""
    job = _get_job(job_id)
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail="Job not completed yet")
    if not job["results"]:
        raise HTTPException(status_code=422, detail="No results to export")

    try:
        out_bytes = write_results_to_excel(
            job["original_bytes"],
            job["results"],
            job["column_info"],
        )
    except Exception as exc:
        logger.exception("Excel write error for job %s", job_id)
        raise HTTPException(status_code=500, detail=f"Excel write failed: {exc}")

    stem   = Path(job["filename"]).stem
    suffix = Path(job["filename"]).suffix or ".xlsx"
    dl_name = f"{stem}_LEI_results{suffix}"

    return Response(
        content=out_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{dl_name}"'},
    )


# ── Background task ───────────────────────────────────────────────────────────
async def _run_job(job_id: str):
    job = jobs[job_id]
    active_jobs.inc()
    t0 = time.perf_counter()
    try:
        def on_progress(idx: int, result: dict):
            job["progress"] = idx + 1
            job["results"].append(result)
            src = (result.get("source") or "not_found").lower().replace(" + ", "_and_").replace("-", "_")
            leis_checked_total.labels(source=src).inc()

        await check_lei_batch(job["leis"], on_progress=on_progress)
        job["status"] = "completed"
        jobs_total.labels(status="completed").inc()
        job_duration_seconds.observe(time.perf_counter() - t0)
        logger.info("job_completed", extra={"job_id": job_id, "count": len(job["results"])})

    except Exception as exc:
        logger.exception("job_failed", extra={"job_id": job_id, "error": str(exc)})
        job["status"]    = "error"
        job["error_msg"] = str(exc)
        jobs_total.labels(status="error").inc()
    finally:
        active_jobs.dec()


# ── Static frontend ───────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))

# Mount remaining static assets (CSS, JS, icons)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
