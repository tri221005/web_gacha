"""End-to-end check of the realtime PikaMC sync.

Verifies that:
  1. the web wallet mirrors the live ExcellentEconomy balance
  2. the login identity matches the AuthMe row (username/realname)
  3. every page that shows a balance shows the live number
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app import game, store  # noqa: E402
from app.pika import find_authme_user, find_economy_user  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

BASE = "http://127.0.0.1:8099"
# The accounts that are actually used on the server. An account that has
# never signed in has no wallet, so the pages would show nothing and the
# test would report a failure that is not one.
PLAYERS = ("hhh21", "shsuzy")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(f"{name}: {detail}")


async def main() -> None:
    store.init()
    for name in PLAYERS:
        print(f"\n===== {name} =====")

        auth = await find_authme_user(name)
        eco = await find_economy_user(name)
        if auth is None or eco is None:
            check("authme + economy rows exist", False, f"auth={auth is not None} eco={eco is not None}")
            continue

        live_money = float(eco["money"])
        check("authme realname matches economy name",
              str(auth["realname"]).lower() == str(eco["name"]).lower(),
              f"realname={auth['realname']!r} eco.name={eco['name']!r}")

        # 1. sync the ledger directly
        game.sync_wallet(eco["name"], live_money)
        web_balance = store.get_balance(eco["name"])
        check("ledger mirrors live balance",
              abs(web_balance - live_money) < 1,
              f"web={web_balance} live={live_money}")

        # 2. the rendered pages must show the same number
        cookie = mint({
            "user": auth["realname"],
            "login_name": auth["username"],
            "csrf": "x",
        })
        async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
            r = await c.get("/vi", cookies={"jv_session": cookie})
            page_money = re.search(r'class="amount" id="balance">([^<]+)<', r.text)
            re.search(r'id="pika">([^<]+)<', r.text)
            shown = page_money.group(1).strip() if page_money else "?"
            expected_fmt = f"{int(live_money):,}".replace(",", ".")
            check("/vi shows the live balance", shown == expected_fmt,
                  f"shown={shown!r} expected={expected_fmt!r}")

            api = await c.get("/api/wallet/live", cookies={"jv_session": cookie})
            data = api.json()
            check("/api/wallet/live returns live pika",
                  abs(float(data["pika"]) - live_money) < 1,
                  f"pika={data['pika']} live={live_money}")
            check("/api/wallet/live balance == pika",
                  abs(float(data["balance"]) - float(data["pika"])) < 1,
                  f"balance={data['balance']} pika={data['pika']}")

            # 3. the header chip on every page
            for path in ("/gacha", "/inventory", "/bonus"):
                rr = await c.get(path, cookies={"jv_session": cookie})
                chip = re.search(r'class="coin-chip".*?<span>([^<]*?) Coin', rr.text, re.S)
                chip_txt = chip.group(1).strip() if chip else "?"
                check(f"header chip on {path}", chip_txt == expected_fmt,
                      f"chip={chip_txt!r} expected={expected_fmt!r}")

    print("\n" + "=" * 50)
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("ALL CHECKS PASSED")


asyncio.run(main())
