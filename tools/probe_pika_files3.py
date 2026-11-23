"""Inspect what /files/download returns and check the existing server_all_databases.sql."""
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import PIKA_API_KEY, PIKA_BASE_URL  # noqa: E402

H = {"Authorization": f"Bearer {PIKA_API_KEY}", "Accept": "application/json"}
SRV = "de021d06-8c2d-40c9-b470-31c5eb240d92"
BASE = PIKA_BASE_URL

with httpx.Client(timeout=60.0, headers=H) as c:
    print("=== /files/download response body ===")
    r = c.get(f"{BASE}/api/client/servers/{SRV}/files/download",
              params={"files": "/plugins/ExcellentEconomy/data.db"})
    print("status", r.status_code)
    try:
        print(json.dumps(r.json(), ensure_ascii=False)[:800])
    except Exception:
        print(r.text[:800])

    print()
    print("=== list /plugins/ExcellentEconomy ===")
    r = c.get(f"{BASE}/api/client/servers/{SRV}/files/list",
              params={"path": "/plugins/ExcellentEconomy", "per_page": 100})
    for e in r.json().get("entries", {}).get("data", []):
        print(f"  {e.get('size','?'):>12} {e.get('name')}")

    print()
    print("=== list /plugins/AuthMe ===")
    r = c.get(f"{BASE}/api/client/servers/{SRV}/files/list",
              params={"path": "/plugins/AuthMe", "per_page": 100})
    for e in r.json().get("entries", {}).get("data", []):
        print(f"  {e.get('size','?'):>12} {e.get('name')}")

    print()
    print("=== head of server_all_databases.sql (first 2000 chars) ===")
    r = c.get(f"{BASE}/api/client/servers/{SRV}/files/download",
              params={"files": "/plugins/server_all_databases.sql"})
    print("status", r.status_code, "len", len(r.content))
    print(r.text[:2000])
