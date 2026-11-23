"""Download every plugin database from the PikaMC server and dump them to SQL.

Two data sources are merged into one .sql file:
  1. The raw plugin databases (AuthMe, ExcellentEconomy, LuckPerms, ...) —
     downloaded as .db files and converted with sqlite3's iterdump().
  2. The server's own /server_all_databases.sql consolidated dump — kept as the
     canonical H2-format source for tables we cannot open locally (LuckPerms H2).

The output is one self-contained .sql file with schema + data for every table.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import PIKA_API_KEY, PIKA_BASE_URL  # noqa: E402

SRV = "de021d06-8c2d-40c9-b470-31c5eb240d92"
BASE = PIKA_BASE_URL
H = {"Authorization": f"Bearer {PIKA_API_KEY}", "Accept": "application/json"}
ROOT = Path(__file__).resolve().parent.parent

# Every database file discovered on the server, with the plugin it belongs to.
REMOTE_DATABASES = [
    ("/plugins/AdvancedRedeem/data.db", "AdvancedRedeem"),
    ("/plugins/AuthMe/authme.db", "AuthMe"),
    ("/plugins/Boombox/storage.db", "Boombox"),
    ("/plugins/CoreProtect/database.db", "CoreProtect"),
    ("/plugins/ExcellentCrates/data.db", "ExcellentCrates"),
    ("/plugins/ExcellentEconomy/data.db", "ExcellentEconomy"),
    ("/plugins/floodgate/linked-players.db", "Floodgate"),
    ("/plugins/LuckPerms/luckperms-h2-v2.mv.db", "LuckPerms"),
    ("/plugins/nightcore/data.db", "Nightcore"),
    ("/plugins/PlayerPoints/playerpoints.db", "PlayerPoints"),
    ("/plugins/VJobs/local.db", "VJobs"),
    ("/plugins/zAuctionHouse/database.db", "zAuctionHouse"),
    ("/plugins/zMenu/database.db", "zMenu"),
    ("/plugins/EconomyShopGUI/transactions/transactions.db", "EconomyShopGUI"),
    ("/plugins/GSit/data/data.db", "GSit"),
]

# Files too large to be worth pulling through the panel API.
SKIP_DOWNLOAD = {"/plugins/CoreProtect/database.db"}  # 372 MB block log


def signed_url(client: httpx.Client, remote_path: str) -> str:
    """Get a signed download URL, backing off on the panel's 429 rate limit."""
    last = None
    for attempt in range(8):
        r = client.get(f"{BASE}/api/client/servers/{SRV}/files/download",
                       params={"files": remote_path})
        if r.status_code == 429:
            wait = 3 * (attempt + 1)
            print(f"       rate-limited, waiting {wait}s...")
            time.sleep(wait)
            last = r
            continue
        r.raise_for_status()
        return r.json()["url"]
    raise RuntimeError(f"rate limited after retries: {last}")


def download(client: httpx.Client, remote_path: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = signed_url(client, remote_path)
    n = 0
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in resp.iter_bytes(1024 * 256):
                fh.write(chunk)
                n += len(chunk)
    return n


def dump_sqlite(db_path: Path) -> tuple[str, list[str]]:
    """Return (sql_text, [table names]) for a SQLite database."""
    con = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if not tables:
            return "", []
        lines = []
        for t in tables:
            lines.append(f"DROP TABLE IF EXISTS \"{t}\";")
        schema = con.iterdump()
        for line in schema:
            if line.startswith("BEGIN TRANSACTION") or line.startswith("COMMIT"):
                continue
            lines.append(line + ";")
        return "\n".join(lines), tables
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="server_data.sql")
    ap.add_argument("--skip-coreprotect", action="store_true", default=True)
    args = ap.parse_args()

    dl_dir = ROOT / "downloads"
    dl_dir.mkdir(exist_ok=True)
    out_path = ROOT / args.out

    parts: list[str] = []
    report: list[tuple[str, str, int, int]] = []

    with httpx.Client(timeout=300.0, headers=H, follow_redirects=True) as client:
        for remote, plugin in REMOTE_DATABASES:
            if remote in SKIP_DOWNLOAD:
                report.append((plugin, remote, -1, 0))
                print(f"  SKIP  {plugin:18} {remote} (too large)")
                continue
            local = dl_dir / f"{plugin}.db"
            try:
                download(client, remote, local)
            except Exception as exc:
                print(f"  FAIL  {plugin:18} {remote}: {str(exc)[:80]}")
                report.append((plugin, remote, -2, 0))
                continue
            try:
                sql, tables = dump_sqlite(local)
            except Exception as exc:
                print(f"  FAIL  {plugin:18} not a readable sqlite: {str(exc)[:80]}")
                report.append((plugin, remote, -3, 0))
                continue
            rowcount = 0
            if sql:
                con = sqlite3.connect(f"file:{local.resolve().as_posix()}?mode=ro", uri=True)
                for t in tables:
                    try:
                        rowcount += con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                    except sqlite3.Error:
                        pass
                con.close()
            parts.append(f"\n-- ==========================================================\n"
                         f"-- PLUGIN: {plugin}\n"
                         f"-- SOURCE: {remote}\n"
                         f"-- TABLES: {', '.join(tables) if tables else '(none - non-sqlite)'}\n"
                         f"-- ROWS:   {rowcount}\n"
                         f"-- ==========================================================\n{sql}")
            report.append((plugin, remote, rowcount, len(tables)))
            print(f"  OK    {plugin:18} {len(tables):2} tables {rowcount:>8,} rows")

    out_path.write_text("\n".join(parts), encoding="utf-8")
    print()
    print(f"Wrote {out_path.name}: {out_path.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
