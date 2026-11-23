"""Probe the confirmed payout and payment findings.

Run:  python tools/test_security_probe2.py
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

STUB_PORT = 8132

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> None:
    store.init()
    panel = Panel()
    panel.add_user("alice", "Alice")

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
                                 timeout=60) as c:
        cookie = mint({"user": "Alice", "login_name": "alice", "csrf": "x"})

        # Give Alice one item worth 500.
        store.ensure_wallet("Alice", seed=100000)
        item = {"id": "probe", "name": "Probe", "rarity": "common", "coin": 500,
                "image": "", "color": "#fff"}
        inv_id = store.add_inventory("Alice", item, "probe")
        store.set_balance("Alice", 100000, "sync", "probe setup")

        # --- 1. sell the SAME item twice, one after the other ---
        before = panel.balances.get("Alice", 0.0)
        r1 = await c.post("/api/inventory/sell", json={"ids": [inv_id]},
                          cookies={"jv_session": cookie}, headers={"x-csrf": "x"})
        r2 = await c.post("/api/inventory/sell", json={"ids": [inv_id]},
                          cookies={"jv_session": cookie}, headers={"x-csrf": "x"})
        gained = panel.balances.get("Alice", 0.0) - before
        check("selling the same item twice is refused the second time",
              r2.status_code == 400,
              f"first={r1.status_code} second={r2.status_code} body={r2.text[:120]}")
        check("the item is paid out only once",
              gained == 500, f"the server gained {gained} for an item worth 500")

        # --- 2. two concurrent sells of the same item ---
        store.add_inventory("Alice", item, "probe")
        held = store.list_inventory("Alice", "held")
        inv2 = held[0]["id"]
        # The database is shared between the suites, so the item may be an
        # older one with a different value. Use its real value.
        value2 = int(held[0]["value"])
        before = panel.balances.get("Alice", 0.0)
        reps = await asyncio.gather(
            c.post("/api/inventory/sell", json={"ids": [inv2]},
                   cookies={"jv_session": cookie}, headers={"x-csrf": "x"}),
            c.post("/api/inventory/sell", json={"ids": [inv2]},
                   cookies={"jv_session": cookie}, headers={"x-csrf": "x"}),
            return_exceptions=True)
        gained = panel.balances.get("Alice", 0.0) - before
        ok_count = sum(1 for r in reps if not isinstance(r, Exception)
                       and r.status_code == 200)
        check("two concurrent sells of one item pay out once",
              gained <= value2,
              f"the server gained {gained} for an item worth {value2}, "
              f"{ok_count} replies were 200")

        # --- 3. a battle seat is joined before the server is paid ---
        #     If the console call fails, the seat stays and the money is gone.
        print("\n[server failure path]")
        panel.add_user("broke", "Broke", money=1000000)
        broke_cookie = mint({"user": "Broke", "login_name": "broke", "csrf": "x"})
        store.ensure_wallet("Broke", seed=1000000)

        # Make the console endpoint refuse the payment.
        original_send = pika_mod.send_command

        async def failing_send(command: str) -> None:
            raise __import__("fastapi").HTTPException(status_code=503,
                                                      detail="console down")

        pika_mod.send_command = failing_send
        main_mod.send_command = failing_send
        try:
            r = await c.post("/api/battles", json={"case_id": "jelly-starter",
                                                   "slots": 2, "rounds": 1,
                                                   "mode": "STANDARD"},
                             cookies={"jv_session": broke_cookie},
                             headers={"x-csrf": "x"})
            check("a failed server payment is reported to the player",
                  r.status_code == 503, f"http={r.status_code}")
            battles = store.list_battles()["open"]
            mine = [b for b in battles if b["host"] == "Broke"]
            check("no battle is left behind after a failed payment",
                  not mine, f"battles hosted by Broke={len(mine)}")
            rows = store.recent_tx("Broke", 20)
            debits = [t for t in rows if t["kind"] == "battle_pay" and t["amount"] < 0]
            refunds = [t for t in rows if t["kind"] == "refund" and t["amount"] > 0]
            check("the local wallet is refunded when the server refuses",
                  len(refunds) >= len(debits),
                  f"battle_pay debits={len(debits)} refunds={len(refunds)}")
            # The balance is what matters: it must be back where it started.
            check("the balance is unchanged after a failed payment",
                  store.get_balance("Broke") == 1000000,
                  f"balance={store.get_balance('Broke')} (started at 1000000)")
        finally:
            pika_mod.send_command = original_send
            main_mod.send_command = original_send

        # --- 4. joining a battle twice ---
        r1 = await c.post("/api/battles", json={"case_id": "jelly-starter",
                                                "slots": 2, "rounds": 1,
                                                "mode": "STANDARD"},
                          cookies={"jv_session": cookie}, headers={"x-csrf": "x"})
        if r1.status_code == 200:
            bid = r1.json()["id"]
            r2 = await c.post(f"/api/battles/{bid}/join", json={},
                              cookies={"jv_session": cookie},
                              headers={"x-csrf": "x"})
            check("the host cannot take a second seat in the same battle",
                  r2.status_code == 400, f"http={r2.status_code} {r2.text[:100]}")
        else:
            check("the host cannot take a second seat in the same battle", False,
                  f"battle creation failed: {r1.status_code} {r1.text[:120]}")

    server.should_exit = True
    await task

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")


asyncio.run(main())
