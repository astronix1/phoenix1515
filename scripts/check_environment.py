"""Check local configuration required to run the Phoenix Shopper Assistant."""

import os
import shutil
import socket
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) != 0


def main() -> int:
    issues = []

    mock_llm = os.getenv("MOCK_LLM", "true").lower() in {"1", "true", "yes", "on"}
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("LLM_API_KEY")
    if not mock_llm and not gemini_key:
        issues.append("MOCK_LLM=false but no GEMINI_API_KEY or LLM_API_KEY is configured")

    if shutil.which("python") is None and shutil.which("python3") is None:
        issues.append("Python is not available on PATH")

    requirements = BASE_DIR / "requirements.txt"
    if not requirements.is_file():
        issues.append("requirements.txt was not found")

    db_path = BASE_DIR / os.getenv("SQLITE_DB_PATH", "shop.db")
    if not db_path.exists():
        print(f"INFO: SQLite database will be created at {db_path}")

    for name, host, port in (
        ("API", "127.0.0.1", int(os.getenv("PORT", "8000"))),
        ("UI", "127.0.0.1", 8501),
    ):
        if port_available(host, port):
            print(f"OK: {name} port {port} is available")
        else:
            print(f"WARN: {name} port {port} is already in use")

    if issues:
        print("\n".join(f"ERROR: {issue}" for issue in issues), file=sys.stderr)
        return 1

    print("OK: environment configuration is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
