"""Try selling an item against the live server.

Checks that selling pays the Coin back to the Minecraft server and that the
web wallet matches afterwards.
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


async def main() -> None:
    store.init()
    auth = await find_authme_user(PLAYER)
    eco = await find_economy_user(auth["username"])
    player = eco["name"]
    before = float(eco["money"])
    print(f"player : {player}")
    print(f"before : {before:,.2f}")

    held = store.list_inventory(player, "held")
    if not held:
        print("no items in the bag to sell")
        sys.exit(1)
    item = held[0]
    print(f"selling: {item['name']} ({item['value']:,} Coin)")

    cookie = mint({
        "user": auth["realname"],
        "login_name": auth["username"],
        "csrf": "x",
    })

    async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
        r = await c.post("/api/inventory/sell", json={"ids": [item["id"]]},
                         cookies={"jv_session": cookie},
                         headers={"x-csrf": "x"})
        print(f"\nsell -> HTTP {r.status_code}")
        print("  ", r.text[:300])
        if r.status_code != 200:
            print("\nFAILED: the item could not be sold")
            sys.exit(1)

        body = r.json()
        amount = body["amount"]

        eco2 = await find_economy_user(auth["username"])
        after = float(eco2["money"])
        print(f"\namount : {amount:,}")
        print(f"after  : {after:,.2f}")
        print(f"delta  : {after - before:+,.2f}")

        ok = abs((after - before) - amount) < 1
        print(f"\n  [{'PASS' if ok else 'FAIL'}] server paid back exactly {amount:,}")

        ok2 = abs(body["balance"] - after) < 1
        print(f"  [{'PASS' if ok2 else 'FAIL'}] web balance {body['balance']:,} "
              f"matches the server {after:,.0f}")

        row = store.get_inventory_item(item["id"])
        ok3 = row["status"] == "sold"
        print(f"  [{'PASS' if ok3 else 'FAIL'}] the item is marked sold "
              f"(status={row['status']})")

        print("\nLIVE SELL CHECKS PASSED" if (ok and ok2 and ok3) else "\nCHECKS FAILED")


asyncio.run(main())
