"""Check that the wallet history reads correctly after live play."""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app import store  # noqa: E402
from app.pika import find_authme_user  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

BASE = "http://127.0.0.1:8099"
PLAYER = os.getenv("LIVE_TEST_PLAYER", "hhh21")


async def main() -> None:
    store.init()
    auth = await find_authme_user(PLAYER)
    cookie = mint({
        "user": auth["realname"],
        "login_name": auth["username"],
        "csrf": "x",
    })

    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        r = await c.get("/vi", cookies={"jv_session": cookie})
        body = r.text

        print("=== wallet transactions (newest first) ===")
        for row in store.recent_tx(auth["realname"], 12):
            print(f"  {row['kind']:12} {row['amount']:>10,}  {row.get('note', '')}")

        labels = re.findall(r"<td>([^<]+)</td>", body)
        print("\n=== labels on the page ===")
        print("  ", labels)

        kinds = {row["kind"] for row in store.recent_tx(auth["realname"], 12)}
        print("\nkinds present:", kinds)

        # the sync label may appear, but the real actions must be there too
        has_open = "Mở rương" in labels
        has_sell = "Bán đồ" in labels
        print(f"  [{'PASS' if has_open else 'FAIL'}] 'Mở rương' shows in the history")
        print(f"  [{'PASS' if has_sell else 'FAIL'}] 'Bán đồ' shows in the history")

        # the generic sync label should not dominate the history
        sync_count = labels.count("Đồng bộ PikaMC")
        total = len(labels)
        print(f"  sync entries: {sync_count}/{total}")
        print(f"  [{'PASS' if sync_count < total else 'FAIL'}] the history is not all sync rows")


asyncio.run(main())
