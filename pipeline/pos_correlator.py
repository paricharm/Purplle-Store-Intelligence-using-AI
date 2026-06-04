from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.pos_import import load_pos_csv
from app.time_utils import parse_timestamp
from pipeline.enrich_events import add_billing_abandonment_events


def converted_visitor_ids(
    events: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    window_minutes: int = 5,
) -> set[str]:
    """Return visitor IDs seen at billing shortly before a POS transaction."""

    billing_events = [
        event
        for event in events
        if not event.get("is_staff", False)
        and (
            event.get("event_type") == "BILLING_QUEUE_JOIN"
            or "BILL" in str(event.get("zone_id") or "").upper()
        )
    ]
    converted: set[str] = set()
    for txn in transactions:
        txn_ts = parse_timestamp(str(txn["timestamp"]))
        window_start = txn_ts - timedelta(minutes=window_minutes)
        store_id = str(txn["store_id"])
        for event in billing_events:
            if event.get("store_id") != store_id:
                continue
            event_ts = parse_timestamp(str(event["timestamp"]))
            if window_start <= event_ts <= txn_ts:
                converted.add(str(event["visitor_id"]))
    return converted


def correlate_file(events_path: Path, pos_csv_path: Path, output_path: Path) -> dict[str, Any]:
    events = _load_events(events_path)
    transactions = load_pos_csv(pos_csv_path) if pos_csv_path.exists() else []
    enriched = add_billing_abandonment_events(events, transactions)
    converted = converted_visitor_ids(enriched, transactions)
    _write_events(output_path, enriched)
    return {
        "input_events": len(events),
        "output_events": len(enriched),
        "converted_visitors": len(converted),
        "output": str(output_path),
    }


def _load_events(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_events(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in sorted(events, key=lambda row: row["timestamp"]):
            handle.write(json.dumps(event, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Correlate billing events with POS transactions.")
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--pos-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(correlate_file(args.events, args.pos_csv, args.output))


if __name__ == "__main__":
    main()
