# Docker Live Dashboard Demo

This demo proves the pipeline and API are genuinely connected:

1. Docker runs the FastAPI service and web dashboard.
2. Docker runs YOLOE-26 on the mounted CCTV clips and writes detection events.
3. The dashboard polls the API and updates only after the API stores events.

## 1. Start Docker Desktop

Open Docker Desktop and wait until it shows Docker is running.

Verify:

```powershell
docker info
docker compose version
```

## 2. Start API + Dashboard + YOLOE Live Pipeline In Docker

From the project root:

```powershell
cd E:\track\customer_track
docker compose down
Remove-Item data\store_intelligence.db -Force -ErrorAction SilentlyContinue
docker compose --profile live up --build
```

Keep this terminal open. Docker starts the API and then a `yoloe-live` service that runs:

```text
CCTV clips -> YOLOE-26 person detector -> tracker/stitcher/staff-role classifier
          -> /data/generated_events_yoloe26.jsonl -> POST /events/ingest
```

The API is available at:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/dashboard
http://127.0.0.1:8000/docs
```

## 3. Open The Dashboard

Open:

```text
http://127.0.0.1:8000/dashboard
```

At first, event count and metrics should be zero or low. The dashboard includes:

- CCTV video feed from the mounted `sample_data/store-intelligence-videos` folder.
- Camera selector for `CAM_1` through `CAM_5`.
- YOLOE-26 detection overlay boxes from API event metadata.
- Staff/customer role labels. Green means customer, amber means staff.
- Live metrics, funnel, anomalies, heatmap, and latest event table.

## 4. Optional: Replay Existing YOLOE Events Into Docker API

The `--profile live` command already generates and replays events. If you only want to replay an existing file in a second PowerShell terminal:

```powershell
cd E:\track\customer_track
.\.venv\Scripts\Activate.ps1
python -m pipeline.live_replay --events data/generated_events_yoloe26.jsonl --api-url http://127.0.0.1:8000 --speed 12 --batch-size 1
```

The dashboard should update while this command runs.

This is the proof path:

```text
yoloe-live Docker service
  -> YOLOE-26 + tracker + role classifier
  -> /data/generated_events_yoloe26.jsonl
  -> POST /events/ingest inside Docker API
  -> SQLite /data/store_intelligence.db
  -> GET /stores/STORE_BLR_002/live
  -> /dashboard updates metrics and detection overlays on screen
```

## 5. Repeat The Demo Without Resetting DB

If you run the demo again without deleting the database, use:

```powershell
python -m pipeline.live_replay --events data/generated_events_yoloe26.jsonl --api-url http://127.0.0.1:8000 --speed 12 --batch-size 1 --fresh-run
```

`--fresh-run` generates new event IDs and visitor suffixes so the API accepts the replay as a new live run.

## 6. Optional: Ingest All Events Immediately

For a fast non-live API check:

```powershell
python scripts/ingest_jsonl.py data/generated_events_yoloe26.jsonl --api-url http://127.0.0.1:8000
Invoke-RestMethod http://127.0.0.1:8000/stores/STORE_BLR_002/metrics
```

## 7. Stop Docker

```powershell
docker compose down
```
