"""Probe: a wrong count must never touch the player's Coin.

`open_case` charges the server first and rolls after. If the count is
validated only after the payment, the player's Coin is taken and given
back for every bad request — noisy in the ledger and risky if the refund
fails.
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

STUB_PORT = 8152
PLAYER = "badcount"

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
                                 timeout=60) as c:
        cookie = mint({"user": PLAYER, "login_name": PLAYER, "csrf": "x"})
        store.ensure_wallet(PLAYER, seed=100000)
        panel.balances[PLAYER] = 100000.0

        before = panel.balances[PLAYER]
        for count in (99, 0, -1, 6, 1000):
            r = await c.post("/api/case/jelly-starter/open", json={"count": count},
                             cookies={"jv_session": cookie}, headers={"x-csrf": "x"})
            check(f"count={count} is refused",
                  r.status_code == 400, f"http={r.status_code}")
        after = panel.balances[PLAYER]
        check("a refused count never touches the Coin",
              after == before, f"server={after} before={before}")

        rows = store.recent_tx(PLAYER, 20)
        money_rows = [r for r in rows if r.get("kind") in ("open", "refund")]
        check("a refused count leaves no money row in the ledger",
              not money_rows, f"rows={[(r.get('kind'), r.get('amount')) for r in money_rows]}")

        held = store.list_inventory(PLAYER, "held")
        check("a refused count hands out no item", len(held) == 0,
              f"held items={len(held)}")

        # A good count still works.
        r = await c.post("/api/case/jelly-starter/open", json={"count": 2},
                         cookies={"jv_session": cookie}, headers={"x-csrf": "x"})
        check("a valid count still works", r.status_code == 200,
              f"http={r.status_code} {r.text[:120]}")
        check("a valid count takes the Coin",
              panel.balances[PLAYER] == before - 10000,
              f"server={panel.balances[PLAYER]}")

    server.should_exit = True
    await task

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")
    sys.exit(1 if failed else 0)


asyncio.run(main())
