"""Compare the live PikaMC data against what the SQL Server dump holds."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import store  # noqa: E402
from app.pika import sqlite_query  # noqa: E402

store.init()


async def main() -> None:
    live_auth = await sqlite_query(
        "/plugins/AuthMe/authme.db",
        "SELECT username, realname, lastlogin FROM authme",
        rows=500,
    )
    live_eco = await sqlite_query(
        "/plugins/ExcellentEconomy/data.db",
        "SELECT name, money, last_seen FROM excellenteconomy_users",
        rows=500,
    )

    with store._lock:
        con = store.connect()
        cur = con.cursor()
        cur.execute("SELECT username, realname FROM authme_authme")
        sql_auth = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT name, CAST(money AS BIGINT) FROM excellenteconomy_excellenteconomy_users")
        sql_eco = {r[0]: r[1] for r in cur.fetchall()}

    print(f"authme: live={len(live_auth)} sqlserver={len(sql_auth)}")
    live_names = {str(r.get("username")) for r in live_auth}
    sql_names = set(sql_auth)
    only_live = sorted(live_names - sql_names)
    only_sql = sorted(sql_names - live_names)
    print(f"  only in live      ({len(only_live)}): {only_live[:12]}")
    print(f"  only in sqlserver ({len(only_sql)}): {only_sql[:12]}")

    print(f"\neconomy: live={len(live_eco)} sqlserver={len(sql_eco)}")
    # A player can have more than one economy account with the same name.
    # The live one is the one seen most recently; the older ones are stale.
    live_e: dict[str, float] = {}
    live_seen: dict[str, int] = {}
    for row in live_eco:
        name = str(row.get("name"))
        seen = int(row.get("last_seen") or 0)
        if name not in live_seen or seen > live_seen[name]:
            live_seen[name] = seen
            live_e[name] = float(row.get("money") or 0)
    diff = []
    for name, money in live_e.items():
        if name in sql_eco and abs(sql_eco[name] - money) > 1:
            diff.append((name, sql_eco[name], money))
    print(f"  balance differs for {len(diff)} players:")
    for name, old, new in sorted(diff, key=lambda d: -abs(d[1] - d[2]))[:12]:
        print(f"    {name:18} sql={old:>12,}  live={new:>12,.0f}  delta={new - old:>+12,.0f}")

    # what the web wallet holds right now
    with store._lock:
        con = store.connect()
        cur = con.cursor()
        cur.execute("SELECT player, balance, is_bot FROM gacha_wallets WHERE is_bot = 0")
        print("\nweb wallets (non-bot) vs live pika balance:")
        for player, balance, _ in cur.fetchall():
            live = live_e.get(player)
            flag = ""
            if live is not None and abs(live - balance) > 1:
                flag = "  <-- MISMATCH"
            print(f"    {player:14} web={balance:>10,}  pika={live!s:>14}{flag}")


asyncio.run(main())
