# CHOICES

## 1. Detection Model Choice

Options considered were YOLOE-26, a custom trained YOLOv8 `best.pt`, RT-DETR, MediaPipe, and a VLM-only approach. The final submission uses the custom YOLOv8 model at `models/best.pt` because it is trained directly for the two business classes the challenge needs: `customer` and `staff`. This is stronger than generic person detection because staff exclusion no longer depends on a color heuristic after detection. RT-DETR may improve some crowded scenes, but it adds more complexity for a short challenge. MediaPipe is lightweight, but it is less suitable for full-body retail CCTV with occlusion. A VLM-only approach would be too slow and expensive for frame-by-frame processing.

The AI suggestion was to start with YOLOv8 or YOLOv11 and use ByteTrack or DeepSORT for tracking. I followed that direction once a trained `best.pt` was available. The pipeline defaults to ByteTrack through Ultralytics `model.track(...)`, while preserving a centroid fallback for environments where tracker dependencies are unavailable. ByteTrack should improve ID continuity through crowded billing, partial occlusion, and group entry, which are the scoring cases most likely to expose a centroid-only tracker.

The detector records `detector_model`, `detector_family`, `detector_classes`, `custom_class_id`, `custom_class_name`, and role metadata in every emitted event. Staff/customer identity is anonymous role classification through the detector class output. It does not identify faces or customer identity. A `staff` detection sets `is_staff=true`; a `customer` detection counts as a shopper.

The model is not the whole solution. Entry/exit, re-entry, zone dwell, queue abandonment, and conversion still require application logic. The current submission implements those with entry-line direction checks, POS-aware abandonment enrichment, polygon zone mapping, and cross-camera session stitching. The Re-ID layer is OSNet-ready: the current stitcher preserves camera-local IDs, pre-stitch IDs, route context, and `reid_method` metadata so an OSNet embedding matcher can replace or augment the baseline without changing the API event schema.

## 2. Event Schema Design Rationale

The challenge provided a required event shape, so the project keeps that schema directly rather than creating a private internal schema. The Pydantic model validates `event_id`, store, camera, visitor token, event type, timestamp, zone, dwell duration, staff flag, confidence, and metadata. The API accepts low-confidence events instead of suppressing them. This matters because the reviewers evaluate confidence calibration and because downstream metrics can decide how to treat uncertain detections.

The AI suggestion was to split raw detections, tracks, sessions, and business events into separate schemas. That is a good production design, but it is more than the acceptance gate needs. I chose one public event schema for ingest plus internal helper logic for metrics. The trade-off is that the event table stores metadata as JSON instead of fully normalized columns. This makes ingestion flexible and keeps schema changes small while still supporting required metrics like queue depth and session sequence.

The schema is idempotent by `event_id`, replayable through JSONL, and readable in follow-up discussion. It also supports the scoring edge cases: staff exclusion through `is_staff`, re-entry through `REENTRY` under the same `visitor_id`, group handling through one event per track, dwell through repeated 30-second `ZONE_DWELL`, and billing behavior through queue events and POS correlation.

The event metadata intentionally carries audit fields beyond the minimum schema: camera-local visitor ID, pre-stitch visitor ID, bounding box, center point, and stitching method. These make the Re-ID/session baseline easier to debug without changing the required public event fields.

## 3. API Architecture Choice

Options considered were FastAPI with SQLite, FastAPI with PostgreSQL, and Node.js with Express. FastAPI was chosen because the challenge FAQ says Python has the best scoring harness coverage, and Pydantic validation maps naturally to event ingestion. SQLite was chosen for the submitted baseline because it keeps `docker compose up` simple and deterministic. PostgreSQL is better for multi-store production traffic, but it introduces more moving parts for a take-home evaluation.

The AI recommendation was PostgreSQL plus Redis or Kafka for event streaming. I agree with that direction for 40 live stores, but I chose a smaller architecture for this first version. The code still separates ingestion, storage, analytics, and health modules, so scaling later is straightforward: replace SQLite with PostgreSQL, move replay/ingest to a queue, and materialize daily aggregates.

The API computes metrics from stored events rather than returning hardcoded outputs. This is important because the evaluation framework caps scores when outputs do not vary with input. The system also imports POS transactions and correlates them with billing-zone visitors in the five-minute pre-transaction window. Health and structured logs are first-class because the problem statement says `/health` is what an on-call engineer checks first.
