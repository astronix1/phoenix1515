"""Create a consistent timestamped backup of a SQLite database."""

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


def backup_database(source: Path, destination: Path) -> Path:
    source = source.resolve()
    destination = destination.resolve()

    if not source.is_file():
        raise FileNotFoundError(f"SQLite database not found: {source}")

    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = destination / f"{source.stem}-{timestamp}.db"

    with sqlite3.connect(source) as source_db:
        with sqlite3.connect(backup_path) as backup_db:
            source_db.backup(backup_db)

    return backup_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=BASE_DIR / "shop.db",
        help="SQLite database to back up",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=BASE_DIR / "backups",
        help="Directory where the backup will be written",
    )
    args = parser.parse_args()

    try:
        backup_path = backup_database(args.source, args.destination)
    except (sqlite3.Error, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Created backup: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
