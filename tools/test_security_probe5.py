"""Proof: a refused server charge still hands the player a sellable item.

The Minecraft console answers HTTP 200 even when the command itself fails
("player not found", "not enough money"). The app only looks at the HTTP
status, so it believes the money was taken and hands out the drop.

The stub below refuses `eco take` but accepts `eco give`, so the free item
can be sold for real money afterwards.

Run:  python tools/test_security_probe5.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app import store  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402
from tools.test_security import Panel  # noqa: E402

STUB_PORT = 8135
PLAYER = "refusedplayer"

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
        cur.execute("DELETE FROM gacha_inventory WHERE player = ?", PLAYER)
        cur.execute("DELETE FROM gacha_tx WHERE player = ?", PLAYER)
        cur.execute("DELETE FROM gacha_wallets WHERE player = ?", PLAYER)
        con.commit()

    # The panel answers HTTP 200 to everything. `eco take` changes nothing
    # (the console refused it), `eco give` works.
    app = FastAPI()

    @app.post("/api/client/servers/{uuid}/files/sqlite-query")
    async def sqlite_query(request: Request):
        body = await request.json()
        rows = panel._run(body.get("file", ""), body.get("query", ""))
        if not rows:
            return JSONResponse({"results": []})
        keys = list(rows[0])
        return JSONResponse({"results": [{
            "columns": [{"name": k} for k in keys],
            "rows": [[{"type": "text", "value": r.get(k)} for k in keys] for r in rows],
        }]})

    @app.post("/api/client/servers/{uuid}/command")
    async def command(request: Request):
        body = await request.json()
        parts = str(body.get("command", "")).split()
        if len(parts) == 4 and parts[0] == "eco" and parts[1] == "give":
            name, amount = parts[2], float(parts[3])
            panel.balances[name] = panel.balances.get(name, 0.0) + amount
            import sqlite3
            con = sqlite3.connect(panel.economy)
            con.execute("UPDATE excellenteconomy_users SET money = ? WHERE name = ?",
                        (panel.balances[name], name))
            con.commit()
            con.close()
        # `eco take` is refused: HTTP 200, no money moved.
        return JSONResponse({"ok": True})

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=STUB_PORT,
                                            log_level="error"))
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

        r = await c.get("/api/wallet/live", cookies={"jv_session": cookie})
        server_money = panel.balances[PLAYER]
        local_before = store.get_balance(PLAYER)
        check("the wallet mirrors the server before the case is opened",
              abs(local_before - server_money) < 1,
              f"local={local_before} server={server_money}")

        # Open the case. The console refuses to take the money.
        r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                         cookies={"jv_session": cookie}, headers={"x-csrf": "x"})
        check("the refused payment is reported to the player",
              r.status_code == 503, f"http={r.status_code}")
        held = store.list_inventory(PLAYER, "held")
        check("the player gets NO item when the server took no money",
              len(held) == 0, f"held items={len(held)}")
        check("the server balance is untouched after the refused case",
              panel.balances[PLAYER] == server_money,
              f"server={panel.balances[PLAYER]} before={server_money}")
        check("the local wallet is not debited for the refused case",
              store.get_balance(PLAYER) == local_before,
              f"local={store.get_balance(PLAYER)} before={local_before}")

        # There is nothing to sell, so the money-printing path is closed.
        print("\n[selling the unpaid item]")
        r = await c.post("/api/inventory/sell", json={"ids": [1]},
                         cookies={"jv_session": cookie}, headers={"x-csrf": "x"})
        check("there is no unpaid item to sell", r.status_code == 400,
              f"http={r.status_code} body={r.text[:120]}")
        check("the server paid nothing for the refused case",
              panel.balances[PLAYER] == server_money,
              f"server={panel.balances[PLAYER]} before={server_money}")

    server.should_exit = True
    await task

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")


asyncio.run(main())
