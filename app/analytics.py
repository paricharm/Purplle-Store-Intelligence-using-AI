from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.config import settings
from app.layout import billing_zone_ids, zones_for_store
from app.storage import fetch_events, fetch_pos_transactions, latest_event_timestamp
from app.time_utils import day_bounds_for, parse_timestamp, to_iso_z


def _business_window(store_id: str, db_path: Path | None = None) -> tuple[str, str]:
    latest = latest_event_timestamp(store_id, db_path)
    start, end = day_bounds_for(latest)
    return to_iso_z(start) or "", to_iso_z(end) or ""


def _metadata(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["metadata_json"] or "{}")
    except json.JSONDecodeError:
        return {}


def _customer_events(store_id: str, db_path: Path | None = None) -> list[Any]:
    start, end = _business_window(store_id, db_path)
    return [
        row
        for row in fetch_events(store_id, start, end, db_path)
        if not row["is_staff"] and row["event_type"] != "DETECTION"
    ]


def converted_visitors(store_id: str, db_path: Path | None = None) -> set[str]:
    start, end = _business_window(store_id, db_path)
    events = [
        row
        for row in fetch_events(store_id, start, end, db_path)
        if not row["is_staff"] and row["event_type"] != "DETECTION"
    ]
    transactions = fetch_pos_transactions(store_id, start, end, db_path)
    return _converted_visitors_from_events(store_id, events, transactions)


def _converted_visitors_from_events(
    store_id: str, events: list[Any], transactions: list[Any]
) -> set[str]:
    billing_zones = billing_zone_ids(store_id)
    billing_events = [
        row
        for row in events
        if row["event_type"] in {"BILLING_QUEUE_JOIN", "ZONE_ENTER", "ZONE_DWELL"}
        and (row["zone_id"] in billing_zones or row["event_type"] == "BILLING_QUEUE_JOIN")
    ]

    converted: set[str] = set()
    for txn in transactions:
        txn_ts = parse_timestamp(txn["timestamp"])
        window_start = txn_ts - timedelta(minutes=5)
        for event in billing_events:
            event_ts = parse_timestamp(event["timestamp"])
            if window_start <= event_ts <= txn_ts:
                converted.add(event["visitor_id"])
    return converted


def compute_live_analytics(store_id: str, db_path: Path | None = None) -> dict[str, Any]:
    start, end = _business_window(store_id, db_path)
    events = [
        row
        for row in fetch_events(store_id, start, end, db_path)
        if not row["is_staff"] and row["event_type"] != "DETECTION"
    ]
    transactions = fetch_pos_transactions(store_id, start, end, db_path)
    converted = _converted_visitors_from_events(store_id, events, transactions)

    metrics = _metrics_from_events(store_id, events, converted, start, end)
    funnel = _funnel_from_events(store_id, events, converted)
    heatmap = _heatmap_from_events(store_id, events)
    anomalies = _anomalies_from_events(store_id, events, metrics)
    return {
        "metrics": metrics,
        "funnel": funnel,
        "heatmap": heatmap,
        "anomalies": anomalies,
    }


def _metrics_from_events(
    store_id: str,
    events: list[Any],
    converted: set[str],
    start: str,
    end: str,
) -> dict[str, Any]:
    visitors = {row["visitor_id"] for row in events}
    dwell_by_zone: dict[str, list[int]] = defaultdict(list)
    for row in events:
        if row["event_type"] == "ZONE_DWELL" and row["zone_id"]:
            dwell_by_zone[row["zone_id"]].append(int(row["dwell_ms"]))

    avg_dwell = [
        {
            "zone_id": zone_id,
            "avg_dwell_ms": round(sum(values) / len(values), 2),
            "sample_count": len(values),
        }
        for zone_id, values in sorted(dwell_by_zone.items())
    ]

    latest_queue_depth = 0
    for row in events:
        meta = _metadata(row)
        if row["event_type"] == "BILLING_QUEUE_JOIN" and meta.get("queue_depth") is not None:
            latest_queue_depth = int(meta["queue_depth"])

    billing_sessions = {
        row["visitor_id"]
        for row in events
        if row["event_type"] == "BILLING_QUEUE_JOIN"
        or (row["zone_id"] and "BILL" in row["zone_id"].upper())
    }
    abandoned = {
        row["visitor_id"] for row in events if row["event_type"] == "BILLING_QUEUE_ABANDON"
    }

    return {
        "store_id": store_id,
        "window": {"start": start, "end": end},
        "unique_visitors": len(visitors),
        "converted_visitors": len(converted),
        "conversion_rate": round(len(converted) / len(visitors), 4) if visitors else 0,
        "avg_dwell_per_zone": avg_dwell,
        "queue_depth": latest_queue_depth,
        "abandonment_rate": round(len(abandoned) / len(billing_sessions), 4) if billing_sessions else 0,
    }


def _funnel_from_events(store_id: str, events: list[Any], converted: set[str]) -> dict[str, Any]:
    entry = {
        row["visitor_id"]
        for row in events
        if row["event_type"] in {"ENTRY", "REENTRY"}
    } or {row["visitor_id"] for row in events}
    zone_visit = {
        row["visitor_id"]
        for row in events
        if row["event_type"] in {"ZONE_ENTER", "ZONE_DWELL"} and row["zone_id"]
    }
    billing = {
        row["visitor_id"]
        for row in events
        if row["event_type"] == "BILLING_QUEUE_JOIN"
        or (row["zone_id"] and "BILL" in row["zone_id"].upper())
    }
    purchase = set(converted)

    if entry:
        zone_visit = zone_visit & entry
        billing = billing & zone_visit
        purchase = purchase & billing

    raw_stages = [
        ("Entry", entry),
        ("Zone Visit", zone_visit),
        ("Billing Queue", billing),
        ("Purchase", purchase),
    ]
    stages = []
    previous_count: int | None = None
    for name, visitors in raw_stages:
        count = len(visitors)
        if previous_count is None or previous_count == 0:
            dropoff = 0.0
        else:
            dropoff = round((previous_count - count) / previous_count, 4)
        stages.append({"stage": name, "count": count, "dropoff_from_previous": dropoff})
        previous_count = count

    return {"store_id": store_id, "unit": "session", "stages": stages}


def _heatmap_from_events(store_id: str, events: list[Any]) -> dict[str, Any]:
    sessions = {row["visitor_id"] for row in events}
    zone_visitors: dict[str, set[str]] = defaultdict(set)
    zone_dwell: dict[str, list[int]] = defaultdict(list)

    for row in events:
        zone_id = row["zone_id"]
        if not zone_id:
            continue
        if row["event_type"] in {"ZONE_ENTER", "ZONE_DWELL", "BILLING_QUEUE_JOIN"}:
            zone_visitors[zone_id].add(row["visitor_id"])
        if row["event_type"] == "ZONE_DWELL":
            zone_dwell[zone_id].append(int(row["dwell_ms"]))

    configured_zones = [zone["zone_id"] for zone in zones_for_store(store_id)]
    all_zones = sorted(set(configured_zones) | set(zone_visitors) | set(zone_dwell))
    max_visits = max((len(zone_visitors[z]) for z in all_zones), default=0)

    zones = []
    for zone_id in all_zones:
        visits = len(zone_visitors[zone_id])
        dwell_values = zone_dwell[zone_id]
        avg_dwell = round(sum(dwell_values) / len(dwell_values), 2) if dwell_values else 0
        normalized = int(round((visits / max_visits) * 100)) if max_visits else 0
        zones.append(
            {
                "zone_id": zone_id,
                "visit_frequency": visits,
                "avg_dwell_ms": avg_dwell,
                "normalized_score": normalized,
            }
        )

    return {
        "store_id": store_id,
        "session_count": len(sessions),
        "data_confidence": "HIGH" if len(sessions) >= 20 else "LOW",
        "zones": zones,
    }


def _anomalies_from_events(
    store_id: str, events: list[Any], metrics: dict[str, Any]
) -> dict[str, Any]:
    anomalies: list[dict[str, Any]] = []

    if metrics["queue_depth"] >= settings.queue_spike_threshold:
        anomalies.append(
            {
                "type": "BILLING_QUEUE_SPIKE",
                "severity": "CRITICAL" if metrics["queue_depth"] >= settings.queue_spike_threshold * 2 else "WARN",
                "evidence": {"queue_depth": metrics["queue_depth"]},
                "suggested_action": "Move an associate to billing and open an additional counter if available.",
            }
        )

    configured = {zone["zone_id"] for zone in zones_for_store(store_id)}
    latest = max((parse_timestamp(row["timestamp"]) for row in events), default=None)
    if latest:
        cutoff = latest - timedelta(minutes=30)
        recent_zones = {
            row["zone_id"]
            for row in events
            if row["zone_id"] and parse_timestamp(row["timestamp"]) >= cutoff
        }
        dead_zones = sorted(configured - recent_zones)
        for zone_id in dead_zones:
            anomalies.append(
                {
                    "type": "DEAD_ZONE",
                    "severity": "INFO",
                    "evidence": {"zone_id": zone_id, "minutes_without_visit": 30},
                    "suggested_action": f"Check visibility, planogram, or staff coverage for {zone_id}.",
                }
            )

    current_rate = metrics["conversion_rate"]
    if len(events) >= 10 and current_rate < 0.05:
        anomalies.append(
            {
                "type": "CONVERSION_DROP",
                "severity": "WARN",
                "evidence": {"current_conversion_rate": current_rate},
                "suggested_action": "Inspect billing wait time and high-dwell zones that are not converting.",
            }
        )

    return {"store_id": store_id, "active_anomalies": anomalies}


def compute_metrics(store_id: str, db_path: Path | None = None) -> dict[str, Any]:
    events = _customer_events(store_id, db_path)
    visitors = {row["visitor_id"] for row in events}
    converted = converted_visitors(store_id, db_path)

    dwell_by_zone: dict[str, list[int]] = defaultdict(list)
    for row in events:
        if row["event_type"] == "ZONE_DWELL" and row["zone_id"]:
            dwell_by_zone[row["zone_id"]].append(int(row["dwell_ms"]))

    avg_dwell = [
        {
            "zone_id": zone_id,
            "avg_dwell_ms": round(sum(values) / len(values), 2),
            "sample_count": len(values),
        }
        for zone_id, values in sorted(dwell_by_zone.items())
    ]

    latest_queue_depth = 0
    for row in events:
        meta = _metadata(row)
        if row["event_type"] == "BILLING_QUEUE_JOIN" and meta.get("queue_depth") is not None:
            latest_queue_depth = int(meta["queue_depth"])

    billing_sessions = {
        row["visitor_id"]
        for row in events
        if row["event_type"] == "BILLING_QUEUE_JOIN"
        or (row["zone_id"] and "BILL" in row["zone_id"].upper())
    }
    abandoned = {
        row["visitor_id"] for row in events if row["event_type"] == "BILLING_QUEUE_ABANDON"
    }

    return {
        "store_id": store_id,
        "window": {"start": _business_window(store_id, db_path)[0], "end": _business_window(store_id, db_path)[1]},
        "unique_visitors": len(visitors),
        "converted_visitors": len(converted),
        "conversion_rate": round(len(converted) / len(visitors), 4) if visitors else 0,
        "avg_dwell_per_zone": avg_dwell,
        "queue_depth": latest_queue_depth,
        "abandonment_rate": round(len(abandoned) / len(billing_sessions), 4) if billing_sessions else 0,
    }


def compute_funnel(store_id: str, db_path: Path | None = None) -> dict[str, Any]:
    events = _customer_events(store_id, db_path)
    entry = {
        row["visitor_id"]
        for row in events
        if row["event_type"] in {"ENTRY", "REENTRY"}
    } or {row["visitor_id"] for row in events}
    zone_visit = {
        row["visitor_id"]
        for row in events
        if row["event_type"] in {"ZONE_ENTER", "ZONE_DWELL"} and row["zone_id"]
    }
    billing = {
        row["visitor_id"]
        for row in events
        if row["event_type"] == "BILLING_QUEUE_JOIN"
        or (row["zone_id"] and "BILL" in row["zone_id"].upper())
    }
    purchase = converted_visitors(store_id, db_path)

    if entry:
        zone_visit = zone_visit & entry
        billing = billing & zone_visit
        purchase = purchase & billing

    raw_stages = [
        ("Entry", entry),
        ("Zone Visit", zone_visit),
        ("Billing Queue", billing),
        ("Purchase", purchase),
    ]
    stages = []
    previous_count: int | None = None
    for name, visitors in raw_stages:
        count = len(visitors)
        if previous_count is None:
            dropoff = 0.0
        elif previous_count == 0:
            dropoff = 0.0
        else:
            dropoff = round((previous_count - count) / previous_count, 4)
        stages.append({"stage": name, "count": count, "dropoff_from_previous": dropoff})
        previous_count = count

    return {"store_id": store_id, "unit": "session", "stages": stages}


def compute_heatmap(store_id: str, db_path: Path | None = None) -> dict[str, Any]:
    events = _customer_events(store_id, db_path)
    sessions = {row["visitor_id"] for row in events}
    zone_visitors: dict[str, set[str]] = defaultdict(set)
    zone_dwell: dict[str, list[int]] = defaultdict(list)

    for row in events:
        zone_id = row["zone_id"]
        if not zone_id:
            continue
        if row["event_type"] in {"ZONE_ENTER", "ZONE_DWELL", "BILLING_QUEUE_JOIN"}:
            zone_visitors[zone_id].add(row["visitor_id"])
        if row["event_type"] == "ZONE_DWELL":
            zone_dwell[zone_id].append(int(row["dwell_ms"]))

    configured_zones = [zone["zone_id"] for zone in zones_for_store(store_id)]
    all_zones = sorted(set(configured_zones) | set(zone_visitors) | set(zone_dwell))
    max_visits = max((len(zone_visitors[z]) for z in all_zones), default=0)

    zones = []
    for zone_id in all_zones:
        visits = len(zone_visitors[zone_id])
        dwell_values = zone_dwell[zone_id]
        avg_dwell = round(sum(dwell_values) / len(dwell_values), 2) if dwell_values else 0
        normalized = int(round((visits / max_visits) * 100)) if max_visits else 0
        zones.append(
            {
                "zone_id": zone_id,
                "visit_frequency": visits,
                "avg_dwell_ms": avg_dwell,
                "normalized_score": normalized,
            }
        )

    return {
        "store_id": store_id,
        "session_count": len(sessions),
        "data_confidence": "HIGH" if len(sessions) >= 20 else "LOW",
        "zones": zones,
    }


def compute_anomalies(store_id: str, db_path: Path | None = None) -> dict[str, Any]:
    metrics = compute_metrics(store_id, db_path)
    events = _customer_events(store_id, db_path)
    anomalies: list[dict[str, Any]] = []

    if metrics["queue_depth"] >= settings.queue_spike_threshold:
        anomalies.append(
            {
                "type": "BILLING_QUEUE_SPIKE",
                "severity": "CRITICAL" if metrics["queue_depth"] >= settings.queue_spike_threshold * 2 else "WARN",
                "evidence": {"queue_depth": metrics["queue_depth"]},
                "suggested_action": "Move an associate to billing and open an additional counter if available.",
            }
        )

    configured = {zone["zone_id"] for zone in zones_for_store(store_id)}
    latest = latest_event_timestamp(store_id, db_path)
    if latest:
        cutoff = parse_timestamp(latest) - timedelta(minutes=30)
        recent_zones = {
            row["zone_id"]
            for row in events
            if row["zone_id"] and parse_timestamp(row["timestamp"]) >= cutoff
        }
        dead_zones = sorted(configured - recent_zones)
        for zone_id in dead_zones:
            anomalies.append(
                {
                    "type": "DEAD_ZONE",
                    "severity": "INFO",
                    "evidence": {"zone_id": zone_id, "minutes_without_visit": 30},
                    "suggested_action": f"Check visibility, planogram, or staff coverage for {zone_id}.",
                }
            )

    current_rate = metrics["conversion_rate"]
    if len(events) >= 10 and current_rate < 0.05:
        anomalies.append(
            {
                "type": "CONVERSION_DROP",
                "severity": "WARN",
                "evidence": {"current_conversion_rate": current_rate},
                "suggested_action": "Inspect billing wait time and high-dwell zones that are not converting.",
            }
        )

    return {"store_id": store_id, "active_anomalies": anomalies}
