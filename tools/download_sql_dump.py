"""Try alternate paths for the SQL dump and plugins.json."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.pika_download import download  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

candidates = [
    ("/server_all_databases.sql", "downloads/server_all_databases.sql"),
    ("/plugins/.plugins.json", "downloads/plugins_plugins.json"),
    ("/.plugins.json", "downloads/plugins.json"),
]

for remote, local in candidates:
    print(f"[{remote}]")
    try:
        n = download(remote, ROOT / local)
        print(f"  OK saved {n:,} bytes -> {local}")
    except Exception as exc:
        print(f"  FAILED: {str(exc)[:120]}")
