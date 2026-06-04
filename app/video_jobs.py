from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.schemas import EventIn, VideoJobResponse, VideoProcessAllRequest, VideoProcessRequest
from app.storage import insert_events
from pipeline.detect import VideoProcessor
from pipeline.enrich_events import enrich_billing_abandonment_file
from pipeline.run_all import CAMERA_FILES, process_all_cameras


JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def list_videos() -> dict[str, Any]:
    video_dir = settings.cctv_dir_path
    videos = []
    if video_dir.exists():
        for path in sorted(video_dir.glob("*.mp4")):
            videos.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    return {
        "video_dir": str(video_dir),
        "exists": video_dir.exists(),
        "count": len(videos),
        "videos": videos,
    }


def create_video_job(request: VideoProcessRequest) -> VideoJobResponse:
    job_id = uuid.uuid4().hex
    output_path = Path("data") / "jobs" / f"{job_id}.jsonl"
    video_path = _resolve_path(request.video_path, default=settings.cctv_dir_path / "CAM 1.mp4")
    _set_job(
        job_id,
        {
            "job_id": job_id,
            "status": "queued",
            "message": "Video processing job queued.",
            "output_path": str(output_path),
            "events_written": 0,
            "events_ingested": 0,
            "duplicates": 0,
            "error": None,
            "created_at": _now(),
            "updated_at": _now(),
        },
    )

    thread = threading.Thread(
        target=_run_single_video_job,
        args=(job_id, request, video_path, output_path),
        daemon=True,
    )
    thread.start()
    return get_job(job_id)


def create_all_videos_job(request: VideoProcessAllRequest) -> VideoJobResponse:
    job_id = uuid.uuid4().hex
    output_path = Path("data") / "jobs" / f"{job_id}.jsonl"
    video_dir = _resolve_path(request.video_dir, default=settings.cctv_dir_path)
    _set_job(
        job_id,
        {
            "job_id": job_id,
            "status": "queued",
            "message": "All-camera processing job queued.",
            "output_path": str(output_path),
            "events_written": 0,
            "events_ingested": 0,
            "duplicates": 0,
            "error": None,
            "created_at": _now(),
            "updated_at": _now(),
        },
    )

    thread = threading.Thread(
        target=_run_all_videos_job,
        args=(job_id, request, video_dir, output_path),
        daemon=True,
    )
    thread.start()
    return get_job(job_id)


def get_job(job_id: str) -> VideoJobResponse:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return VideoJobResponse(
            job_id=job_id,
            status="not_found",
            message="Video processing job was not found.",
        )
    return VideoJobResponse.model_validate(job)


def _run_single_video_job(
    job_id: str,
    request: VideoProcessRequest,
    video_path: Path,
    output_path: Path,
) -> None:
    try:
        _update_job(job_id, status="running", message=f"Processing {video_path.name}.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        processor = VideoProcessor(
            video_path=video_path,
            output_path=output_path,
            layout_path=settings.store_layout_path,
            store_id=request.store_id,
            camera_id=request.camera_id,
            model_path=Path(request.model),
            clip_start=request.clip_start.astimezone(UTC),
            frame_stride=request.frame_stride,
            confidence_threshold=request.confidence_threshold,
            inference_imgsz=request.imgsz,
            tracking_backend=request.tracker,
            clip_set=request.clip_set,
        )
        events_written = processor.run()
        if settings.pos_csv_path.exists():
            events_written = enrich_billing_abandonment_file(
                output_path,
                output_path,
                settings.pos_csv_path,
            )
        events_ingested, duplicates = _ingest_output(output_path) if request.ingest else (0, 0)
        _update_job(
            job_id,
            status="completed",
            message="Video processed successfully.",
            events_written=events_written,
            events_ingested=events_ingested,
            duplicates=duplicates,
        )
    except Exception as exc:
        _update_job(job_id, status="failed", message="Video processing failed.", error=str(exc))


def _run_all_videos_job(
    job_id: str,
    request: VideoProcessAllRequest,
    video_dir: Path,
    output_path: Path,
) -> None:
    try:
        _update_job(job_id, status="running", message=f"Processing cameras in {video_dir}.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = process_all_cameras(
            video_dir=video_dir,
            output=output_path,
            layout=settings.store_layout_path,
            store_id=request.store_id,
            model=Path(request.model),
            clip_start=request.clip_start.astimezone(UTC),
            frame_stride=request.frame_stride,
            confidence_threshold=request.confidence_threshold,
            inference_imgsz=request.imgsz,
            tracking_backend=request.tracker,
            pos_csv=settings.pos_csv_path if settings.pos_csv_path.exists() else None,
            stitch=request.stitch,
            clip_set=request.clip_set,
        )
        events_written = int(
            result.get("enriched_events")
            or result.get("stitched_events")
            or result.get("combined_events")
            or 0
        )
        events_ingested, duplicates = _ingest_output(output_path) if request.ingest else (0, 0)
        _update_job(
            job_id,
            status="completed",
            message="All-camera processing completed successfully.",
            events_written=events_written,
            events_ingested=events_ingested,
            duplicates=duplicates,
        )
    except Exception as exc:
        _update_job(job_id, status="failed", message="All-camera processing failed.", error=str(exc))


def _ingest_output(path: Path) -> tuple[int, int]:
    accepted_total = 0
    duplicates_total = 0
    batch: list[EventIn] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            batch.append(EventIn.model_validate(json.loads(line)))
            if len(batch) >= settings.ingest_batch_limit:
                accepted, duplicates = insert_events(batch)
                accepted_total += accepted
                duplicates_total += duplicates
                batch = []
    if batch:
        accepted, duplicates = insert_events(batch)
        accepted_total += accepted
        duplicates_total += duplicates
    return accepted_total, duplicates_total


def _resolve_path(value: str | None, *, default: Path) -> Path:
    candidate = Path(value) if value else default
    if not candidate.is_absolute():
        cctv_candidate = settings.cctv_dir_path / candidate
        candidate = cctv_candidate if cctv_candidate.exists() else Path.cwd() / candidate
    resolved = candidate.resolve()
    workspace = Path.cwd().resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"Path must stay inside the project workspace: {resolved}") from exc
    if not resolved.exists():
        known = ", ".join(CAMERA_FILES.values())
        raise FileNotFoundError(f"Video path does not exist: {resolved}. Known camera files: {known}")
    return resolved


def _set_job(job_id: str, values: dict[str, Any]) -> None:
    with JOBS_LOCK:
        JOBS[job_id] = values


def _update_job(job_id: str, **values: Any) -> None:
    with JOBS_LOCK:
        job = JOBS[job_id]
        job.update(values)
        job["updated_at"] = _now()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
