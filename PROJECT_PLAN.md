# Store Intelligence Challenge - Production Project Plan

## 1. Problem Review

The challenge asks for an end-to-end retail analytics system that starts from raw anonymised CCTV footage and ends with a working, containerised Store Intelligence API. The expected output is not only code, but a complete production-aware submission with documented design decisions, test evidence, AI usage notes, and a runnable deployment.

The north star metric is offline store conversion rate:

```text
conversion_rate = visitors_who_completed_purchase / total_unique_visitors
```

Every technical decision should improve either the accuracy of this metric or the operational usefulness of the API.

## 2. Required Deliverables

The final repository must include:

- Detection pipeline that processes CCTV clips and emits structured events.
- REST API that ingests events and exposes metrics, funnel, heatmap, anomalies, and health endpoints.
- Storage layer for events, sessions, POS transactions, metrics, and anomaly state.
- Docker Compose setup where `docker compose up` starts the system.
- Tests with more than 70% statement coverage and required edge case coverage.
- README with setup in 5 commands and pipeline execution instructions.
- `DESIGN.md` with architecture overview and an `AI-Assisted Decisions` section.
- `CHOICES.md` with model choice, event schema rationale, and one API architecture decision.
- Prompt block comments at the top of every test file.
- Optional but recommended live dashboard for bonus points.

## 3. Recommended Architecture

Use a Python-first stack because the challenge scoring harness has best coverage for FastAPI.

```text
CCTV clips + store_layout.json + POS CSV
        |
        v
Detection Pipeline
YOLOv8 / YOLOv11 person detection + ByteTrack tracking + rule-based zone mapping
        |
        v
Event Emitter
JSONL events matching challenge schema
        |
        v
FastAPI Ingest API
validation, deduplication, persistence
        |
        v
PostgreSQL or SQLite
events, sessions, transactions, aggregate views
        |
        v
Metrics / Funnel / Heatmap / Anomaly Services
        |
        v
REST API + optional live dashboard
```

Recommended storage choice:

- Use PostgreSQL for the production-ready version.
- Use SQLite only if time is very tight.
- Keep repository code database-agnostic through SQLAlchemy so local tests can run quickly.

Recommended services:

- `api`: FastAPI application.
- `db`: PostgreSQL.
- `pipeline`: optional one-shot or profile-based service for processing clips.
- `dashboard`: optional Streamlit, React, or terminal dashboard.

## 4. Repository Structure

```text
store-intelligence/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── ingestion.py
│   ├── metrics.py
│   ├── funnel.py
│   ├── heatmap.py
│   ├── anomalies.py
│   ├── health.py
│   └── logging.py
├── pipeline/
│   ├── detect.py
│   ├── tracker.py
│   ├── zones.py
│   ├── sessions.py
│   ├── staff.py
│   ├── emit.py
│   └── run.py
├── dashboard/
│   └── app.py
├── tests/
│   ├── test_ingestion.py
│   ├── test_metrics.py
│   ├── test_funnel.py
│   ├── test_heatmap.py
│   ├── test_anomalies.py
│   ├── test_health.py
│   └── test_pipeline_events.py
├── docs/
│   ├── DESIGN.md
│   └── CHOICES.md
├── sample_data/
│   ├── sample_events.jsonl
│   └── sample_pos_transactions.csv
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── README.md
└── PROJECT_PLAN.md
```

## 5. Event Schema Plan

The pipeline must emit events with this shape:

- `event_id`: UUID v4, globally unique.
- `store_id`: store identifier from `store_layout.json`.
- `camera_id`: source camera.
- `visitor_id`: per visit-session token.
- `event_type`: one of `ENTRY`, `EXIT`, `ZONE_ENTER`, `ZONE_EXIT`, `ZONE_DWELL`, `BILLING_QUEUE_JOIN`, `BILLING_QUEUE_ABANDON`, `REENTRY`.
- `timestamp`: ISO-8601 UTC from clip start time plus frame offset.
- `zone_id`: zone name or null for entry/exit.
- `dwell_ms`: duration, zero for instant events.
- `is_staff`: staff flag.
- `confidence`: model confidence, including low confidence events.
- `metadata`: queue depth, SKU zone, session sequence, and useful pipeline diagnostics.

Implementation rules:

- Validate all events with Pydantic.
- Store malformed events separately or return them in partial-success errors.
- Never silently drop low-confidence events.
- Deduplicate ingest by `event_id`.
- Exclude `is_staff=true` from customer-facing metrics.

## 6. Detection Pipeline Plan

### Step 1: Data Ingestion

- Read `store_layout.json`.
- Discover clips by store and camera angle.
- Load POS transactions.
- Define clip start timestamps from dataset metadata or a config file if not embedded.

### Step 2: Person Detection

- Start with YOLO person detection.
- Use a lightweight model first for speed, then evaluate a larger model if accuracy is poor.
- Record detection confidence per frame.
- Keep low-confidence detections with confidence values instead of suppressing them too aggressively.

### Step 3: Tracking

- Use ByteTrack as the baseline tracker.
- Track per-camera identities.
- Maintain track state: bounding box, timestamps, zone, direction, confidence history.

### Step 4: Direction and Entry/Exit

- Define entry threshold lines from `store_layout.json`.
- Determine movement direction by comparing track positions across frames.
- Emit one `ENTRY` or `EXIT` when a track crosses the threshold.
- Handle groups by emitting one event per tracked person.

### Step 5: Zone Mapping

- Represent each zone as polygon coordinates.
- Map each person using the bottom-center point of the bounding box.
- Emit `ZONE_ENTER` and `ZONE_EXIT`.
- Emit `ZONE_DWELL` every 30 seconds of continuous dwell.

### Step 6: Staff Classification

- Baseline: classify staff using uniform color/appearance rules if visible in the footage.
- Fallback: mark uncertain staff classifications with lower confidence.
- Document limitations clearly in `CHOICES.md`.
- Optional enhancement: sample frames and use a VLM to validate staff/uniform heuristics.

### Step 7: Re-entry and Cross-camera Deduplication

- Maintain session state by store.
- A visitor who exits and reappears within a configurable re-entry window should receive a `REENTRY` event instead of being counted as a fresh visitor.
- Use trajectory, time gap, appearance embedding, and camera overlap rules.
- Keep the implementation explainable because follow-up questions will probe this area.

### Step 8: Billing Queue and POS Correlation

- Detect billing zone occupancy from zone mapping.
- If a visitor enters billing while queue depth is greater than zero, emit `BILLING_QUEUE_JOIN`.
- For each POS transaction, mark visitors in the billing zone within the previous 5 minutes as converted.
- If a visitor leaves billing and no matching POS transaction follows, emit `BILLING_QUEUE_ABANDON`.

### Step 9: Event Output

- Write `events.jsonl`.
- Optionally stream events directly to `POST /events/ingest`.
- Provide a replay mode that simulates real-time event flow for the dashboard.

## 7. API Plan

### Endpoint: `POST /events/ingest`

Requirements:

- Accept batches up to 500 events.
- Validate each event independently.
- Deduplicate by `event_id`.
- Return partial success for malformed events.
- Never return 5xx for normal validation problems.

Response shape:

```json
{
  "accepted": 498,
  "duplicates": 1,
  "rejected": 1,
  "errors": [
    {
      "index": 12,
      "event_id": "bad-event",
      "code": "INVALID_EVENT_TYPE",
      "message": "event_type must be one of the supported values"
    }
  ]
}
```

### Endpoint: `GET /stores/{id}/metrics`

Return:

- Unique visitors today.
- Conversion rate.
- Average dwell per zone.
- Current queue depth.
- Abandonment rate.

Rules:

- Exclude staff.
- Handle zero purchases with conversion rate `0`, not null.
- Handle zero traffic with empty arrays and zero values.

### Endpoint: `GET /stores/{id}/funnel`

Funnel stages:

- Entry.
- Zone Visit.
- Billing Queue.
- Purchase.

Rules:

- Session is the unit.
- Re-entry must not double-count a visitor.
- Return counts and drop-off percentages.

### Endpoint: `GET /stores/{id}/heatmap`

Return:

- Zone visit frequency.
- Average dwell.
- Normalized score from 0 to 100.
- `data_confidence` flag if fewer than 20 sessions are in the selected window.

### Endpoint: `GET /stores/{id}/anomalies`

Detect:

- Queue spike.
- Conversion drop compared with 7-day average.
- Dead zone with no visits in 30 minutes.

Each anomaly must include:

- Type.
- Severity: `INFO`, `WARN`, or `CRITICAL`.
- Evidence values.
- Suggested action.

### Endpoint: `GET /health`

Return:

- Service status.
- Database status.
- Last event timestamp per store.
- `STALE_FEED` warning if any store has more than 10 minutes lag.

## 8. Data Model Plan

Core tables:

- `events`: raw validated events.
- `sessions`: one row per visitor session.
- `session_zone_visits`: zone enter/exit/dwell summary.
- `pos_transactions`: imported POS records.
- `conversions`: session to POS correlation results.
- `anomalies`: active and historical anomaly records.

Important indexes:

- `events(event_id)` unique.
- `events(store_id, timestamp)`.
- `events(store_id, visitor_id, timestamp)`.
- `events(store_id, event_type, timestamp)`.
- `sessions(store_id, visitor_id)`.
- `pos_transactions(store_id, timestamp)`.

## 9. Production Readiness Plan

### Containerisation

- `docker compose up` starts API and database.
- Add health checks for API and database.
- Seed sample events/POS data through a documented command.

### Configuration

- Use environment variables for database URL, log level, ingest batch limit, stale feed threshold, and re-entry window.
- Provide `.env.example`.

### Structured Logging

Log every request with:

- `trace_id`
- `store_id`
- `endpoint`
- `latency_ms`
- `event_count` for ingest
- `status_code`

### Error Handling

- Return structured validation errors.
- Return HTTP 503 if the database is unavailable.
- Do not expose raw stack traces.
- Attach `trace_id` to error responses.

### Observability

- Add `/health`.
- Add basic request timing middleware.
- Add database connectivity check.
- Log ingest counts and duplicate counts.

## 10. Testing Plan

Minimum required test areas:

- Ingest accepts valid events.
- Ingest rejects malformed events with partial success.
- Ingest is idempotent by `event_id`.
- Metrics exclude staff.
- Empty store returns zeros and empty structures.
- All-staff data returns zero customer visitors.
- Zero purchases returns conversion rate `0`.
- Re-entry does not double-count funnel visitors.
- Heatmap marks low confidence when sessions are fewer than 20.
- Anomaly detection catches queue spike, conversion drop, and dead zone.
- Health reports stale feed when last event is older than 10 minutes.

Each test file should begin with:

```python
# PROMPT:
# <Prompt used to generate or improve this test file>
#
# CHANGES MADE:
# <Human changes, corrections, and edge cases added after AI generation>
```

Coverage target:

- Required: more than 70%.
- Aim: 80% or more for API modules.

## 11. Documentation Plan

### README.md

Must include:

- Project overview.
- Five-command setup.
- How to run `docker compose up`.
- How to run tests.
- How to run detection on clips.
- How to ingest generated events.
- Example API requests.
- Dashboard URL if implemented.

### DESIGN.md

Must include:

- Architecture overview.
- Data flow from frame to API response.
- Event lifecycle.
- Sessionization approach.
- POS correlation logic.
- Failure modes.
- `AI-Assisted Decisions` section with 2-3 concrete examples.

### CHOICES.md

Must include three decisions:

- Detection model choice.
- Event schema design rationale.
- API architecture or storage decision.

For each decision:

- Options considered.
- What AI suggested.
- What was chosen.
- Why the choice was made.
- Known trade-offs.

## 12. Live Dashboard Plan

Recommended bonus implementation:

- Build a small web dashboard with Streamlit or a simple React page.
- Show live updates for unique visitors, conversion rate, queue depth, and anomalies.
- Add a pipeline replay command that posts events into the API at simulated real-time speed.

Minimum acceptable dashboard:

- Terminal dashboard using Rich.
- Refresh every 1-5 seconds.
- Show at least one live metric changing as events are ingested.

## 13. Step-by-Step Execution Timeline

### Phase 1: Foundation

1. Create repository structure.
2. Set up FastAPI, SQLAlchemy, Alembic, pytest, Ruff, and Docker Compose.
3. Define Pydantic event schema.
4. Build `POST /events/ingest`.
5. Add database tables and idempotency by `event_id`.
6. Add baseline tests for ingest and schema validation.

Exit criteria:

- `docker compose up` starts API and database.
- Ingest accepts sample events.
- Duplicate ingest is safe.

### Phase 2: Metrics API

1. Import POS transactions.
2. Build session reconstruction from events.
3. Implement conversion correlation using the 5-minute billing window.
4. Implement `/stores/{id}/metrics`.
5. Implement `/stores/{id}/funnel`.
6. Add edge case tests for empty store, staff-only data, zero purchases, and re-entry.

Exit criteria:

- `/metrics` and `/funnel` pass sample assertions.
- Staff and re-entry logic are tested.

### Phase 3: Heatmap, Anomalies, Health

1. Implement `/stores/{id}/heatmap`.
2. Implement queue spike detection.
3. Implement conversion drop versus 7-day average.
4. Implement dead zone detection.
5. Implement `/health` with stale feed warning.
6. Add structured request logging and error handling.

Exit criteria:

- All required API endpoints work.
- Health endpoint is accurate.
- Structured logs contain required fields.

### Phase 4: Detection Pipeline

1. Parse `store_layout.json`.
2. Load clips and sample frames.
3. Implement person detection.
4. Implement tracking and visitor token assignment.
5. Implement threshold crossing for entry and exit.
6. Implement zone enter, zone exit, and dwell.
7. Implement staff flagging.
8. Implement billing queue and POS correlation events.
9. Emit JSONL events.
10. Add replay-to-API command.

Exit criteria:

- Pipeline produces schema-valid JSONL.
- Events can be ingested without 5xx responses.
- Group entry, re-entry, staff, and empty-period behavior is documented.

### Phase 5: Dashboard and Replay

1. Add simulated real-time replay from JSONL.
2. Build terminal or web dashboard.
3. Show live metric updates while replay runs.
4. Document dashboard command in README.

Exit criteria:

- Reviewer can see a metric update live.
- Dashboard connects to real API endpoints.

### Phase 6: Hardening and Submission

1. Run full test suite with coverage.
2. Run clean `docker compose up` from scratch.
3. Validate README commands.
4. Complete `DESIGN.md`.
5. Complete `CHOICES.md`.
6. Add prompt blocks to every test file.
7. Check acceptance gate manually.
8. Prepare follow-up question notes.

Exit criteria:

- All acceptance gate items pass.
- `DESIGN.md` and `CHOICES.md` are each more than 250 words.
- Submission repository is clean and reproducible.

## 14. Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Detection accuracy is weak on occlusion/group entry | Bad entry and funnel counts | Tune confidence thresholds, use ByteTrack, document uncertainty, manually inspect sample frames |
| Staff classification is unreliable | Customer metrics inflated | Use conservative staff rules and mark low confidence; exclude only confident staff |
| Re-entry logic double-counts visitors | Conversion rate denominator inflated | Define explicit re-entry window and test it |
| POS correlation over-assigns purchases | Conversion rate inflated | Correlate only billing-zone sessions in 5-minute pre-transaction window |
| Docker setup fails on reviewer machine | Submission may fail acceptance gate | Test clean clone flow before submission |
| API passes happy path but fails hidden edge cases | Low API score | Build tests around empty store, zero purchases, staff-only, malformed events, duplicates |

## 15. Final Acceptance Checklist

- [ ] `docker compose up` starts everything from a clean clone.
- [ ] `POST /events/ingest` accepts valid event batches up to 500.
- [ ] Ingest is idempotent by `event_id`.
- [ ] Malformed event batches return partial success.
- [ ] `GET /stores/STORE_BLR_002/metrics` returns valid JSON.
- [ ] `/funnel`, `/heatmap`, `/anomalies`, and `/health` are implemented.
- [ ] Staff events are excluded from customer metrics.
- [ ] Re-entry does not double-count sessions.
- [ ] Zero-traffic and zero-purchase cases return valid zero values.
- [ ] Structured logs include all required fields.
- [ ] Test coverage is above 70%.
- [ ] README setup works in 5 commands.
- [ ] `DESIGN.md` includes `AI-Assisted Decisions`.
- [ ] `CHOICES.md` explains the three required decisions.
- [ ] Every test file has `PROMPT` and `CHANGES MADE` blocks.
- [ ] Optional dashboard is documented and works.
