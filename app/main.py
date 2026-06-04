from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.analytics import (
    compute_anomalies,
    compute_funnel,
    compute_heatmap,
    compute_live_analytics,
    compute_metrics,
)
from app.config import settings
from app.dashboard_html import dashboard_html
from app.layout import STORE_ALIASES, load_layout
from app.logging_config import configure_logging, request_logging_middleware
from app.pos_import import import_pos_csv
from app.schemas import (
    EventIn,
    HealthResponse,
    IngestError,
    IngestResponse,
    VideoJobResponse,
    VideoProcessAllRequest,
    VideoProcessRequest,
)
from app.storage import (
    check_database,
    count_events,
    fetch_recent_events,
    init_db,
    insert_events,
    latest_event_timestamp,
    latest_event_timestamp_by_store,
)
from app.time_utils import parse_timestamp
from app.video_jobs import create_all_videos_job, create_video_job, get_job, list_videos


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    init_db()
    import_pos_csv(settings.pos_csv_path)
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.middleware("http")(request_logging_middleware)

_LIVE_CACHE_TTL_SECONDS = 4.0
_live_cache_lock = threading.Lock()
_live_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "service": settings.app_name,
        "status": "ok",
        "docs": "/docs",
        "dashboard": "/dashboard",
        "health": "/health",
        "example_metrics": "/stores/STORE_BLR_002/metrics",
    }


@app.exception_handler(sqlite3.Error)
async def sqlite_exception_handler(request: Request, exc: sqlite3.Error) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": "DATABASE_UNAVAILABLE",
            "message": "The analytics database is unavailable.",
            "trace_id": getattr(request.state, "trace_id", None),
        },
    )


def _extract_payload(body: Any) -> list[Any]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict) and isinstance(body.get("events"), list):
        return body["events"]
    raise HTTPException(
        status_code=400,
        detail={
            "error": "INVALID_PAYLOAD",
            "message": "Expected a JSON array or an object with an events array.",
        },
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    return dashboard_html()


CAMERA_VIDEO_FILES = {
    "CAM_1": "CAM 1.mp4",
    "CAM_2": "CAM 2.mp4",
    "CAM_3": "CAM 3.mp4",
    "CAM_4": "CAM 4.mp4",
    "CAM_5": "CAM 5.mp4",
}


def _clip_library_root() -> Path:
    docker_path = Path("/data/clips")
    if docker_path.exists():
        return docker_path
    return Path("data/clips")


def _browser_clip_root() -> Path:
    docker_path = Path("/data/browser_clips")
    if docker_path.exists():
        return docker_path
    return Path("data/browser_clips")


def _camera_id_from_filename(path: Path, fallback_index: int) -> str:
    stem = path.stem.lower()
    match = re.search(r"cam\s*[_ -]?(\d+)", stem)
    if match:
        return f"CAM_{match.group(1)}"
    if "billing" in stem:
        return "CAM_5"
    if "entry 1" in stem or "entry_1" in stem:
        return "CAM_3"
    if "entry 2" in stem or "entry_2" in stem:
        return "CAM_4"
    if "entry" in stem:
        return "CAM_3"
    if "zone" in stem:
        return "CAM_1"
    return f"CAM_{fallback_index}"


def _clip_sets() -> list[dict[str, Any]]:
    root = _clip_library_root()
    sets = [{"id": "sample", "label": "Sample CCTV", "path": str(settings.cctv_dir_path)}]
    if root.exists():
        for folder in sorted(path for path in root.iterdir() if path.is_dir()):
            sets.append({"id": folder.name, "label": folder.name, "path": str(folder)})
    return sets


def _camera_files_for_clip_set(clip_set: str) -> dict[str, Path]:
    if clip_set == "sample":
        return {camera_id: settings.cctv_dir_path / filename for camera_id, filename in CAMERA_VIDEO_FILES.items()}
    root = _clip_library_root()
    folder = (root / clip_set).resolve()
    try:
        folder.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid clip_set") from exc
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=404, detail=f"Clip set not found: {clip_set}")
    camera_files: dict[str, Path] = {}
    for index, path in enumerate(sorted(folder.glob("*.mp4")), start=1):
        camera_id = _camera_id_from_filename(path, index)
        if camera_id not in camera_files:
            camera_files[camera_id] = path
    return camera_files


def _browser_video_path(clip_set: str, camera_id: str, original_path: Path) -> Path:
    preview = _browser_clip_root() / clip_set / f"{camera_id}.mp4"
    return preview if preview.exists() else original_path


@app.get("/media/cameras")
async def camera_media(clip_set: str = "sample") -> dict[str, Any]:
    layout = load_layout()
    stores = layout.get("stores", {})
    store = stores.get("STORE_BLR_002") or stores.get(STORE_ALIASES.get("STORE_BLR_002", ""), {})
    cameras = []
    camera_files = _camera_files_for_clip_set(clip_set)
    for camera_id, path in sorted(camera_files.items()):
        camera_config = (store.get("cameras") or {}).get(camera_id, {})
        cameras.append(
            {
                "camera_id": camera_id,
                "label": path.name,
                "available": path.exists(),
                "url": f"/media/cameras/{camera_id}.mp4?clip_set={clip_set}",
                "detection_filter": camera_config.get("detection_filter", {}),
            }
        )
    return {"clip_set": clip_set, "clip_sets": _clip_sets(), "cameras": cameras}


@app.get("/videos")
async def videos() -> dict[str, Any]:
    return list_videos()


@app.post("/videos/process", response_model=VideoJobResponse, status_code=202)
async def process_video(request: VideoProcessRequest) -> VideoJobResponse:
    if not settings.enable_in_process_pipeline:
        raise HTTPException(
            status_code=503,
            detail=(
                "In-process custom YOLOv8 pipeline is disabled in this API image. "
                "Use `docker compose --profile live up --build` for raw CCTV processing."
            ),
        )
    try:
        return create_video_job(request)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/videos/process-all", response_model=VideoJobResponse, status_code=202)
async def process_all_videos(request: VideoProcessAllRequest) -> VideoJobResponse:
    if not settings.enable_in_process_pipeline:
        raise HTTPException(
            status_code=503,
            detail=(
                "In-process custom YOLOv8 pipeline is disabled in this API image. "
                "Use `docker compose --profile live up --build` for raw CCTV processing."
            ),
        )
    try:
        return create_all_videos_job(request)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/videos/jobs/{job_id}", response_model=VideoJobResponse)
async def video_job(job_id: str) -> VideoJobResponse:
    job = get_job(job_id)
    if job.status == "not_found":
        raise HTTPException(status_code=404, detail="Video processing job not found.")
    return job


@app.get("/media/cameras/{camera_id}.mp4")
async def camera_video(camera_id: str, request: Request = None, clip_set: str = "sample") -> Response:
    camera_files = _camera_files_for_clip_set(clip_set)
    if camera_id not in camera_files:
        raise HTTPException(status_code=404, detail="Unknown camera_id")
    path = _browser_video_path(clip_set, camera_id, camera_files[camera_id])
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Camera video not found: {camera_id}")
    return _video_response(path, request.headers.get("range") if request else None)


def _video_response(path: Path, range_header: str | None) -> Response:
    file_size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes"}
    if not range_header:
        headers["Content-Length"] = str(file_size)
        return StreamingResponse(
            _iter_file_range(path, 0, file_size - 1),
            media_type="video/mp4",
            headers=headers,
        )

    try:
        unit, value = range_header.split("=", 1)
        if unit.strip().lower() != "bytes":
            raise ValueError
        start_text, end_text = value.split("-", 1)
        start = int(start_text) if start_text else 0
        end = int(end_text) if end_text else file_size - 1
        start = max(0, start)
        end = min(file_size - 1, end)
        if start > end:
            raise ValueError
    except ValueError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    content_length = end - start + 1
    headers.update(
        {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(content_length),
        }
    )
    return StreamingResponse(
        _iter_file_range(path, start, end),
        status_code=206,
        media_type="video/mp4",
        headers=headers,
    )


def _iter_file_range(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024):
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = handle.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@app.post("/events/ingest", response_model=IngestResponse)
async def ingest_events(request: Request, body: Any = Body(...)) -> IngestResponse:
    payload = _extract_payload(body)
    request.state.event_count = len(payload)
    if payload and isinstance(payload[0], dict):
        request.state.store_id = payload[0].get("store_id")
    if len(payload) > settings.ingest_batch_limit:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "BATCH_TOO_LARGE",
                "message": f"Maximum batch size is {settings.ingest_batch_limit}.",
            },
        )

    valid: list[EventIn] = []
    errors: list[IngestError] = []
    for index, raw_event in enumerate(payload):
        event_id = raw_event.get("event_id") if isinstance(raw_event, dict) else None
        try:
            valid.append(EventIn.model_validate(raw_event))
        except ValidationError as exc:
            first = exc.errors()[0]
            errors.append(
                IngestError(
                    index=index,
                    event_id=event_id,
                    code="INVALID_EVENT",
                    message=f"{'.'.join(str(part) for part in first['loc'])}: {first['msg']}",
                )
            )

    accepted, duplicates = insert_events(valid)
    return IngestResponse(
        accepted=accepted,
        duplicates=duplicates,
        rejected=len(errors),
        errors=errors,
    )


@app.get("/stores/{id}/metrics")
async def metrics(id: str) -> dict[str, Any]:
    return await run_in_threadpool(compute_metrics, id)


@app.get("/stores/{id}/events")
async def recent_events(id: str, limit: int = 10) -> dict[str, Any]:
    rows = await run_in_threadpool(fetch_recent_events, id, limit)
    events = []
    for row in rows:
        events.append(
            {
                "event_id": row["event_id"],
                "store_id": row["store_id"],
                "camera_id": row["camera_id"],
                "visitor_id": row["visitor_id"],
                "event_type": row["event_type"],
                "timestamp": row["timestamp"],
                "zone_id": row["zone_id"],
                "dwell_ms": row["dwell_ms"],
                "is_staff": bool(row["is_staff"]),
                "confidence": row["confidence"],
                "metadata": json.loads(row["metadata_json"]),
            }
        )
    return {"store_id": id, "count": len(events), "events": events}


@app.get("/stores/{id}/live")
async def live_snapshot(id: str, limit: int = 8) -> dict[str, Any]:
    return await run_in_threadpool(_live_snapshot_cached, id, limit)


def _live_snapshot_cached(id: str, limit: int = 8) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 2000))
    cache_key = (id, safe_limit)
    now = time.monotonic()
    with _live_cache_lock:
        cached = _live_cache.get(cache_key)
        if cached and now - cached[0] < _LIVE_CACHE_TTL_SECONDS:
            return cached[1]
        snapshot = _live_snapshot_sync(id, safe_limit)
        _live_cache[cache_key] = (time.monotonic(), snapshot)
        return snapshot


def _live_snapshot_sync(id: str, limit: int = 8) -> dict[str, Any]:
    events = []
    for row in fetch_recent_events(id, limit):
        events.append(
            {
                "event_id": row["event_id"],
                "store_id": row["store_id"],
                "camera_id": row["camera_id"],
                "visitor_id": row["visitor_id"],
                "event_type": row["event_type"],
                "timestamp": row["timestamp"],
                "zone_id": row["zone_id"],
                "dwell_ms": row["dwell_ms"],
                "is_staff": bool(row["is_staff"]),
                "confidence": row["confidence"],
                "metadata": json.loads(row["metadata_json"]),
            }
        )
    analytics = compute_live_analytics(id)
    return {
        "store_id": id,
        "event_count": count_events(id),
        "last_event_timestamp": latest_event_timestamp(id),
        "metrics": analytics["metrics"],
        "funnel": analytics["funnel"],
        "heatmap": analytics["heatmap"],
        "anomalies": analytics["anomalies"],
        "recent_events": events,
    }


@app.get("/stores/{id}/funnel")
async def funnel(id: str) -> dict[str, Any]:
    return await run_in_threadpool(compute_funnel, id)


@app.get("/stores/{id}/heatmap")
async def heatmap(id: str) -> dict[str, Any]:
    return await run_in_threadpool(compute_heatmap, id)


@app.get("/stores/{id}/anomalies")
async def anomalies(id: str) -> dict[str, Any]:
    return await run_in_threadpool(compute_anomalies, id)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return await run_in_threadpool(_health_sync)


def _health_sync() -> HealthResponse:
    db_ok = check_database()
    latest_by_store = latest_event_timestamp_by_store() if db_ok else {}
    warnings: list[dict[str, Any]] = []
    stale_cutoff = datetime.now(UTC) - timedelta(minutes=settings.stale_feed_minutes)
    for store_id, timestamp in latest_by_store.items():
        if timestamp and parse_timestamp(timestamp) < stale_cutoff:
            warnings.append(
                {
                    "store_id": store_id,
                    "code": "STALE_FEED",
                    "message": f"No events received in the last {settings.stale_feed_minutes} minutes.",
                    "last_event_timestamp": timestamp,
                }
            )
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        database="ok" if db_ok else "unavailable",
        last_event_timestamp_per_store=latest_by_store,
        warnings=warnings,
    )
