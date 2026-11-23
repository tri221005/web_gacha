"""Walk the whole server filesystem and collect every database / SQL dump file.

/files/list honours `directory` (not `path`). Entries carry a boolean
`directory` flag and a boolean `file` flag.
"""
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import PIKA_API_KEY, PIKA_BASE_URL  # noqa: E402

SRV = "de021d06-8c2d-40c9-b470-31c5eb240d92"
BASE = PIKA_BASE_URL
H = {"Authorization": f"Bearer {PIKA_API_KEY}", "Accept": "application/json"}
DB_EXT = (".db", ".sqlite", ".sqlite3", ".sql", ".mv.db", ".h2.db", ".csv")
SKIP_DIRS = {".trash", "cache", "libraries", "versions", "world", "logs", ".cache"}

found = []
visited = set()


def listing(client, directory):
    r = client.get(f"{BASE}/api/client/servers/{SRV}/files/list",
                   params={"directory": directory, "per_page": 100})
    if r.status_code != 200:
        return None
    return r.json().get("entries", {}).get("data", [])


with httpx.Client(timeout=90.0, headers=H) as c:
    queue = ["/"]
    while queue:
        directory = queue.pop(0)
        if directory in visited:
            continue
        visited.add(directory)
        entries = listing(c, directory)
        if entries is None:
            print(f"  !! cannot list {directory}")
            continue
        for e in entries:
            name = e.get("name", "")
            size = e.get("size", 0)
            full = f"{directory.rstrip('/')}/{name}"
            if e.get("directory"):
                if name not in SKIP_DIRS and not name.startswith("."):
                    queue.append(full)
            elif e.get("file") and name.lower().endswith(DB_EXT):
                found.append((full, size))
                print(f"  FOUND {full}  ({size:,} bytes)")

print()
print(f"=== {len(found)} database/data files ===")
for f, s in sorted(found, key=lambda x: -x[1]):
    print(f"  {s:>14,}  {f}")
