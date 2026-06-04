from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.pos_import import load_pos_csv
from app.schemas import EventType
from app.time_utils import parse_timestamp
from pipeline.emit import build_event


def enrich_billing_abandonment_file(
    input_path: Path,
    output_path: Path,
    pos_csv_path: Path,
) -> int:
    events = _load_events(input_path)
    transactions = load_pos_csv(pos_csv_path) if pos_csv_path.exists() else []
    enriched = add_billing_abandonment_events(events, transactions)
    _write_events(output_path, enriched)
    return len(enriched)


def add_billing_abandonment_events(
    events: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing = {
        (event["store_id"], event["visitor_id"])
        for event in events
        if event["event_type"] == EventType.BILLING_QUEUE_ABANDON.value
    }
    transactions_by_store: dict[str, list[Any]] = {}
    for txn in transactions:
        transactions_by_store.setdefault(str(txn["store_id"]), []).append(parse_timestamp(str(txn["timestamp"])))

    billing_state: dict[tuple[str, str], dict[str, Any]] = {}
    generated: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda row: row["timestamp"]):
        key = (event["store_id"], event["visitor_id"])
        metadata = event.get("metadata") or {}
        if event["event_type"] == EventType.BILLING_QUEUE_JOIN.value:
            billing_state[key] = {
                "join_ts": parse_timestamp(event["timestamp"]),
                "queue_depth": metadata.get("queue_depth"),
                "sku_zone": metadata.get("sku_zone") or event.get("zone_id"),
                "is_staff": bool(event.get("is_staff", False)),
                "confidence": float(event.get("confidence", 0.5)),
                "camera_id": event["camera_id"],
            }
            continue

        if (
            event["event_type"] == EventType.ZONE_EXIT.value
            and str(event.get("zone_id") or "").upper() == "BILLING"
            and key in billing_state
            and key not in existing
            and not event.get("is_staff", False)
        ):
            state = billing_state.pop(key)
            exit_ts = parse_timestamp(event["timestamp"])
            purchase_window_end = exit_ts + timedelta(minutes=5)
            store_transactions = transactions_by_store.get(event["store_id"], [])
            converted = any(state["join_ts"] <= txn_ts <= purchase_window_end for txn_ts in store_transactions)
            if converted:
                continue

            generated.append(
                build_event(
                    store_id=event["store_id"],
                    camera_id=event["camera_id"],
                    visitor_id=event["visitor_id"],
                    event_type=EventType.BILLING_QUEUE_ABANDON,
                    timestamp=exit_ts,
                    zone_id="BILLING",
                    dwell_ms=max(0, int(event.get("dwell_ms") or 0)),
                    is_staff=False,
                    confidence=min(float(event.get("confidence", state["confidence"])), state["confidence"]),
                    metadata={
                        **metadata,
                        "queue_depth": state["queue_depth"],
                        "sku_zone": state["sku_zone"],
                        "session_seq": int((metadata.get("session_seq") or 0)) + 1,
                        "abandonment_reason": "left_billing_without_pos_transaction_within_5_minutes",
                        "pos_correlation_window_minutes": 5,
                    },
                )
            )
            existing.add(key)

    if not generated:
        return events
    return sorted([*events, *generated], key=lambda row: row["timestamp"])


def _load_events(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_events(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Add POS-aware billing abandonment events.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pos-csv", type=Path, default=Path("sample_data/sample_pos_transactions.csv"))
    args = parser.parse_args()
    count = enrich_billing_abandonment_file(args.input, args.output, args.pos_csv)
    print({"events_written": count, "output": str(args.output)})


if __name__ == "__main__":
    main()
