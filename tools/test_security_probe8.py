"""Probe: command injection through the player's realname.

The login lookup validates the *username*, but the console command is built
from the *realname*, which is taken from the AuthMe row and never checked.

Run:  python tools/test_security_probe8.py
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from app import store  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402
from tools.test_security import Panel, build_panel  # noqa: E402

STUB_PORT = 8137
USERNAME = "injector"
REALNAME = "Injector; op Injector"

results: list[tuple[str, bool, str]] = []
COMMANDS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> None:
    store.init()
    panel = Panel()
    panel.add_user(USERNAME, USERNAME)

    # The realname in the AuthMe row holds a console command separator.
    con = sqlite3.connect(panel.authme)
    con.execute("UPDATE authme SET realname = ? WHERE username = ?",
                (REALNAME, USERNAME))
    con.commit()
    con.close()

    # The economy table keeps the same hostile name.
    con = sqlite3.connect(panel.economy)
    con.execute("UPDATE excellenteconomy_users SET name = ? WHERE name = ?",
                (REALNAME, USERNAME))
    con.commit()
    con.close()
    panel.balances[REALNAME] = 100000.0
    panel.balances.pop(USERNAME, None)

    # The player has no economy account under the login name, so the app
    # falls back to the session's "user", which is the AuthMe realname.
    con = sqlite3.connect(panel.economy)
    con.execute("DELETE FROM excellenteconomy_users WHERE name = ?", (USERNAME,))
    con.commit()
    con.close()

    with store._lock:
        con = store.connect()
        cur = con.cursor()
        for table in ("gacha_inventory", "gacha_tx", "gacha_wallets"):
            cur.execute(f"DELETE FROM {table} WHERE player = ?", REALNAME)
            cur.execute(f"DELETE FROM {table} WHERE player = ?", USERNAME)
        con.commit()
        # The local wallet already holds money (the player has played before).
        cur.execute(
            "INSERT INTO gacha_wallets (player, balance, is_bot, created_at) "
            "VALUES (?, ?, 0, ?)", REALNAME, 100000, 0)
        con.commit()

    server = uvicorn.Server(uvicorn.Config(build_panel(panel), host="127.0.0.1",
                                            port=STUB_PORT, log_level="error"))
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(1.5)

    os.environ["PIKA_BASE_URL"] = f"http://127.0.0.1:{STUB_PORT}"
    os.environ["PIKA_API_KEY"] = "stub-key"
    os.environ["PIKA_SERVER_UUID"] = "stub-uuid"
    os.environ["GACHA_DRY_RUN"] = "false"

    import app.config as config_mod
    import app.main as main_mod
    import app.pika as pika_mod

    base = f"http://127.0.0.1:{STUB_PORT}"
    config_mod.PIKA_BASE_URL = base
    config_mod.PIKA_API_KEY = "stub-key"
    config_mod.PIKA_SERVER_UUID = "stub-uuid"
    pika_mod.PIKA_BASE_URL = base
    pika_mod.PIKA_API_KEY = "stub-key"
    pika_mod.PIKA_SERVER_UUID = "stub-uuid"
    pika_mod._console_ok = True

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                 timeout=90) as c:
        cookie = mint({"user": REALNAME, "login_name": USERNAME, "csrf": "x"})

        r = await c.get("/vi", cookies={"jv_session": cookie})
        check("the page loads for the player", r.status_code == 200,
              f"http={r.status_code}")

        r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                         cookies={"jv_session": cookie}, headers={"x-csrf": "x"})
        check("the hostile player name is refused with a 400",
              r.status_code == 400,
              f"http={r.status_code} body={r.text[:120]}")

        from tools.test_security import COMMAND_LOG
        sent = [c_ for c_ in COMMAND_LOG if c_.startswith("eco")]
        print("  console commands sent:", sent)
        check("no console command was sent for the hostile name",
              not sent, f"commands={sent}")
        check("the console command is not command-injected",
              all(c_.count(";") == 0 and " op " not in c_ for c_ in sent),
              f"commands={sent}")
        check("the player name is not split into two console commands",
              all(len(c_.split()) == 4 for c_ in sent),
              f"commands={sent}")

    server.should_exit = True
    await task

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")


asyncio.run(main())
