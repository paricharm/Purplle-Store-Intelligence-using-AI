from __future__ import annotations

import argparse
import os
import time

import requests


def run_terminal_dashboard(api_url: str, store_id: str, refresh_seconds: float) -> None:
    while True:
        metrics = requests.get(f"{api_url.rstrip('/')}/stores/{store_id}/metrics", timeout=10).json()
        anomalies = requests.get(f"{api_url.rstrip('/')}/stores/{store_id}/anomalies", timeout=10).json()
        os.system("cls" if os.name == "nt" else "clear")
        print("Store Intelligence Live Dashboard")
        print("=" * 40)
        print(f"Store: {store_id}")
        print(f"Unique visitors: {metrics.get('unique_visitors', 0)}")
        print(f"Converted visitors: {metrics.get('converted_visitors', 0)}")
        print(f"Conversion rate: {metrics.get('conversion_rate', 0):.2%}")
        print(f"Queue depth: {metrics.get('queue_depth', 0)}")
        print(f"Abandonment rate: {metrics.get('abandonment_rate', 0):.2%}")
        print()
        print("Active anomalies:")
        for anomaly in anomalies.get("active_anomalies", []):
            print(f"- {anomaly['severity']} {anomaly['type']}: {anomaly['suggested_action']}")
        if not anomalies.get("active_anomalies"):
            print("- none")
        time.sleep(refresh_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Terminal dashboard for live store metrics.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--store-id", default="ST1008")
    parser.add_argument("--refresh-seconds", type=float, default=2.0)
    args = parser.parse_args()
    run_terminal_dashboard(args.api_url, args.store_id, args.refresh_seconds)
