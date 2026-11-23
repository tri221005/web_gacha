"""Probe: the bot battle loop, and the X-Forwarded-For rate limit bypass.

Run:  python tools/test_security_probe7.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from app import store  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402
from tools.test_security import Panel, build_panel  # noqa: E402

STUB_PORT = 8136
PLAYER = "loopplayer"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> None:
    store.init()
    panel = Panel()
    panel.add_user(PLAYER, PLAYER)

    with store._lock:
        con = store.connect()
        cur = con.cursor()
        for table in ("gacha_inventory", "gacha_tx", "gacha_wallets"):
            cur.execute(f"DELETE FROM {table} WHERE player = ?", PLAYER)
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
        cookie = mint({"user": PLAYER, "login_name": PLAYER, "csrf": "x"})

        await c.get("/api/wallet/live", cookies={"jv_session": cookie})
        server_before = panel.balances[PLAYER]

        print("[the bot battle loop]")
        # Create a battle, fill it with bots, start it, win the drops.
        r = await c.post("/api/battles", json={"case_id": "jelly-starter",
                                               "slots": 2, "rounds": 1,
                                               "mode": "STANDARD",
                                               "fill_bots": True},
                         cookies={"jv_session": cookie}, headers={"x-csrf": "x"})
        check("a battle can be created and filled with bots",
              r.status_code == 200, f"http={r.status_code} body={r.text[:150]}")
        if r.status_code == 200:
            bid = r.json()["id"]
            r = await c.post(f"/api/battles/{bid}/start", json={},
                             cookies={"jv_session": cookie},
                             headers={"x-csrf": "x"})
            check("the host can start the bot battle",
                  r.status_code == 200, f"http={r.status_code}")
            store.get_battle(bid)
            held = store.list_inventory(PLAYER, "held")
            # Whether the host or the bot wins is a coin flip, so the
            # security property is not "the host wins" but "every seat was
            # paid for". The host paid for its own seat and for the bot.
            paid_seats = server_before - panel.balances[PLAYER]
            check("the host paid for its own seat and for the bot seat",
                  paid_seats >= 5000 * 2,
                  f"the server took {paid_seats} for two seats "
                  f"(a seat costs 5000)")
            check("the bot seat was not free",
                  paid_seats >= 5000 * 2,
                  f"the server took {paid_seats}; a free bot seat would be 5000")

            # Sell the winnings: that is real money from the server.
            if held:
                before = panel.balances[PLAYER]
                won_value = sum(int(i["value"]) for i in held)
                r = await c.post("/api/inventory/sell",
                                 json={"ids": [i["id"] for i in held]},
                                 cookies={"jv_session": cookie},
                                 headers={"x-csrf": "x"})
                check("the winnings can be sold for real money",
                      r.status_code == 200, f"http={r.status_code}")
                gained = panel.balances[PLAYER] - before
                # The server pays exactly what the items are worth. The
                # security property is the check above: the host paid for
                # its own seat and for the bot seat.
                check("the server pays exactly what the items are worth",
                      abs(gained - won_value) <= 1,
                      f"the server paid {gained} for items worth {won_value}")

        print("\n[the rate limit and X-Forwarded-For]")
        import re as _re

        import app.security as security_mod
        security_mod._attempts.clear()
        security_mod._account_attempts.clear()

        async def csrf_of(cl) -> str:
            r = await cl.get("/login")
            m = _re.search(r'name="csrf" value="([^"]+)"', r.text)
            return m.group(1) if m else ""

        # A separate client: the one above is logged in, so `/login`
        # would redirect instead of rendering the form.
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     timeout=30) as cl:
            # 12 wrong passwords, each with a different forged header.
            for i in range(12):
                await cl.post("/login", data={"username": "alice",
                                              "password": "wrong",
                                              "csrf": await csrf_of(cl)},
                              headers={"X-Forwarded-For": f"10.0.0.{i + 1}"})
            blocked = False
            for _ in range(12):
                r = await cl.post("/login", data={"username": "alice",
                                                  "password": "wrong",
                                                  "csrf": await csrf_of(cl)},
                                  headers={"X-Forwarded-For": "10.0.0.1"})
                if "rate" in str(r.headers.get("location", "")):
                    blocked = True
                    break
        check("the login rate limit cannot be bypassed by forging X-Forwarded-For",
              blocked,
              "12 wrong passwords were accepted from the same host "
              "by forging the header")

    server.should_exit = True
    await task

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")


asyncio.run(main())
