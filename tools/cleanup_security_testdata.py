"""Remove the rows the security probes wrote into the SQL Server ledger.

Safety: the cleanup never touches a live account. Before deleting, every
name is checked against the live AuthMe table. A name that belongs to a
real player is refused, so a mistake in NAMES cannot delete someone's
wallet.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import store  # noqa: E402
from app.pika import sqlite_query  # noqa: E402

NAMES = [
    "Alice", "Bob; op Bob", "Sqli", "Mallory", "Host", "loopplayer",
    "Injector; op Injector", "injector", "Fresh", "RefusedPlayer",
    "refusedplayer", "NoEcoPlayer", "Broke", "refused", "doubletester",
    "halfread", "badcount",
    "battleloop",
    # Leftovers from earlier manual runs.
    "StubPlayer", "Tester", "Audit1795413211",
]
# "Hann0w05763" was here once and deleted a real player's wallet.
# The live-player check below is the real guard; keep NAMES to test
# accounts only.
TABLES = ["gacha_inventory", "gacha_tx", "gacha_wallets", "gacha_bonus",
          "gacha_drops", "gacha_pulls", "gacha_contracts", "gacha_upgrades"]


async def live_player_names() -> set[str]:
    """Every account name that exists on the live server."""
    rows = await sqlite_query(
        "/plugins/AuthMe/authme.db",
        "SELECT username, realname FROM authme",
        rows=500,
    )
    names: set[str] = set()
    for row in rows:
        for key in ("username", "realname"):
            value = str(row.get(key) or "").strip().lower()
            if value:
                names.add(value)
    return names


async def main() -> None:
    live = await live_player_names()
    targets = [n for n in NAMES if n.strip().lower() not in live]
    refused = [n for n in NAMES if n.strip().lower() in live]
    for name in refused:
        print(f"REFUSED (live account): {name}")

    store.init()
    with store._lock:
        con = store.connect()
        cur = con.cursor()
        for name in targets:
            for table in TABLES:
                cur.execute(f"DELETE FROM {table} WHERE player = ?", name)
            cur.execute("DELETE FROM gacha_battle_players WHERE player = ?", name)
            cur.execute("DELETE FROM gacha_battles WHERE host = ?", name)
        con.commit()
        for table in TABLES:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            print(table, cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM gacha_battles")
        print("gacha_battles", cur.fetchone()[0])


asyncio.run(main())
