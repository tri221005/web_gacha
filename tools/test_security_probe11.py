"""Probe: the balance read fails halfway through a payment.

`pika_take` sends `eco take` and then reads the balance back. If that read
fails, the app cannot tell whether the money left the server. The safe
answer is "the payment failed" — never "it worked".

This probe makes the balance read fail on the second call only, so the
command did run but the answer is unknown.
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

STUB_PORT = 8151
PLAYER = "halfread"

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

        # --- the read fails right after the command ---
        real_balance = pika_mod.economy_balance
        calls = {"n": 0}

        async def flaky(player: str):
            calls["n"] += 1
            # The first read (before the command) works. Every read after
            # the command fails, so the outcome is unknown.
            if calls["n"] == 1:
                return await real_balance(player)
            raise httpx.ConnectError("the api went away")

        pika_mod.economy_balance = flaky
        main_mod.economy_balance = flaky

        before = panel.balances.get(PLAYER, 0.0)
        r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                         cookies={"jv_session": cookie}, headers={"x-csrf": "x"})
        after = panel.balances.get(PLAYER, 0.0)

        check("an unreadable balance is reported as a failure",
              r.status_code == 503, f"http={r.status_code}")
        check("the failure is a clean 503, not an unhandled crash",
              r.status_code == 503, f"http={r.status_code}")
        held = store.list_inventory(PLAYER, "held")
        check("no item is handed out when the payment is unknown",
              len(held) == 0, f"held items={len(held)}")
        check("the local wallet is not debited",
              store.get_balance(PLAYER) == 100000,
              f"local={store.get_balance(PLAYER)}")

        # The command did run on the server, so the Coin is gone. The app
        # must not have invented a refund, and it must not have handed out
        # a free item either.
        check("the server balance is what the command actually did",
              after == before - 5000,
              f"server={after} before={before} "
              f"(the command did run; the app could not read it back)")

        pika_mod.economy_balance = real_balance
        main_mod.economy_balance = real_balance

    server.should_exit = True
    await task

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")
    sys.exit(1 if failed else 0)


asyncio.run(main())
