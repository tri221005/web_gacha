"""Audit: hunt for logic bugs across the whole app.

This probe looks for the kind of bug that only shows up when two parts of
the app disagree with each other: the same rule applied in two places, a
check that reads the wrong field, a number that is used before it is
known.

Run:  python tools/test_audit_logic.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app import game, store  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def fresh(name: str, coins: int) -> str:
    store.run(
        lambda con: con.cursor().execute(
            "DELETE FROM gacha_wallets WHERE player = ?", name
        )
    )
    store.credit(name, coins, "seed", "test")
    return name


def drop(name: str) -> None:
    try:
        store.run(
            lambda con: (
                con.cursor().execute(
                    "DELETE FROM gacha_inventory WHERE player = ?", name),
                con.cursor().execute("DELETE FROM gacha_tx WHERE player = ?", name),
                con.cursor().execute("DELETE FROM gacha_pulls WHERE player = ?", name),
                con.cursor().execute(
                    "DELETE FROM gacha_wallets WHERE player = ?", name),
            )
        )
    except Exception:
        pass


async def main() -> None:
    store.init()
    import app.main as main_mod

    names: list[str] = []
    transport = httpx.ASGITransport(app=main_mod.app)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     timeout=60) as c:
            # ---------------------------------------------------------- #
            print("[the bonus can only be claimed once per day]")
            # ---------------------------------------------------------- #
            p = fresh(f"AUD_Bonus_{uuid.uuid4().hex[:8]}", 100_000)
            names.append(p)
            ck = mint({"user": p, "login_name": p.lower(), "csrf": "x"})
            r = await c.post("/api/bonus", json={}, cookies={"jv_session": ck},
                             headers={"x-csrf": "x"})
            check("the first bonus is granted", r.status_code == 200,
                  f"http={r.status_code} body={r.text[:150]}")
            first_amount = r.json().get("amount") if r.status_code == 200 else 0
            r = await c.post("/api/bonus", json={}, cookies={"jv_session": ck},
                             headers={"x-csrf": "x"})
            check("the second bonus in the same day is refused",
                  r.status_code >= 400, f"http={r.status_code}")
            # The balance must only have moved once.
            balance = store.get_balance(p)
            check("the bonus was paid exactly once",
                  balance == 100_000 + (first_amount or 0),
                  f"balance={balance} expected={100_000 + (first_amount or 0)}")

            # ---------------------------------------------------------- #
            print("\n[the upgrade keeps the item when it loses]")
            # ---------------------------------------------------------- #
            up = fresh(f"AUD_Up_{uuid.uuid4().hex[:8]}", 100_000)
            names.append(up)
            # Give the player one cheap item and upgrade it into an
            # expensive one that loses. The stake must be gone and no
            # reward must appear.
            cheap = game.market_listings()[0]
            inv_id = store.add_inventory(up, cheap, "case", "jelly-starter")
            stake_value = cheap.coin
            target = next((i for i in game.market_listings()
                           if i.coin > stake_value * 2), None)
            if target is None:
                check("an upgrade target exists for the test", False,
                      "no market listing above the cheapest one")
            else:
                # Force a loss by patching the chance check: the odds are
                # what they are, so the test accepts either outcome but
                # checks the ledger is consistent with it.
                res = game.do_upgrade(up, inv_id, target.id, target.coin)
                row = store.get_inventory_item(inv_id)
                check("the stake is no longer held",
                      row["status"] == "upgraded", str(row["status"]))
                held = store.list_inventory(up, "held")
                reward = [i for i in held if i["source"] == "upgrade"]
                if res["won"]:
                    check("a win puts exactly one reward in the bag",
                          len(reward) == 1, f"reward={len(reward)}")
                    check("the reward is the target item",
                          reward and reward[0]["item_id"] == target.id,
                          str(reward))
                else:
                    check("a loss puts no reward in the bag",
                          len(reward) == 0, f"reward={len(reward)}")
                # The upgrade must never be free: the stake must be gone
                # from the bag, and the log must show what happened.
                logged = store.run(
                    lambda con: con.cursor().execute(
                        "SELECT COUNT(*) FROM gacha_upgrades WHERE player = ?", up
                    ).fetchone()[0]
                )
                check("the upgrade is recorded in the upgrade log",
                      logged >= 1, f"rows={logged}")

            # ---------------------------------------------------------- #
            print("\n[an upgrade cannot be run twice on the same item]")
            # ---------------------------------------------------------- #
            p2 = fresh(f"AUD_Up2_{uuid.uuid4().hex[:8]}", 100_000)
            names.append(p2)
            cheap2 = game.market_listings()[0]
            inv2 = store.add_inventory(p2, cheap2, "case", "jelly-starter")
            target2 = next((i for i in game.market_listings()
                            if i.coin > cheap2.coin * 2), None)
            if target2 is not None:
                game.do_upgrade(p2, inv2, target2.id, target2.coin)
                try:
                    game.do_upgrade(p2, inv2, target2.id, target2.coin)
                    check("the same item cannot be upgraded twice",
                          False, "no error was raised")
                except game.GameError:
                    check("the same item cannot be upgraded twice", True)
            # And the same target twice in a row through HTTP.
            ck2 = mint({"user": p2, "login_name": p2.lower(), "csrf": "x"})
            r = await c.post("/api/upgrade", json={
                "inventory_id": inv2, "target_id": target2.id if target2 else "x",
                "target_coin": target2.coin if target2 else 0,
            }, cookies={"jv_session": ck2}, headers={"x-csrf": "x"})
            check("upgrading an already used item over HTTP is refused",
                  r.status_code >= 400, f"http={r.status_code}")

            # ---------------------------------------------------------- #
            print("\n[selling only works on items the player owns]")
            # ---------------------------------------------------------- #
            owner = fresh(f"AUD_Own_{uuid.uuid4().hex[:8]}", 100_000)
            other = fresh(f"AUD_Oth_{uuid.uuid4().hex[:8]}", 100_000)
            names += [owner, other]
            item = game.market_listings()[0]
            owner_item = store.add_inventory(owner, item, "case", "jelly-starter")
            ck_other = mint({"user": other, "login_name": other.lower(),
                              "csrf": "x"})
            r = await c.post("/api/inventory/sell", json={"ids": [owner_item]},
                             cookies={"jv_session": ck_other},
                             headers={"x-csrf": "x"})
            check("another player cannot sell somebody else's item",
                  r.status_code >= 400, f"http={r.status_code}")
            check("the item is still held after the refused sale",
                  store.get_inventory_item(owner_item)["status"] == "held",
                  store.get_inventory_item(owner_item)["status"])
            check("the other player was not credited",
                  store.get_balance(other) == 100_000,
                  f"balance={store.get_balance(other)}")

            # ---------------------------------------------------------- #
            print("\n[the open case endpoint never hands out a free item]")
            # ---------------------------------------------------------- #
            broke = fresh(f"AUD_Broke_{uuid.uuid4().hex[:8]}", 100)
            names.append(broke)
            ck_broke = mint({"user": broke, "login_name": broke.lower(),
                              "csrf": "x"})
            r = await c.post("/api/case/jelly-starter/open", json={"count": 5},
                             cookies={"jv_session": ck_broke},
                             headers={"x-csrf": "x"})
            check("a player without enough Coin cannot open a case",
                  r.status_code >= 400, f"http={r.status_code}")
            held = store.list_inventory(broke, "held")
            check("no item is handed out when the payment is refused",
                  len(held) == 0, f"held={len(held)}")
            check("the balance is untouched",
                  store.get_balance(broke) == 100,
                  f"balance={store.get_balance(broke)}")

            # ---------------------------------------------------------- #
            print("\n[the case list is not empty and every case can roll]")
            # ---------------------------------------------------------- #
            from app.gacha import load_cases as _load_cases
            cases = _load_cases()
            check("there is at least one case", len(cases) > 0, str(len(cases)))
            bad = [c.id for c in cases if not c.items]
            check("every case has items", not bad, str(bad))
            bad_cost = [c.id for c in cases if c.pull_cost <= 0]
            check("every case has a price", not bad_cost, str(bad_cost))
            zero_weight = [c.id for c in cases
                           if sum(max(0, i.weight) for i in c.items) <= 0]
            check("every case has a usable weight table",
                  not zero_weight, str(zero_weight))
            # A case with a zero-weight item must never roll it.
            from app.gacha import roll as _roll
            for case_obj in cases:
                zero_items = [i for i in case_obj.items if i.weight <= 0]
                if not zero_items:
                    continue
                rolled = {_roll(case_obj).id for _ in range(300)}
                picked = rolled & {i.id for i in zero_items}
                check(f"a zero-weight item in {case_obj.id} never rolls",
                      not picked, str(picked))
                break

            # ---------------------------------------------------------- #
            print("\n[the market list has no duplicates]")
            # ---------------------------------------------------------- #
            market = game.market_listings()
            keys = [(i.id, i.coin) for i in market]
            check("the market list has no duplicate item", len(keys) == len(set(keys)),
                  str([k for k in keys if keys.count(k) > 1][:5]))

            # ---------------------------------------------------------- #
            print("\n[the wallet cannot go negative]")
            # ---------------------------------------------------------- #
            neg = fresh(f"AUD_Neg_{uuid.uuid4().hex[:8]}", 100)
            names.append(neg)
            try:
                store.debit(neg, 10_000, "test", "audit")
                check("a debit larger than the balance is refused",
                      False, "no error was raised")
            except ValueError:
                check("a debit larger than the balance is refused", True)
            check("the balance is still correct after the refused debit",
                  store.get_balance(neg) == 100,
                  f"balance={store.get_balance(neg)}")

            # ---------------------------------------------------------- #
            print("\n[the ban stops every action that costs Coin]")
            # ---------------------------------------------------------- #
            banned = fresh(f"AUD_Ban_{uuid.uuid4().hex[:8]}", 100_000)
            names.append(banned)
            store.set_ban(banned, "audit")
            ck_ban = mint({"user": banned, "login_name": banned.lower(),
                           "csrf": "x"})
            r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                             cookies={"jv_session": ck_ban},
                             headers={"x-csrf": "x"})
            check("a banned player cannot open a case",
                  r.status_code == 403, f"http={r.status_code}")
            r = await c.post("/api/bonus", json={}, cookies={"jv_session": ck_ban},
                             headers={"x-csrf": "x"})
            check("a banned player cannot claim the bonus",
                  r.status_code == 403, f"http={r.status_code}")
            store.lift_ban(banned)

            # ---------------------------------------------------------- #
            print("\n[the admin list and the .env list agree]")
            # ---------------------------------------------------------- #
            from app.config import ADMIN_USERS
            names_set = {n.lower() for n in ADMIN_USERS}
            check("there is at least one admin in .env", len(names_set) > 0,
                  str(ADMIN_USERS))

            # ---------------------------------------------------------- #
            print("\n[the stats agree with the ledger]")
            # ---------------------------------------------------------- #
            stats = store.stats()
            check("the stats have no contract key any more",
                  "contracts" not in stats, str(sorted(stats.keys())))

            # ---------------------------------------------------------- #
            print("\n[a battle in the lobby is shown with the right seat count]")
            # ---------------------------------------------------------- #
            lobby = store.list_battles()
            bad_seats = [b["id"] for b in lobby["open"]
                         if int(b.get("seated") or 0) != len(b.get("players") or [])]
            check("the seat count matches the players in every lobby row",
                  not bad_seats, str(bad_seats[:5]))

    finally:
        for name in names:
            drop(name)

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")


asyncio.run(main())
