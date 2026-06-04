# DESIGN

## Architecture Overview

This project is built as a complete but pragmatic Store Intelligence system. The detection side processes CCTV footage and emits structured visitor events. The API side validates, stores, and computes business metrics from those events and the POS transaction file. The implementation favors a simple operational path because the evaluation framework gives reviewers only a few minutes to run the system, inspect events, and call endpoints.

The main runtime is a FastAPI service backed by SQLite. SQLite was chosen because the challenge FAQ explicitly allows it and because it makes `docker compose up` reliable without database migrations or a separate PostgreSQL container. The storage layer is still isolated in `app/storage.py`, so moving to PostgreSQL later would mainly require replacing SQL statements and connection handling rather than rewriting analytics logic.

The data flow is:

1. CCTV clips are processed by `pipeline.run_all` using the custom YOLOv8 `models/best.pt` staff/customer detector.
2. The detection pipeline emits JSONL events using the required schema.
3. `pipeline.live_replay` or the Docker `custom-yolo-live` service posts those events to `POST /events/ingest`.
4. The API validates each event with Pydantic, deduplicates by `event_id`, and stores accepted events.
5. Analytics modules compute metrics, funnel, heatmap, anomalies, and health directly from stored events and POS rows.

The web dashboard is served by the same FastAPI application at `/dashboard`. It is not a static mock: it polls `/stores/{id}/live`, lists mounted camera feeds, shows recent detection boxes from event metadata, and can submit an all-camera raw CCTV processing job through `POST /videos/process-all`. The job runner is intentionally in-process for this MVP so `docker compose up` starts a complete application without Redis, Celery, or another worker service. For a higher-throughput production deployment, the `app/video_jobs.py` interface can be moved behind a durable queue while keeping the public API unchanged.

## Detection Design

The detection pipeline supports a real custom YOLOv8 path and a sample path. The production demo default is `models/best.pt`, loaded through Ultralytics YOLO. The model has two classes, `customer` and `staff`, so staff exclusion is produced by the detector itself instead of a post-hoc clothing heuristic. Tracking defaults to ByteTrack through Ultralytics `model.track(...)`, with a centroid fallback only for dependency-light tests. The tracker assigns stable camera-local track IDs, maps each detection to zones, and uses zone transitions to emit `ZONE_ENTER`, `ZONE_EXIT`, and `ZONE_DWELL`.

After all cameras are processed, `pipeline/stitch_sessions.py` converts camera-local visitor IDs such as `VIS_CAM_3_00001` into anonymous store-level session IDs such as `VIS_70594640`. The stitcher uses camera route order, event time gaps, zone context, and track-fragment guards. It preserves the original local ID in event metadata as `pre_stitch_visitor_id` and `camera_visitor_id`, so the reviewer can audit how a session was assembled.

The detection layer now keeps evaluating the entry threshold after the first entry. That matters because a customer who exits and crosses inbound again should produce `REENTRY` under the same visitor token instead of a second unrelated `ENTRY`. Billing abandonment is added as a separate enrichment pass in `pipeline/enrich_events.py`: if a non-staff visitor leaves billing and no POS transaction appears within the configured five-minute window, the pipeline emits `BILLING_QUEUE_ABANDON`. This keeps the detector focused on visual behavior and keeps POS correlation explicit and testable.

Zone mapping is rule based. The config file defines camera IDs, normalized polygons, and an entry threshold line. A detected person's bottom-center point is mapped into a polygon. This makes the approach auditable and easy to tune for the provided store layout. It also avoids depending on a VLM for every frame, which would be slower, costly, and harder to reproduce during evaluation.

Staff/customer identity is anonymous role classification, not face identity. The custom detector emits `customer` or `staff` boxes directly; the pipeline stores that as `is_staff`, `metadata.person_role`, `metadata.custom_class_name`, and `metadata.role_source=custom_yolov8_class`. The stitcher uses majority staff evidence rather than allowing one weak staff event to mark an entire session. The OSNet Re-ID upgrade point is the cross-camera stitching layer: an embedding matcher can replace the current route/time/zone baseline while preserving the public event schema.

## API Design

The ingest endpoint accepts a JSON array or an object containing an `events` array. It validates every event independently and returns accepted, duplicate, and rejected counts. Duplicate event IDs are ignored rather than inserted again, making replay safe. Validation errors are returned as structured partial-success responses instead of crashing the batch.

The metrics endpoint uses the latest ingested event day as the replay business day. This keeps old challenge clips useful even when reviewed on a later date. If events are current, that window is naturally today. Staff events are excluded from all customer metrics.

POS correlation follows the problem statement: a visitor in the billing zone during the five minutes before a POS timestamp counts as converted. Since POS data has no customer ID, the system correlates by store and time window. This is intentionally session-level, not transaction-line-level. The POS importer groups CSV rows by invoice number to avoid counting multiple SKUs in the same receipt as multiple purchases.

## Failure Handling and Observability

Every request is logged as structured JSON with `trace_id`, `store_id`, endpoint, latency, event count, and status code. Database errors are converted to HTTP 503 responses with a structured body. `/health` reports database status, last event timestamp by store, and `STALE_FEED` warnings when the feed is older than the configured threshold.

## AI-Assisted Decisions

AI helped shape three decisions. First, I used it to compare a heavy production stack against a lightweight challenge stack. The suggestion was PostgreSQL plus a worker queue. I overrode that for the first submission because the evaluation gate values clean startup, and SQLite is accepted by the FAQ. The code keeps a storage boundary so PostgreSQL remains a later upgrade.

Second, AI suggested using a VLM for zone classification. I rejected that for the main loop because it would be expensive and hard to reproduce. I chose normalized polygons from `store_layout.json`, which are transparent and fast. A VLM can still be useful offline to validate zone labels or staff uniform patterns.

Third, AI suggested dropping low-confidence detections to improve apparent accuracy. I kept low-confidence events with their confidence values because the problem statement explicitly rewards confidence calibration. Silent suppression would make hidden scoring and debugging worse.
