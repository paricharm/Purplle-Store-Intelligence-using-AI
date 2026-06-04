from __future__ import annotations

from datetime import UTC, datetime, time, timedelta


def parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_iso_z(value: str | datetime | None) -> str | None:
    if value is None:
        return None
    dt = parse_timestamp(value)
    return dt.isoformat().replace("+00:00", "Z")


def day_bounds_for(timestamp: str | datetime | None) -> tuple[datetime, datetime]:
    anchor = parse_timestamp(timestamp) if timestamp else datetime.now(UTC)
    start = datetime.combine(anchor.date(), time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def seconds_between(newer: str | datetime, older: str | datetime) -> float:
    return (parse_timestamp(newer) - parse_timestamp(older)).total_seconds()
