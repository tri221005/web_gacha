"""Verify the live money flow against a fake PikaMC panel.

The app runs in-process over ASGI, so the whole live path is exercised —
charge the server, mirror the balance, hand out the drop, sell it, pay the
server back — without touching the real hosting panel or a real player.
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
from tools.pika_stub import PLAYER, SERVER_BALANCE, build_stub  # noqa: E402

STUB_PORT = 8124


async def main() -> None:
    store.init()

    stub = build_stub()
    config = uvicorn.Config(stub, host="127.0.0.1", port=STUB_PORT, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(1.5)

    # Point the app at the stub and switch off dry-run.
    os.environ["PIKA_BASE_URL"] = f"http://127.0.0.1:{STUB_PORT}"
    os.environ["PIKA_API_KEY"] = "stub-key"
    os.environ["PIKA_SERVER_UUID"] = "stub-uuid"
    os.environ["GACHA_DRY_RUN"] = "false"

    import app.config as config_mod
    import app.main as main_mod
    import app.pika as pika_mod

    config_mod.PIKA_BASE_URL = f"http://127.0.0.1:{STUB_PORT}"
    config_mod.PIKA_API_KEY = "stub-key"
    config_mod.PIKA_SERVER_UUID = "stub-uuid"
    pika_mod.PIKA_BASE_URL = config_mod.PIKA_BASE_URL
    pika_mod.PIKA_API_KEY = config_mod.PIKA_API_KEY
    pika_mod.PIKA_SERVER_UUID = config_mod.PIKA_SERVER_UUID
    pika_mod._console_ok = True

    cookie = mint({"user": PLAYER, "login_name": PLAYER.lower(), "csrf": "x"})
    failures: list[str] = []

    # start from a clean ledger so the run is independent of previous ones
    with store._lock:
        con = store.connect()
        cur = con.cursor()
        cur.execute("DELETE FROM gacha_tx WHERE player = ?", PLAYER)
        cur.execute("DELETE FROM gacha_inventory WHERE player = ?", PLAYER)
        con.commit()

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{name}: {detail}")

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                 timeout=30) as c:
        # 1. the wallet mirrors the fake server balance
        r = await c.get("/api/wallet/live", cookies={"jv_session": cookie})
        data = r.json()
        check("wallet mirrors the server", abs(data["balance"] - 100000) < 1,
              f"balance={data.get('balance')} detail={data}")

        # 2. opening a case charges the server exactly once
        server_before = SERVER_BALANCE[PLAYER]
        r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                         cookies={"jv_session": cookie},
                         headers={"x-csrf": "x"})
        check("open case returns 200", r.status_code == 200, r.text[:200])
        if r.status_code == 200:
            body = r.json()
            check("server was charged once",
                  abs(SERVER_BALANCE[PLAYER] - (server_before - 5000)) < 1,
                  f"server={SERVER_BALANCE[PLAYER]} expected={server_before - 5000}")
            check("web balance matches the server",
                  abs(body["balance"] - SERVER_BALANCE[PLAYER]) < 1,
                  f"web={body['balance']} server={SERVER_BALANCE[PLAYER]}")
            inv_id = body["openings"][0]["inventory_id"]

            # 3. selling pays the server back
            server_before = SERVER_BALANCE[PLAYER]
            r = await c.post("/api/inventory/sell", json={"ids": [inv_id]},
                             cookies={"jv_session": cookie},
                             headers={"x-csrf": "x"})
            check("sell returns 200", r.status_code == 200, r.text[:200])
            if r.status_code == 200:
                sold = r.json()
                check("server was paid back",
                      SERVER_BALANCE[PLAYER] > server_before,
                      f"server={SERVER_BALANCE[PLAYER]} before={server_before}")
                check("web balance matches the server again",
                      abs(sold["balance"] - SERVER_BALANCE[PLAYER]) < 1,
                      f"web={sold['balance']} server={SERVER_BALANCE[PLAYER]}")

            # 4. the ledger must not have double-charged: only one "open"
            #    entry for this run, not one per attempt
            txs = store.recent_tx(PLAYER, 20)
            opens = [t for t in txs if t["kind"] == "open"]
            check("the wallet was not debited twice", len(opens) == 1,
                  f"open transactions={len(opens)}")

    server.should_exit = True
    await task

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("LIVE MONEY FLOW CHECKS PASSED")


asyncio.run(main())
