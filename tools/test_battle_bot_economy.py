"""Probe: the money in a battle where the host is a bot.

The design says: "a bot seat costs the server nothing but can win items
the host sells for real money, so the host pays for every bot it calls."

That works when a *real* host creates the room and calls the bots: the
host pays for both seats on the server, so the server gets its money back
from the payout.

It does not work the other way round. When a **bot** creates the room and
a **real** player joins it, the real player only pays for their own seat.
The bot's seat was paid from the bot's fake local wallet, never from the
server. If the real player then wins, they take the bot's drops as well
and can sell them for real Coin on the Minecraft server.

This probe measures that leak.

Run:  python tools/test_battle_bot_economy.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app import store  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402
from tools.test_security import Panel, build_panel  # noqa: E402

STUB_PORT = 8141

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> None:
    store.init()
    panel = Panel()
    panel.add_user("joinplayer", "joinplayer")

    with store._lock:
        con = store.connect()
        cur = con.cursor()
        for table in ("gacha_inventory", "gacha_tx", "gacha_wallets",
                      "gacha_battle_players", "gacha_battle_drops",
                      "gacha_battles"):
            cur.execute(f"DELETE FROM {table}")
        con.commit()

    server = uvicorn_server(panel)

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
                                 timeout=120) as c:
        cookie = mint({"user": "joinplayer", "login_name": "joinplayer",
                       "csrf": "x"})
        await c.get("/api/wallet/live", cookies={"jv_session": cookie})
        before = panel.balances["joinplayer"]

        print("[a real player joins a room a bot created]")
        # The bot creates the room. Only the bot's fake wallet pays for
        # the bot seat.
        import app.game as game_mod
        bot_host = store.BOT_NAMES[0]
        # In live mode the bot wallet is only seeded with the bot's real
        # PikaMC balance, which is zero. The bot needs a local wallet to
        # sit down, exactly like it has in production.
        game_mod.seed_wallet(bot_host, is_bot=True)
        created = game_mod.create_battle(bot_host, "jelly-starter", slots=2,
                                         rounds=1, mode="STANDARD", is_bot=True)
        battle_id = created["id"]

        r = await c.post(f"/api/battles/{battle_id}/join", json={},
                         cookies={"jv_session": cookie}, headers={"x-csrf": "x"})
        check("the real player can join the bot's room",
              r.status_code == 200, f"http={r.status_code} body={r.text[:150]}")
        if r.status_code != 200:
            server.should_exit = True
            await server_task
            return

        # The player must pay for the bot seat as well as their own: the
        # bot seat was never paid for on the Minecraft server.
        seat_price = 5000
        paid_now = before - panel.balances["joinplayer"]
        check("the player pays for the bot seat too",
              paid_now == seat_price * 2,
              f"paid {paid_now}, expected {seat_price * 2}")

        r = await c.post(f"/api/battles/{battle_id}/start", json={},
                         cookies={"jv_session": cookie}, headers={"x-csrf": "x"})
        check("the real player cannot start a room the bot hosts",
              r.status_code >= 400, f"http={r.status_code}")

        # The bot loop is what starts a bot's room once it is full.
        import app.game as game_mod2
        game_mod2.start_battle(battle_id, bot_host)

        battle = store.get_battle(battle_id)
        check("the battle finished", battle["status"] == "FINISHED",
              str(battle["status"]))
        winner = battle["winner"]
        check("the battle has a winner",
              winner in ("joinplayer", bot_host), str(winner))

        # What did the real player pay, and what did they get?
        paid_to_server = before - panel.balances["joinplayer"]
        held = store.list_inventory("joinplayer", "held")
        won_value = sum(int(i["value"]) for i in held)

        print("\n[the economics of the bot's room]")
        print(f"    paid to the server : {paid_to_server:>12,}")
        print(f"    items won          : {won_value:>12,}")
        print(f"    difference         : {won_value - paid_to_server:>12,}")

        # The player paid for one seat, but the drops of BOTH seats end up
        # in their bag, and the bag can be sold for real Coin. So the
        # question is not "did this one round win" but "does this pay
        # out over many rounds".
        print("\n[repeat it many times to see the average]")
        total_paid = 0
        total_won = 0
        wins = 0
        rounds = 60
        for _ in range(rounds):
            with store._lock:
                con = store.connect()
                cur = con.cursor()
                cur.execute("DELETE FROM gacha_inventory WHERE player = ?",
                            "joinplayer")
                cur.execute("DELETE FROM gacha_wallets WHERE player = ?",
                            "joinplayer")
                con.commit()
            panel.balances["joinplayer"] = 100_000.0
            # The stub panel writes the balance back into its SQLite file,
            # so both have to be reset. Otherwise the balance the app
            # reads keeps falling and the join is refused.
            import sqlite3
            con = sqlite3.connect(panel.economy)
            con.execute(
                "UPDATE excellenteconomy_users SET money = ? WHERE name = ?",
                (100_000.0, "joinplayer"),
            )
            con.commit()
            con.close()
            # The local ledger needs the wallet too, or the join is
            # refused for "not enough Coin".
            store.run(lambda con: con.cursor().execute(
                "DELETE FROM gacha_wallets WHERE player = ?", "joinplayer"))
            store.credit("joinplayer", 100_000, "seed", "test")
            game_mod.seed_wallet(bot_host, is_bot=True)
            b = game_mod.create_battle(bot_host, "jelly-starter", slots=2,
                                       rounds=1, mode="STANDARD", is_bot=True)
            r = await c.post(f"/api/battles/{b['id']}/join", json={},
                             cookies={"jv_session": cookie},
                             headers={"x-csrf": "x"})
            if r.status_code != 200:
                print(f"    join failed: http={r.status_code} {r.text[:200]}")
                continue
            # The bot loop starts its own room.
            game_mod2.start_battle(b["id"], bot_host)
            bt = store.get_battle(b["id"])
            # The player paid for their seat in every round, win or lose.
            total_paid += 100_000.0 - panel.balances["joinplayer"]
            if bt["winner"] != "joinplayer":
                continue
            wins += 1
            h = store.list_inventory("joinplayer", "held")
            total_won += sum(int(i["value"]) for i in h)
        print(f"    {rounds} rounds ({wins} wins): paid {total_paid:>12,}  "
              f"won {total_won:>12,}  net {total_won - total_paid:>+12,}")
        check("joining a bot's room is never profitable over many rounds",
              total_won <= total_paid,
              f"paid {total_paid} but won {total_won} "
              f"(+{total_won - total_paid})")

    server.should_exit = True
    await server_task

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")


def uvicorn_server(panel):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(build_panel(panel), host="127.0.0.1",
                                            port=STUB_PORT, log_level="error"))
    global server_task
    server_task = asyncio.create_task(server.serve())
    return server


asyncio.run(main())
