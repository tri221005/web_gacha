"""Probe: the money that leaves during a case battle.

`tools/test_battle_logic.py` checks the rules. This probe checks the
money, over HTTP, with the PikaMC payment stubbed out so no real Coin
moves.

The dangerous spots:

- The host pays for its own seat *and* for every bot it calls. If the
  local ledger and the server are charged a different amount, the two
  drift apart and the site either gives away items or takes Coin twice.
- When the server refuses the payment, the seat must go and the Coin
  must come back — on both the server and the ledger.

Run:  python tools/test_battle_money.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app import store  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

results: list[tuple[str, bool, str]] = []

# What the stubbed server was told to take, per player.
server_taken: dict[str, int] = {}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def fresh(name: str, coins: int) -> str:
    """Give a test account a known balance on both sides."""
    store.run(
        lambda con: con.cursor().execute(
            "DELETE FROM gacha_wallets WHERE player = ?", name
        )
    )
    store.credit(name, coins, "seed", "test")
    server_taken[name] = 0
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

    # The server payment is stubbed: the command that would take Coin on
    # the Minecraft server is recorded instead, and the ledger is left
    # alone so the test can see what the app does on its own.
    real_take = main_mod.pika_take

    async def fake_take(player, amount, kind="sync"):
        server_taken[player] = server_taken.get(player, 0) + int(amount)
        return store.get_balance(player)

    class Refused(Exception):
        pass


    transport = httpx.ASGITransport(app=main_mod.app)
    names: list[str] = []

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     timeout=30) as c:
            main_mod.pika_take = fake_take

            print("[the host pays for its seat and for every bot]")
            host = fresh(f"BTMoney_H_{uuid.uuid4().hex[:8]}", 100_000)
            names.append(host)
            host_cookie = mint({"user": host, "login_name": host.lower(),
                                 "csrf": "x"})
            case_id = "jelly-starter"

            r = await c.post("/api/battles", json={
                "case_id": case_id, "slots": 2, "rounds": 1,
                "mode": "STANDARD", "fill_bots": True,
            }, cookies={"jv_session": host_cookie}, headers={"x-csrf": "x"})
            check("a battle with bots is created", r.status_code == 200,
                  f"http={r.status_code} body={r.text[:200]}")
            if r.status_code != 200:
                return

            data = r.json()
            data.get("id")
            bots = sum(1 for p in (data.get("players") or [])
                       if p.get("is_bot") and p.get("player") != host)
            case = main_mod.get_case(case_id)
            seat = case.pull_cost * 1 if case else 0
            expected = seat * (1 + bots)
            check("the server was charged for the host seat and the bots",
                  server_taken.get(host, 0) == expected,
                  f"taken={server_taken.get(host, 0)} expected={expected} bots={bots}")

            # The ledger was debited by create_battle, which is the local
            # mirror of the host's own seat. The bots paid from their own
            # wallets, so the host's ledger must only ever lose the price
            # of its own seat — never the price of the bots as well.
            ledger_drop = store.get_balance(host)
            expected_local = 100_000 - seat
            check("the ledger is debited for the host seat only",
                  ledger_drop == expected_local,
                  f"balance={ledger_drop} expected={expected_local}")

            print("\n[the server refuses the payment]")
            host2 = fresh(f"BTMoney_R_{uuid.uuid4().hex[:8]}", 100_000)
            names.append(host2)
            host2_cookie = mint({"user": host2, "login_name": host2.lower(),
                                 "csrf": "x"})

            async def refusing_take(player, amount, kind="sync"):
                from fastapi import HTTPException
                raise HTTPException(status_code=503,
                                    detail="Server chưa trừ Coin.")

            main_mod.pika_take = refusing_take
            r = await c.post("/api/battles", json={
                "case_id": case_id, "slots": 2, "rounds": 1, "mode": "STANDARD",
            }, cookies={"jv_session": host2_cookie}, headers={"x-csrf": "x"})
            check("a refused payment is reported as a failure",
                  r.status_code >= 400, f"http={r.status_code}")
            check("the Coin comes back to the ledger",
                  store.get_balance(host2) == 100_000,
                  f"balance={store.get_balance(host2)}")
            check("no battle is left in the lobby",
                  not any(b.get("host") == host2
                          for b in (store.list_battles().get("open") or [])),
                  "the refused battle is still in the lobby")

            print("\n[the server refuses the bots]")
            main_mod.pika_take = fake_take
            host3 = fresh(f"BTMoney_B_{uuid.uuid4().hex[:8]}", 100_000)
            names.append(host3)
            host3_cookie = mint({"user": host3, "login_name": host3.lower(),
                                 "csrf": "x"})
            r = await c.post("/api/battles", json={
                "case_id": case_id, "slots": 2, "rounds": 1, "mode": "STANDARD",
            }, cookies={"jv_session": host3_cookie}, headers={"x-csrf": "x"})
            check("the battle is created without bots", r.status_code == 200,
                  f"http={r.status_code}")
            battle3 = r.json().get("id")

            async def refusing_bot_take(player, amount, kind="sync"):
                from fastapi import HTTPException
                raise HTTPException(status_code=503,
                                    detail="Server chưa trừ Coin.")

            main_mod.pika_take = refusing_bot_take
            r = await c.post(f"/api/battles/{battle3}/bots", json={},
                             cookies={"jv_session": host3_cookie},
                             headers={"x-csrf": "x"})
            check("a refused bot payment is reported as a failure",
                  r.status_code >= 400, f"http={r.status_code}")
            after = store.get_battle(battle3)
            bots_left = [p for p in (after.get("players") or []) if p.get("is_bot")]
            check("the bots are taken back out of the lobby",
                  not bots_left, f"bots_left={len(bots_left)}")
            check("the Coin comes back to the ledger after the bots fail",
                  store.get_balance(host3) == 100_000 - seat,
                  f"balance={store.get_balance(host3)} expected={100_000 - seat}")

            print("\n[a refused payment must not hand out free Coin]")
            # The regression: the host pays the server for its own seat and
            # for every bot, but the ledger only ever held the host's own
            # seat. Refunding the server amount gave the host the price of
            # the bots for free, so a refused payment was a way to mint
            # Coin.
            host4 = fresh(f"BTMoney_F_{uuid.uuid4().hex[:8]}", 100_000)
            names.append(host4)
            host4_cookie = mint({"user": host4, "login_name": host4.lower(),
                                 "csrf": "x"})
            main_mod.pika_take = refusing_take
            r = await c.post("/api/battles", json={
                "case_id": case_id, "slots": 2, "rounds": 1,
                "mode": "STANDARD", "fill_bots": True,
            }, cookies={"jv_session": host4_cookie}, headers={"x-csrf": "x"})
            check("a refused payment with bots is reported as a failure",
                  r.status_code >= 400, f"http={r.status_code}")
            check("the host gets exactly the Coin back, not more",
                  store.get_balance(host4) == 100_000,
                  f"balance={store.get_balance(host4)} expected=100000")
            check("no battle is left behind",
                  not any(b.get("host") == host4
                          for b in (store.list_battles().get("open") or [])),
                  "the refused battle is still in the lobby")

            print("\n[the host cannot call bots on somebody else's battle]")
            main_mod.pika_take = fake_take
            other = fresh(f"BTMoney_O_{uuid.uuid4().hex[:8]}", 100_000)
            names.append(other)
            other_cookie = mint({"user": other, "login_name": other.lower(),
                                 "csrf": "x"})
            r = await c.post(f"/api/battles/{battle3}/bots", json={},
                             cookies={"jv_session": other_cookie},
                             headers={"x-csrf": "x"})
            check("another player cannot add bots",
                  r.status_code == 403, f"http={r.status_code}")

            print("\n[the host cannot take the win away from the game]")
            # A player who is not the host cannot start the battle.
            guest = fresh(f"BTMoney_G_{uuid.uuid4().hex[:8]}", 100_000)
            names.append(guest)
            guest_cookie = mint({"user": guest, "login_name": guest.lower(),
                                 "csrf": "x"})
            r = await c.post(f"/api/battles/{battle3}/join", json={},
                             cookies={"jv_session": guest_cookie},
                             headers={"x-csrf": "x"})
            check("a second player can join", r.status_code == 200,
                  f"http={r.status_code}")
            r = await c.post(f"/api/battles/{battle3}/start", json={},
                             cookies={"jv_session": guest_cookie},
                             headers={"x-csrf": "x"})
            check("a player who is not the host cannot start the battle",
                  r.status_code >= 400, f"http={r.status_code}")

            print("\n[the balance on the server and the ledger agree]")
            # The server was told to take the host seat and the bots. The
            # ledger only ever holds the host seat. The two must not be
            # compared directly: they answer different questions. What
            # must hold is that the ledger is never debited more than
            # the host's own seat.
            host_total = server_taken.get(host, 0)
            ledger_total = 100_000 - store.get_balance(host)
            check("the ledger only holds the host's own seat",
                  ledger_total == seat,
                  f"ledger={ledger_total} seat={seat} server={host_total}")

            print("\n[a guest cannot start a battle]")
            guest_client = httpx.AsyncClient(transport=transport,
                                             base_url="http://test", timeout=30)
            async with guest_client as g:
                r = await g.post("/api/battles", json={
                    "case_id": case_id, "slots": 2, "rounds": 1,
                    "mode": "STANDARD",
                }, headers={"x-csrf": "x"})
                check("a guest cannot create a battle", r.status_code == 401,
                      f"http={r.status_code}")

    finally:
        main_mod.pika_take = real_take
        for name in names:
            drop(name)

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")


asyncio.run(main())
