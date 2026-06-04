from __future__ import annotations

import csv
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.storage import init_db, insert_pos_transactions
from app.time_utils import to_iso_z


def _parse_pos_timestamp(date_text: str, time_text: str) -> str:
    try:
        local = ZoneInfo("Asia/Kolkata")
    except ZoneInfoNotFoundError:
        local = timezone(timedelta(hours=5, minutes=30), "IST")
    dt = datetime.strptime(f"{date_text} {time_text}", "%d-%m-%Y %H:%M:%S")
    return to_iso_z(dt.replace(tzinfo=local).astimezone(UTC)) or ""


def load_pos_csv(path: Path) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    totals: defaultdict[str, float] = defaultdict(float)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            invoice = row.get("invoice_number") or row.get("order_id")
            if not invoice:
                continue
            store_id = row.get("store_id") or row.get("store_name") or "UNKNOWN_STORE"
            amount_raw = row.get("total_amount") or row.get("NMV") or row.get("GMV") or "0"
            try:
                amount = float(amount_raw)
            except ValueError:
                amount = 0.0
            totals[invoice] += amount
            if invoice not in grouped:
                grouped[invoice] = {
                    "transaction_id": invoice,
                    "store_id": store_id,
                    "timestamp": _parse_pos_timestamp(
                        row.get("order_date", "01-01-1970"),
                        row.get("order_time", "00:00:00"),
                    ),
                    "basket_value_inr": 0.0,
                }

    transactions = []
    for invoice, txn in grouped.items():
        txn["basket_value_inr"] = round(totals[invoice], 2)
        transactions.append(txn)
    return transactions


def import_pos_csv(path: Path) -> tuple[int, int]:
    if not path.exists():
        return (0, 0)
    init_db()
    return insert_pos_transactions(load_pos_csv(path))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Import POS CSV into the API SQLite database.")
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()
    inserted, duplicates = import_pos_csv(args.csv_path)
    print({"inserted": inserted, "duplicates": duplicates})
