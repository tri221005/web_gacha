"""Explore PikaMC files API: list entries + try downloading a binary file."""
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

with httpx.Client(timeout=30.0, headers=H) as c:
    print("=== /files/list?path=/plugins (page 1, per_page 100) ===")
    r = c.get(f"{BASE}/api/client/servers/{SRV}/files/list",
              params={"path": "/plugins", "per_page": 100})
    data = r.json()
    entries = data.get("entries", {})
    print("total:", entries.get("total"))
    for e in entries.get("data", []):
        print(f"  {e.get('type','?'):6} {e.get('size','?'):>12} {e.get('name')}")

    print()
    print("=== try files/download with files param ===")
    for path in ("/plugins/ExcellentEconomy/data.db", "/plugins/AuthMe/authme.db"):
        for extra in ({}, {"files": path}):
            params = extra if extra else {"path": "/plugins"}
            r = c.get(f"{BASE}/api/client/servers/{SRV}/files/download", params=params)
            print(f"  params={params} -> {r.status_code} {r.headers.get('content-type','')} "
                  f"len={len(r.content)}")
            if r.status_code == 200 and "json" not in r.headers.get("content-type", ""):
                print(f"    binary! first bytes: {r.content[:16]!r}")

    print()
    print("=== try /files/download POST ===")
    r = c.post(f"{BASE}/api/client/servers/{SRV}/files/download",
               json={"files": "/plugins/ExcellentEconomy/data.db"})
    print(f"  POST json -> {r.status_code} {r.headers.get('content-type','')} len={len(r.content)}")
    print("  ", r.text[:300])
