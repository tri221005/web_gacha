"""Isolate the double-sell root cause.

Run:  python tools/test_security_probe9.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import game, store  # noqa: E402

PLAYER = "doubletester"
ITEM = {"id": "x", "name": "X", "rarity": "common", "coin": 500,
        "image": "", "color": "#fff"}

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> None:
    store.init()
    with store._lock:
        con = store.connect()
        cur = con.cursor()
        for t in ("gacha_inventory", "gacha_tx", "gacha_wallets"):
            cur.execute(f"DELETE FROM {t} WHERE player = ?", PLAYER)
        con.commit()

    store.ensure_wallet(PLAYER, seed=100000)
    inv_id = store.add_inventory(PLAYER, ITEM, "probe")

    # 1. The pending state is accepted as sellable.
    game.sell_items(PLAYER, [inv_id], commit=False)
    row = store.get_inventory_item(inv_id)
    check("the item is marked as pending after the first sell",
          row["status"] == "selling", f"status={row['status']}")

    try:
        game.sell_items(PLAYER, [inv_id], commit=False)
        check("a pending item cannot be sold a second time", False,
              "the second sell was accepted")
    except game.GameError as exc:
        check("a pending item cannot be sold a second time", True, str(exc.message))

    # 2. Two threads reading the same item at the same time.
    import threading
    store.ensure_wallet(PLAYER, seed=100000)
    inv2 = store.add_inventory(PLAYER, ITEM, "probe")
    accepted: list[str] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        try:
            game.sell_items(PLAYER, [inv2], commit=False)
            accepted.append("ok")
        except game.GameError:
            accepted.append("refused")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("two threads cannot both sell the same item",
          accepted.count("ok") == 1,
          f"accepted={accepted}")

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")


asyncio.run(main())
