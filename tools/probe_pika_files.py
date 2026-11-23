"""Probe the PikaMC panel API for file-download / file-list endpoints."""
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import PIKA_API_KEY, PIKA_BASE_URL  # noqa: E402

H = {
    "Authorization": f"Bearer {PIKA_API_KEY}",
    "Accept": "application/json",
}
SRV = "de021d06-8c2d-40c9-b470-31c5eb240d92"
BASE = PIKA_BASE_URL


def probe(method, path, **kw):
    url = f"{BASE}{path}"
    try:
        with httpx.Client(timeout=25.0) as c:
            r = c.request(method, url, headers=H, **kw)
        ct = r.headers.get("content-type", "")
        body = r.text[:300] if "json" in ct or "text" in ct else f"<{len(r.content)} bytes {ct}>"
        print(f"{method:6} {path:60} -> {r.status_code} {ct[:40]:25} {body[:160]}")
        return r
    except Exception as exc:
        print(f"{method:6} {path:60} -> EXC {exc}")
        return None


print("=== known-working endpoints ===")
probe("GET", f"/api/client/servers/{SRV}")
probe("POST", f"/api/client/servers/{SRV}/files/sqlite-query",
      json={"file": "/plugins/ExcellentEconomy/data.db", "query": "SELECT 1", "rows": 1, "read_only": True})

print()
print("=== file list / download candidates ===")
cands = [
    ("GET", f"/api/client/servers/{SRV}/files"),
    ("GET", f"/api/client/servers/{SRV}/files/list"),
    ("GET", f"/api/client/servers/{SRV}/files/list?path=/plugins"),
    ("GET", f"/api/client/servers/{SRV}/files/read?file=/plugins/ExcellentEconomy/data.db"),
    ("GET", f"/api/client/servers/{SRV}/files/download?file=/plugins/ExcellentEconomy/data.db"),
    ("GET", f"/api/client/servers/{SRV}/files/raw?file=/plugins/ExcellentEconomy/data.db"),
    ("GET", f"/api/client/servers/{SRV}/files/content?file=/plugins/ExcellentEconomy/data.db"),
    ("GET", f"/api/client/servers/{SRV}/files/backup"),
    ("GET", f"/api/client/servers/{SRV}/files/download"),
    ("GET", f"/api/client/servers/{SRV}/backups"),
    ("GET", f"/api/client/servers/{SRV}/files/sqlite-dump"),
]
for m, p in cands:
    probe(m, p)
