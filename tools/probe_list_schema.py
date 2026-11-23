"""Inspect the raw entry objects returned by /files/list to learn the schema."""
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import PIKA_API_KEY, PIKA_BASE_URL  # noqa: E402

SRV = "de021d06-8c2d-40c9-b470-31c5eb240d92"
BASE = PIKA_BASE_URL
H = {"Authorization": f"Bearer {PIKA_API_KEY}", "Accept": "application/json"}

with httpx.Client(timeout=30.0, headers=H) as c:
    for directory in ("/plugins", "/plugins/AuthMe", "/plugins/ExcellentEconomy"):
        r = c.get(f"{BASE}/api/client/servers/{SRV}/files/list",
                  params={"directory": directory, "per_page": 100})
        if r.status_code != 200:
            print(f"{directory}: {r.status_code} {r.text[:100]}")
            continue
        payload = r.json()
        entries = payload.get("entries", {})
        print(f"\n=== {directory} (total={entries.get('total')}) ===")
        print("  top-level keys:", list(payload.keys()))
        print("  entries keys:", list(entries.keys()))
        data = entries.get("data", [])
        if data:
            print("  first entry raw:")
            print("   ", json.dumps(data[0], ensure_ascii=False, indent=2)[:500])
            print("  all names:")
            print("   ", [e.get("name") for e in data][:40])
