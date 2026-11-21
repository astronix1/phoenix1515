"""Small cross-platform commands for common repository development tasks."""

import argparse
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> int:
    process = subprocess.run(command, cwd=BASE_DIR)
    return process.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="Validate seed catalogue and shopper data")
    subparsers.add_parser("test", help="Run the standard-library unit test suite")
    subparsers.add_parser("environment", help="Check local runtime configuration")
    args = parser.parse_args()

    python = sys.executable or "python"
    if args.command == "validate":
        return run([python, "-m", "data.validate_data"])
    if args.command == "test":
        return run([python, "-m", "unittest", "discover", "-s", "tests", "-v"])
    if args.command == "environment":
        return run([python, "-m", "scripts.check_environment"])
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
