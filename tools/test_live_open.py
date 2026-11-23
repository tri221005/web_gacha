"""Try a real case opening against the live server.

Uses a player with a known balance, opens one case and checks that:
  - the server balance dropped by exactly the case cost
  - the web wallet matches the server afterwards
  - the drop landed in the bag
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app import store  # noqa: E402
from app.pika import find_authme_user, find_economy_user  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

BASE = "http://127.0.0.1:8099"
PLAYER = os.getenv("LIVE_TEST_PLAYER", "hhh21")
CASE = os.getenv("LIVE_TEST_CASE", "jelly-starter")


async def main() -> None:
    store.init()
    auth = await find_authme_user(PLAYER)
    if auth is None:
        print(f"player {PLAYER} not in AuthMe")
        sys.exit(1)
    eco = await find_economy_user(auth["username"])
    player = eco["name"]
    before = float(eco["money"])
    print(f"player : {player}")
    print(f"before : {before:,.2f}")

    cookie = mint({
        "user": auth["realname"],
        "login_name": auth["username"],
        "csrf": "x",
    })

    async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
        r = await c.post(f"/api/case/{CASE}/open", json={"count": 1},
                         cookies={"jv_session": cookie},
                         headers={"x-csrf": "x"})
        print(f"\nopen case -> HTTP {r.status_code}")
        print("  ", r.text[:300])
        if r.status_code != 200:
            print("\nFAILED: the case could not be opened")
            sys.exit(1)

        body = r.json()
        cost = body["total_cost"]
        print(f"\ncost   : {cost:,}")

        # read the server balance back
        eco2 = await find_economy_user(auth["username"])
        after = float(eco2["money"])
        print(f"after  : {after:,.2f}")
        print(f"delta  : {after - before:+,.2f}")

        ok = abs((after - before) + cost) < 1
        print(f"\n  [{'PASS' if ok else 'FAIL'}] server charged exactly {cost:,}")

        ok2 = abs(body["balance"] - after) < 1
        print(f"  [{'PASS' if ok2 else 'FAIL'}] web balance {body['balance']:,} "
              f"matches the server {after:,.0f}")

        inv = store.get_inventory_item(body["openings"][0]["inventory_id"])
        ok3 = inv is not None and inv["status"] == "held" and inv["player"] == player
        print(f"  [{'PASS' if ok3 else 'FAIL'}] the drop is in {player}'s bag "
              f"({inv['name'] if inv else '?'})")

        print("\nLIVE CASE OPEN CHECKS PASSED" if (ok and ok2 and ok3) else "\nCHECKS FAILED")


asyncio.run(main())
