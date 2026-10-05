"""FastAPI server: upload a reference + comparison video, align, score, serve results and media.

Run:  .venv/bin/uvicorn server.app:app --reload --port 8000
See CONTRACT.md section 3 for the endpoints.
"""
from __future__ import annotations

import importlib
import json
import os
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from dancecv.config import REPO_ROOT, Params
from dancecv.pipeline import run_from_alignment

JOBS_DIR = REPO_ROOT / "outputs" / "jobs"
# Which alignment implementation to use: "stub" (dancecv.alignment.stub) or "audio" (Wei's
# dancecv.alignment.audio). Both expose align(ref_path, comp_path, out_dir, trim=True) -> Alignment.
ALIGNER = os.environ.get("DANCECV_ALIGNER", "stub")

Status = Literal["queued", "aligning", "pose", "scoring", "done", "error"]

app = FastAPI(title="dance-cv")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------------------
# Job state: in memory, mirrored to <job>/status.json so it survives a server restart.
# --------------------------------------------------------------------------------------
class JobStatus(BaseModel):
    job_id: str
    status: Status = "queued"
    progress: float = 0.0
    error: Optional[str] = None
    updated: float = 0.0


_jobs: dict[str, JobStatus] = {}
_lock = threading.Lock()

# pipeline stage -> (status, progress range)
_STAGES: dict[str, tuple[Status, float, float]] = {
    "trim": ("aligning", 0.10, 0.15),
    "pose": ("pose", 0.15, 0.80),
    "scoring": ("scoring", 0.80, 0.85),
    "debug": ("scoring", 0.85, 0.99),
    "done": ("done", 1.0, 1.0),
}


def _job_dir(job_id: str) -> Path:
    if not job_id.isalnum():  # ids are uuid hex; reject anything path-like
        raise HTTPException(404, "unknown job")
    return JOBS_DIR / job_id


def _set(job_id: str, **fields) -> None:
    with _lock:
        js = _jobs.get(job_id) or JobStatus(job_id=job_id)
        js = js.model_copy(update={**fields, "updated": time.time()})
        _jobs[job_id] = js
        (JOBS_DIR / job_id / "status.json").write_text(js.model_dump_json())


def _get(job_id: str) -> JobStatus:
    with _lock:
        if job_id in _jobs:
            return _jobs[job_id]
    f = _job_dir(job_id) / "status.json"
    if not f.exists():
        raise HTTPException(404, "unknown job")
    return JobStatus.model_validate_json(f.read_text())


def _get_aligner():
    module = {"stub": "dancecv.alignment.stub", "audio": "dancecv.alignment.audio"}[ALIGNER]
    return importlib.import_module(module).align


def _progress(job_id: str):
    def report(stage: str, frac: float) -> None:
        status, lo, hi = _STAGES.get(stage, ("scoring", 0.8, 0.99))
        _set(job_id, status=status, progress=round(lo + (hi - lo) * frac, 3))
    return report


def _run_job(job_id: str, ref: Optional[Path], comp: Optional[Path], offset: Optional[float],
             alignment_path: Optional[Path], debug: bool) -> None:
    out = JOBS_DIR / job_id
    try:
        if alignment_path is None:
            _set(job_id, status="aligning", progress=0.02)
            align = _get_aligner()
            if ALIGNER == "stub":
                method = "zero" if offset is not None else "xcorr"
                align(ref, comp, out, trim=True, method=method, offset=offset)
            else:
                align(ref, comp, out, trim=True)
            alignment_path = out / "alignment.json"
        run_from_alignment(alignment_path, out, Params(), debug=debug, progress=_progress(job_id))
        _set(job_id, status="done", progress=1.0)
    except Exception as e:  # report any failure to the client
        traceback.print_exc()
        _set(job_id, status="error", error=f"{type(e).__name__}: {e}")


def _start(job_id: str, **kwargs) -> dict:
    _set(job_id, status="queued", progress=0.0)
    threading.Thread(target=_run_job, args=(job_id,), kwargs=kwargs, daemon=True).start()
    return {"job_id": job_id}


async def _save_upload(upload: UploadFile, dst_stem: Path) -> Path:
    suffix = Path(upload.filename or "").suffix.lower() or ".mp4"
    dst = dst_stem.with_suffix(suffix)
    with open(dst, "wb") as f:
        while chunk := await upload.read(1 << 20):
            f.write(chunk)
    return dst


# --------------------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------------------
@app.post("/api/jobs")
async def create_job(
    reference: UploadFile = File(...),
    comparison: UploadFile = File(...),
    offset_seconds: Optional[float] = Form(None),
    debug: bool = Form(True),
) -> dict:
    job_id = uuid.uuid4().hex
    out = JOBS_DIR / job_id
    out.mkdir(parents=True)
    ref = await _save_upload(reference, out / "reference")
    comp = await _save_upload(comparison, out / "comparison")
    return _start(job_id, ref=ref, comp=comp, offset=offset_seconds, alignment_path=None, debug=debug)


class FromAlignment(BaseModel):
    alignment_path: str
    debug: bool = True


@app.post("/api/jobs/from-alignment")
def create_job_from_alignment(body: FromAlignment) -> dict:
    path = Path(body.alignment_path).resolve()
    if not path.is_file():
        raise HTTPException(400, f"alignment file not found: {path}")
    job_id = uuid.uuid4().hex
    (JOBS_DIR / job_id).mkdir(parents=True)
    return _start(job_id, ref=None, comp=None, offset=None, alignment_path=path, debug=body.debug)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> JobStatus:
    return _get(job_id)


def _results(job_id: str) -> dict:
    f = _job_dir(job_id) / "results.json"
    if not f.exists():
        raise HTTPException(404, "results not ready")
    return json.loads(f.read_text())


@app.get("/api/jobs/{job_id}/results")
def job_results(job_id: str) -> dict:
    return _results(job_id)


@app.get("/api/jobs/{job_id}/media/{kind}")
def job_media(job_id: str, kind: Literal["reference", "comparison", "debug"]) -> FileResponse:
    media = _results(job_id)["media"]
    key = {"reference": "reference_trimmed", "comparison": "comparison_trimmed", "debug": "debug_video"}[kind]
    if not media.get(key):
        raise HTTPException(404, f"no {kind} media for this job")
    path = (_job_dir(job_id) / media[key]).resolve()
    if not path.is_file():
        raise HTTPException(404, f"{kind} media missing on disk")
    return FileResponse(path, media_type="video/mp4")
