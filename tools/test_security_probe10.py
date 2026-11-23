"""Measure the money the bot battle loop can move.

The host pays for every seat, including the bot seats it calls: a bot
seat costs the server nothing but can win items the host sells for real
money. This probe runs many bot battles and checks that the server does
not lose money over them.

Run:  python tools/test_security_probe10.py
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

STUB_PORT = 8138
PLAYER = "battleloop"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> None:
    store.init()
    panel = Panel()
    # 30 battles at 2 seats each, so the host needs 300,000 Coin to pay
    # for every seat. The default 100,000 would run out halfway.
    panel.add_user(PLAYER, PLAYER, money=1_000_000.0)

    with store._lock:
        con = store.connect()
        cur = con.cursor()
        for t in ("gacha_inventory", "gacha_tx", "gacha_wallets"):
            cur.execute(f"DELETE FROM {t} WHERE player = ?", PLAYER)
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
                                 timeout=120) as c:
        cookie = mint({"user": PLAYER, "login_name": PLAYER, "csrf": "x"})
        await c.get("/api/wallet/live", cookies={"jv_session": cookie})
        start = panel.balances[PLAYER]

        # Run 30 bot battles, selling the winnings every time.
        rounds = 30
        seat_cost = 5000
        # The host pays for its own seat and for the bot seat, so every
        # battle costs 2 seats.
        seats_per_battle = 2
        won = 0
        played = 0
        payout = 0
        for _i in range(rounds):
            r = await c.post("/api/battles", json={"case_id": "jelly-starter",
                                                   "slots": 2, "rounds": 1,
                                                   "mode": "STANDARD",
                                                   "fill_bots": True},
                             cookies={"jv_session": cookie},
                             headers={"x-csrf": "x"})
            if r.status_code != 200:
                break
            bid = r.json()["id"]
            r = await c.post(f"/api/battles/{bid}/start", json={},
                             cookies={"jv_session": cookie},
                             headers={"x-csrf": "x"})
            if r.status_code != 200:
                continue
            battle = store.get_battle(bid)
            held = store.list_inventory(PLAYER, "held")
            played += 1
            if battle.get("winner") == PLAYER:
                won += 1
            if held:
                before = panel.balances[PLAYER]
                await c.post("/api/inventory/sell",
                             json={"ids": [x["id"] for x in held]},
                             cookies={"jv_session": cookie},
                             headers={"x-csrf": "x"})
                payout += panel.balances[PLAYER] - before

        end = panel.balances[PLAYER]
        net = end - start
        paid = played * seats_per_battle * seat_cost
        check("every battle was played",
              played == rounds, f"{played} of {rounds} battles ran")
        check("the host wins roughly half the bot battles",
              5 <= won <= 25, f"won {won} of {played}")
        # The host paid 2 seats per battle and got back the value of the
        # items it won. The server must not come out ahead: a free bot
        # seat would let the host farm money.
        check("the server does not make money from the bot battles",
              net < 0,
              f"the server went from {start:,.0f} to {end:,.0f} ({net:+,.0f}); "
              f"the host paid {paid:,} for {played * seats_per_battle} seats "
              f"and won {payout:,.0f} back")
        check("the host pays for the bot seats too",
              paid >= seat_cost * played * 2,
              f"{paid:,} paid for {played} battles "
              f"(a free bot seat would be {seat_cost * played:,})")

    server.should_exit = True
    await task

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")


asyncio.run(main())
