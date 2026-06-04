from __future__ import annotations

import argparse

from dashboard.app import run_terminal_dashboard


def main() -> None:
    parser = argparse.ArgumentParser(description="Terminal dashboard for live store metrics.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--store-id", default="STORE_BLR_002")
    parser.add_argument("--refresh-seconds", type=float, default=2.0)
    args = parser.parse_args()
    run_terminal_dashboard(args.api_url, args.store_id, args.refresh_seconds)


if __name__ == "__main__":
    main()
