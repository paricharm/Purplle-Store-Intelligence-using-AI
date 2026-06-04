from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def live_replay(
    path: Path,
    api_url: str,
    batch_size: int,
    speed: float,
    max_sleep: float,
    fresh_run: bool,
) -> None:
    events = _load_events(path)
    if fresh_run:
        run_id = uuid.uuid4().hex[:6]
        events = [_freshen_event(event, run_id) for event in events]

    last_ts: datetime | None = None
    batch: list[dict[str, Any]] = []
    accepted_total = 0
    duplicate_total = 0

    for index, event in enumerate(events, start=1):
        current_ts = parse_ts(event["timestamp"])
        if last_ts is not None:
            delay = max(0.0, (current_ts - last_ts).total_seconds() / max(speed, 0.001))
            time.sleep(min(delay, max_sleep))
        last_ts = current_ts

        batch.append(event)
        if len(batch) >= batch_size:
            result = _post(batch, api_url)
            accepted_total += int(result.get("accepted", 0))
            duplicate_total += int(result.get("duplicates", 0))
            _print_progress(index, len(events), event, result, accepted_total, duplicate_total)
            batch = []

    if batch:
        result = _post(batch, api_url)
        accepted_total += int(result.get("accepted", 0))
        duplicate_total += int(result.get("duplicates", 0))
        _print_progress(len(events), len(events), batch[-1], result, accepted_total, duplicate_total)

    print(
        {
            "status": "complete",
            "events_seen": len(events),
            "accepted_total": accepted_total,
            "duplicate_total": duplicate_total,
            "api_url": api_url,
        }
    )


def _load_events(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        events = [json.loads(line) for line in handle if line.strip()]
    return sorted(events, key=lambda event: event["timestamp"])


def _freshen_event(event: dict[str, Any], run_id: str) -> dict[str, Any]:
    metadata = dict(event.get("metadata") or {})
    metadata["live_replay_run_id"] = run_id
    metadata["original_event_id"] = event["event_id"]
    metadata["original_visitor_id"] = event["visitor_id"]
    return {
        **event,
        "event_id": str(uuid.uuid4()),
        "visitor_id": f"{event['visitor_id']}_{run_id}",
        "metadata": metadata,
    }


def _post(batch: list[dict[str, Any]], api_url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/events/ingest",
        data=json.dumps(batch).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"API ingest failed: HTTP {exc.code} {body}") from exc


def _print_progress(
    index: int,
    total: int,
    event: dict[str, Any],
    result: dict[str, Any],
    accepted_total: int,
    duplicate_total: int,
) -> None:
    print(
        {
            "progress": f"{index}/{total}",
            "event_type": event["event_type"],
            "visitor_id": event["visitor_id"],
            "timestamp": event["timestamp"],
            "batch_result": result,
            "accepted_total": accepted_total,
            "duplicate_total": duplicate_total,
        },
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Replay pipeline events through the API in simulated real time."
    )
    parser.add_argument("--events", type=Path, default=Path("generated_events.jsonl"))
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument(
        "--speed",
        type=float,
        default=12.0,
        help="Replay speed multiplier. 12 means twelve seconds of clip time per real second.",
    )
    parser.add_argument("--max-sleep", type=float, default=1.5)
    parser.add_argument(
        "--fresh-run",
        action="store_true",
        help="Generate new event IDs and visitor suffixes so repeated demos still update metrics.",
    )
    args = parser.parse_args()
    live_replay(
        path=args.events,
        api_url=args.api_url,
        batch_size=args.batch_size,
        speed=args.speed,
        max_sleep=args.max_sleep,
        fresh_run=args.fresh_run,
    )
