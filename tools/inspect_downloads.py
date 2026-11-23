"""Inspect the downloaded databases and find every .db/.sqlite on the server."""
import os
import sqlite3
import sys
from pathlib import Path

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import PIKA_API_KEY, PIKA_BASE_URL  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRV = "de021d06-8c2d-40c9-b470-31c5eb240d92"
BASE = PIKA_BASE_URL
H = {"Authorization": f"Bearer {PIKA_API_KEY}", "Accept": "application/json"}

print("=== downloaded db contents ===")
for p in sorted((ROOT / "downloads").glob("*.db")):
    print(f"\n--- {p.name} ({p.stat().st_size:,} bytes) ---")
    con = sqlite3.connect(f"file:{p.resolve().as_posix()}?mode=ro", uri=True)
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print("  tables:", tables)
    for t in tables:
        try:
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            print(f"    {t}: {n}")
        except sqlite3.Error as exc:
            print(f"    {t}: ERR {exc}")
    con.close()

print("\n=== scan server for database files ===")
with httpx.Client(timeout=60.0, headers=H) as c:
    for base_path in ("/plugins", "/plugins/AuthMe", "/plugins/ExcellentEconomy",
                      "/plugins/Nexo", "/plugins/ItemsAdder", "/data"):
        r = c.get(f"{BASE}/api/client/servers/{SRV}/files/list",
                  params={"path": base_path, "per_page": 200})
        if r.status_code != 200:
            print(f"  {base_path}: {r.status_code}")
            continue
        entries = r.json().get("entries", {})
        data = entries.get("data", [])
        # the API seems to ignore `path` for some server versions; dedupe by name
        names = sorted({e.get("name", "") for e in data})
        interesting = [n for n in names if n.endswith((".db", ".sqlite", ".sqlite3", ".sql"))]
        print(f"  {base_path}: total={entries.get('total')} db-like={interesting}")
