"""Verify the web wallet always follows the server, even when it drifts.

The local ledger is deliberately corrupted (as if it went stale), then a
normal page load has to pull the server balance back.
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app import store  # noqa: E402
from app.pika import find_authme_user, find_economy_user  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

BASE = "http://127.0.0.1:8099"
PLAYER = "hhh21"


async def main() -> None:
    store.init()
    auth = await find_authme_user(PLAYER)
    eco = await find_economy_user(auth["username"])
    live = float(eco["money"])
    player = eco["name"]

    cookie = mint({
        "user": auth["realname"],
        "login_name": auth["username"],
        "csrf": "x",
    })

    # 1. corrupt the local ledger
    store.set_balance(player, 1, "sync", "test drift")
    print(f"  ledger corrupted -> {store.get_balance(player)}")
    assert store.get_balance(player) == 1

    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        # 2. a normal page load must repair it
        r = await c.get("/gacha", cookies={"jv_session": cookie})
        # The chip markup carries a title attribute, so the match is made
        # on the class and the number, not on the whole tag.
        chip = re.search(r'class="coin-chip".*?<span>([^<]*?) Coin', r.text, re.S)
        shown = chip.group(1).strip() if chip else "?"
        expected = f"{int(live):,}".replace(",", ".")
        print(f"  header chip after load -> {shown} (expected {expected})")
        assert shown == expected, f"ledger did NOT follow the server: {shown} != {expected}"

        # 3. the stored ledger must match too
        stored = store.get_balance(player)
        print(f"  ledger after load -> {stored} (server {live})")
        assert abs(stored - live) < 1, "stored ledger still stale"

    print("\nAUTO-SYNC CHECK PASSED")


asyncio.run(main())
