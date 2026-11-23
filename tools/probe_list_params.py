"""Find a file-listing call that actually honours a directory path."""
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import PIKA_API_KEY, PIKA_BASE_URL  # noqa: E402

SRV = "de021d06-8c2d-40c9-b470-31c5eb240d92"
BASE = PIKA_BASE_URL
H = {"Authorization": f"Bearer {PIKA_API_KEY}", "Accept": "application/json"}


def names(entries):
    return sorted({e.get("name", "") for e in entries})


with httpx.Client(timeout=30.0, headers=H) as c:
    base = f"{BASE}/api/client/servers/{SRV}/files/list"

    trials = [
        ("path=/plugins", base, {"path": "/plugins"}),
        ("directory=/plugins", base, {"directory": "/plugins"}),
        ("dir=/plugins", base, {"dir": "/plugins"}),
        ("path=plugins", base, {"path": "plugins"}),
        ("path=/plugins/AuthMe", base, {"path": "/plugins/AuthMe"}),
        ("url /plugins", f"{BASE}/api/client/servers/{SRV}/files/list/plugins", {}),
        ("url /plugins/AuthMe", f"{BASE}/api/client/servers/{SRV}/files/list/plugins/AuthMe", {}),
        ("query ?path= on files/list/AuthMe", f"{BASE}/api/client/servers/{SRV}/files/list/AuthMe", {}),
    ]

    seen = {}
    for label, url, params in trials:
        r = c.get(url, params=params)
        if r.status_code != 200:
            print(f"{label:36} -> {r.status_code} {r.text[:80]}")
            continue
        data = r.json().get("entries", {}).get("data", [])
        ns = names(data)
        key = tuple(ns[:6])
        print(f"{label:36} -> 200 n={len(ns)} first={ns[:6]}")
        seen[label] = key

    print()
    print("distinct listings:", len(set(seen.values())), "of", len(seen))
