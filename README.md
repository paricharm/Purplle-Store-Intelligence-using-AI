# Purplle-Store-Intelligence-using-AI
# Store Intelligence API

End-to-end implementation for the Store Intelligence challenge: raw CCTV footage becomes structured visitor events, events are ingested into an API, and the API returns live store metrics such as visitors, conversion rate, dwell, funnel, heatmap, anomalies, and health.

The implementation is intentionally production-aware but practical for the challenge window. The API uses FastAPI with SQLite so `docker compose up` is enough to start the API, dashboard, and a default live event replay into `POST /events/ingest`. The detection pipeline can run in two modes:

- `sample`: generates schema-valid events that exercise staff, re-entry, queue, dwell, and abandonment behavior.
- `detect`: uses your custom Ultralytics YOLOv8 weights at `models/best.pt` with two classes: `customer` and `staff`.

## Acceptance-Gate Quick Start

No manual setup is required beyond cloning the repo and running Docker Compose.

```bash
git clone <your-repo-url>
cd store-intelligence
docker compose up --build
```

Then verify the required scoring endpoints:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/stores/STORE_BLR_002/metrics
```

On Windows PowerShell, replace `curl` with `Invoke-RestMethod` if needed.

Open the production dashboard:

```text
http://127.0.0.1:8000/dashboard
```

The default Compose stack starts:

- `api`: FastAPI service, dashboard, health endpoint, and SQLite-backed intelligence API.
- `event-replay`: simulated-real-time replay of bundled schema-valid pipeline events into the API.

The dashboard polls live metrics, recent events, anomalies, funnel, heatmap, and job
status. The default Docker API image stays fast to build and uses the bundled
`event-replay` service for a connected live demo. Raw custom YOLOv8 CCTV processing runs
through the `live` or `generate` profile, which builds the dedicated pipeline image with
Ultralytics and OpenCV.

## Running the API Locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Install `requirements-pipeline.txt` as well only when you want to run raw CCTV detection
from local Python instead of Docker's pipeline profile.

The API stores data in `data/store_intelligence.db` by default. The bundled POS CSV is imported during startup when `POS_CSV_PATH` points to it.

## Running the Detection Pipeline

Generate sample events:

```bash
python -m pipeline.run --mode sample --output sample_data/sample_events.jsonl
```

Run custom YOLOv8 staff/customer detection against one raw CCTV clip:

```bash
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-pipeline.txt
python -m pipeline.run --mode detect --video "sample_data/store-intelligence-videos/CAM 1.mp4" --camera-id CAM_1 --store-id STORE_BLR_002 --model models/best.pt --tracker bytetrack --pos-csv "POS - sample transactionsb1e826f.csv" --output data/generated_events_custom_yolov8.jsonl
```

Process all CCTV clips into one combined event stream:

```bash
python -m pipeline.run_all --video-dir "sample_data/store-intelligence-videos" --store-id STORE_BLR_002 --model models/best.pt --tracker bytetrack --pos-csv "POS - sample transactionsb1e826f.csv" --clip-start 2026-04-10T11:20:00Z --frame-stride 10 --conf 0.05 --output data/generated_events_custom_yolov8.jsonl
```

`run_all` stitches camera-local track IDs into store-level anonymous visitor sessions by default. Use `--no-stitch` only when debugging raw per-camera output.

The output JSONL goes to:

```text
data/generated_events_custom_yolov8.jsonl
```

Ingest the generated events into the running API:

```bash
python scripts/ingest_jsonl.py data/generated_events_custom_yolov8.jsonl --api-url http://127.0.0.1:8000
```

The default model is `models/best.pt`. It is your custom trained YOLOv8 detector with `customer` and `staff` classes. ByteTrack is the default tracker:

```bash
python -m pipeline.run_all --video-dir "CCTV Footage" --model models/best.pt --tracker bytetrack --clip-start 2026-04-10T11:20:00Z --frame-stride 10 --output generated_events_custom_yolov8.jsonl
```

Compare outputs:

```bash
python scripts/compare_event_files.py generated_events.jsonl generated_events_custom_yolov8.jsonl
```

The detector adds audit metadata per event: `detector_model`, `detector_family`, `detector_classes`, `custom_class_id`, `custom_class_name`, `bbox_xyxy`, `center_norm`, `person_role`, `role_confidence`, `role_source`, and `role_signals`. Staff/customer comes directly from the custom model class output.

Replay events into the API as a live stream:

```bash
python -m pipeline.live_replay --events data/generated_events_custom_yolov8.jsonl --api-url http://127.0.0.1:8000 --speed 12 --batch-size 1 --fresh-run
```

The Re-ID/session baseline also preserves `camera_visitor_id`, `pre_stitch_visitor_id`, `session_seq`, and `stitching_method` so reviewer questions can be answered from the event stream.

## Model Workflow

The submitted detection workflow is:

```text
Custom YOLOv8 best.pt
classes: customer, staff
  -> ByteTrack
  -> OSNet-ready cross-camera Re-ID/session stitching
  -> Polygon zone detection using config/store_layout.json
  -> Event generator
  -> FastAPI analytics
```

`models/best.pt` is the only production detector used by the raw CCTV pipeline. The model class name drives `is_staff`: detections labeled `staff` are excluded from customer metrics, while detections labeled `customer` count as shoppers. Cross-camera Re-ID is handled by the session stitching layer and records `reid_method` / `stitching_method` metadata so the reviewer can trace how camera-local tracks became store-level sessions.

## API Endpoints

### `POST /events/ingest`

Accepts a JSON array or `{ "events": [...] }` batch of up to 500 events. It validates every event independently, deduplicates by `event_id`, and returns partial success.

### `GET /stores/{id}/metrics`

Returns unique visitors, conversion rate, average dwell per zone, queue depth, and abandonment rate. Staff events are excluded.

### `GET /stores/{id}/funnel`

Returns session-based funnel stages: Entry, Zone Visit, Billing Queue, Purchase. Re-entry events do not double count the same `visitor_id`.

### `GET /stores/{id}/heatmap`

Returns zone visit frequency, average dwell, normalized 0-100 score, and a `data_confidence` flag.

### `GET /stores/{id}/anomalies`

Returns active queue spike, conversion drop, and dead zone anomalies with severity and suggested action.

### `GET /health`

Returns service status, database status, last event timestamp by store, and stale feed warnings.

## Implementation Checklist Mapping

The repository now exposes the suggested challenge skeleton directly, while keeping the
production logic in the existing shared modules:

| Phase | Files | What they do |
| --- | --- | --- |
| Part A detection | `pipeline/detect.py`, `pipeline/tracker.py`, `pipeline/emit.py`, `pipeline/pos_correlator.py`, `pipeline/run.sh` | Custom YOLOv8 staff/customer detection, ByteTrack tracking, Re-ID/session stitching, event schema emission, POS correlation, and one-command pipeline execution. |
| Part B API | `app/main.py`, `app/models.py`, `app/db.py`, `app/ingestion.py`, `app/metrics.py`, `app/funnel.py`, `app/anomalies.py`, `app/health.py` | FastAPI service, Pydantic event models, SQLite access, ingest/idempotency, metrics, funnel, anomaly, and health entrypoints. |
| Part C production | `Dockerfile`, `docker-compose.yml`, `tests/` | Container startup, default live replay, healthcheck, structured logging coverage, and edge-case tests. |
| Part D AI docs | `DESIGN.md`, `CHOICES.md`, `docs/DESIGN.md`, `docs/CHOICES.md` | Architecture, AI-assisted decisions, trade-offs, and model/API choices. |
| Part E dashboard | `app/dashboard_html.py`, `dashboard/tui.py`, `dashboard/app.py` | Web dashboard and terminal dashboard backed by API metrics. |

## Tests

```bash
pip install -r requirements.txt
pytest
coverage run --branch --source=app,pipeline -m pytest -p no:cacheprovider -o addopts='' tests
coverage report
```

The current suite has 29 passing tests and reports 72% statement coverage with the command above. Each test file includes the required `PROMPT` and `CHANGES MADE` block. The tests cover ingest idempotency, schema validation, custom YOLOv8 staff/customer metadata, staff exclusion, zero traffic, zero purchases, re-entry funnel behavior, heatmap confidence, anomaly detection, health data, live replay, Docker helper behavior, skeleton file entrypoints, POS correlation, and sample pipeline event validity.

## Live Dashboard

Docker demo instructions are also available in [DOCKER_LIVE_DEMO.md](DOCKER_LIVE_DEMO.md).

Production-style Docker path:

```powershell
docker compose down
Remove-Item data\store_intelligence.db -Force -ErrorAction SilentlyContinue
docker compose --profile live up --build
```

The plain `docker compose up --build` command starts the API/dashboard plus bundled event replay. The `--profile live` command starts the API/dashboard and a custom YOLOv8 live service that processes the mounted CCTV clips, writes `/data/generated_events_custom_yolov8.jsonl`, and streams those events into `POST /events/ingest`.

Open the web dashboard:

```text
http://127.0.0.1:8000/dashboard
```

The dashboard shows a CCTV video feed, recent detection boxes from event metadata, live KPIs, funnel, anomalies, heatmap, and latest events.

Run simulated-real-time replay from pipeline-generated events:

```bash
python -m pipeline.live_replay --events generated_events_custom_yolov8.jsonl --api-url http://127.0.0.1:8000 --speed 12 --batch-size 1
```

The dashboard polls `/stores/ST1008/live` every 1.5 seconds. The replay script posts events through `POST /events/ingest`, so the dashboard changes only when the API stores new events.

For a clean demo, start with a fresh database. With local Uvicorn:

```powershell
Remove-Item data\live_demo.db -Force -ErrorAction SilentlyContinue
$env:APP_DB_PATH="data/live_demo.db"
uvicorn app.main:app --reload
```

If you do not reset the DB, add `--fresh-run` so repeated demos still visibly update metrics:

```bash
python -m pipeline.live_replay --events generated_events_custom_yolov8.jsonl --api-url http://127.0.0.1:8000 --speed 12 --fresh-run
```

The older terminal dashboard is still available:

```bash
python dashboard/app.py --api-url http://127.0.0.1:8000 --store-id ST1008
```

## Important Files

- `DESIGN.md`: architecture and AI-assisted design notes.
- `CHOICES.md`: required trade-off writeup.
- `PROJECT_PLAN.md`: detailed execution plan.
- `config/store_layout.json`: zone and camera configuration.
- `notebooks/train_yolo_colab.ipynb`: optional Colab notebook for later custom training.
- `models/best.pt`: custom YOLOv8 staff/customer detector used by the raw CCTV pipeline.
