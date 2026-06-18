from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .pipeline import ingest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kenyan Google Trends data pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest_parser = subparsers.add_parser("ingest", help="Fetch and load the current RSS feed")
    ingest_parser.add_argument("--geo", default=os.getenv("TRENDS_GEO", "KE"))
    ingest_parser.add_argument(
        "--db", type=Path, default=Path(os.getenv("TRENDS_DB_PATH", "data/search_behaviour.db"))
    )
    ingest_parser.add_argument(
        "--raw-dir", type=Path, default=Path(os.getenv("TRENDS_RAW_DIR", "data/raw"))
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "ingest":
        result = ingest(geo=args.geo, db_path=args.db, raw_dir=args.raw_dir)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

