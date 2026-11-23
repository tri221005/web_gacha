"""Refresh the AuthMe and ExcellentEconomy tables in SQL Server from live PikaMC.

The .sql dump is a snapshot; this pulls the current rows straight from the
server so the local mirror of the player data stays fresh.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import store  # noqa: E402
from app.pika import sqlite_query  # noqa: E402


async def main() -> None:
    store.init()

    auth_rows = await sqlite_query(
        "/plugins/AuthMe/authme.db",
        "SELECT username, realname, password, ip, lastlogin, regip, regdate, "
        "x, y, z, world, yaw, pitch, email, isLogged, hasSession, totp, premiumUUID "
        "FROM authme",
        rows=1000,
    )
    eco_rows = await sqlite_query(
        "/plugins/ExcellentEconomy/data.db",
        "SELECT uuid, name, last_seen, settings, hiddenFromTops, money, shards, coins "
        "FROM excellenteconomy_users",
        rows=1000,
    )
    print(f"live rows: authme={len(auth_rows)} economy={len(eco_rows)}")

    with store._lock:
        con = store.connect()
        cur = con.cursor()

        cur.execute("DELETE FROM authme_authme")
        for r in auth_rows:
            cur.execute(
                "INSERT INTO authme_authme (username, realname, password, ip, "
                "lastlogin, regip, regdate, x, y, z, world, yaw, pitch, email, "
                "isLogged, hasSession, totp, premiumUUID) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                r.get("username"), r.get("realname"), r.get("password"),
                r.get("ip"), _ms_to_dt(r.get("lastlogin")), r.get("regip"),
                _ms_to_dt(r.get("regdate")), r.get("x") or 0.0, r.get("y") or 0.0,
                r.get("z") or 0.0, r.get("world") or "world", r.get("yaw"),
                r.get("pitch"), r.get("email"), r.get("isLogged") or 0,
                r.get("hasSession") or 0, r.get("totp"), r.get("premiumUUID"),
            )

        cur.execute("DELETE FROM excellenteconomy_excellenteconomy_users")
        for r in eco_rows:
            cur.execute(
                "INSERT INTO excellenteconomy_excellenteconomy_users "
                "(uuid, name, last_seen, settings, hiddenFromTops, money, shards, coins) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                r.get("uuid"), r.get("name"), r.get("last_seen"),
                r.get("settings"), r.get("hiddenFromTops") or 0,
                r.get("money") or 0, r.get("shards") or 0, r.get("coins") or 0,
            )
        con.commit()

        cur.execute("SELECT COUNT(*) FROM authme_authme")
        print(f"  authme_authme rows now: {cur.fetchone()[0]}")
        cur.execute("SELECT COUNT(*) FROM excellenteconomy_excellenteconomy_users")
        print(f"  economy rows now: {cur.fetchone()[0]}")


def _ms_to_dt(value):
    """Convert an epoch-millisecond value into a SQL Server datetime."""
    if value in (None, ""):
        return None
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    import datetime
    return datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=ms)


asyncio.run(main())
