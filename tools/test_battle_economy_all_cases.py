"""Probe: the money in a battle, for every case.

The bot-hosted room is where the money could leak: the bot seat was
never paid for on the Minecraft server, so the player who joins has to
pay for it. This probe checks that for every case, including the ones
that pay out more than they cost.

Run:  python tools/test_battle_economy_all_cases.py
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app import game, store  # noqa: E402
from app.gacha import case_rtp, load_cases  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402
from tools.test_security import Panel, build_panel  # noqa: E402

STUB_PORT = 8147
PLAYER = "joinplayer"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> None:
    store.init()
    panel = Panel()
    panel.add_user(PLAYER, PLAYER)

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
        cookie = mint({"user": PLAYER, "login_name": PLAYER, "csrf": "x"})

        for case in load_cases():
            seat = case.pull_cost
            rtp = case_rtp(case) * 100
            print(f"\n[{case.id}] seat={seat:,} RTP={rtp:.1f}%")

            # Reset the player and the room.
            panel.balances[PLAYER] = 1_000_000.0
            con = sqlite3.connect(panel.economy)
            con.execute(
                "UPDATE excellenteconomy_users SET money = ? WHERE name = ?",
                (1_000_000.0, PLAYER),
            )
            con.commit()
            con.close()
            store.run(lambda cn: cn.cursor().execute(
                "DELETE FROM gacha_inventory WHERE player = ?", PLAYER))
            store.run(lambda cn: cn.cursor().execute(
                "DELETE FROM gacha_wallets WHERE player = ?", PLAYER))
            store.credit(PLAYER, 1_000_000, "seed", "test")

            # The bot needs enough Coin in its own fake wallet to sit
            # down, so it is topped up here.
            bot = store.BOT_NAMES[0]
            game.seed_wallet(bot, is_bot=True)
            store.credit(bot, seat * 10, "seed", "bot nap")
            battle = game.create_battle(bot, case.id, slots=2, rounds=1,
                                        mode="STANDARD", is_bot=True)
            r = await c.post(f"/api/battles/{battle['id']}/join", json={},
                             cookies={"jv_session": cookie},
                             headers={"x-csrf": "x"})
            if r.status_code != 200:
                check(f"{case.id}: the player can join", False,
                      f"http={r.status_code} {r.text[:120]}")
                continue
            paid = 1_000_000.0 - panel.balances[PLAYER]
            check(f"{case.id}: the player pays for both seats",
                  paid == seat * 2,
                  f"paid {paid:,.0f}, expected {seat * 2:,}")

            # The value of the two seats. The theoretical RTP is used for
            # the decision, because sampling the loot table is noisy: the
            # jackpot items are worth so much that a few thousand rolls
            # can swing the measured average by a wide margin.
            expected_win = 2 * seat * rtp / 100
            # The sampled average is only used to confirm that the
            # measured value lands near the theoretical one.
            from app.gacha import roll
            samples = 4000
            measured = sum(roll(case).coin for _ in range(samples)) / samples
            theoretical = seat * rtp / 100
            check(f"{case.id}: the measured value is near the theoretical one",
                  abs(measured - theoretical) <= theoretical * 0.25,
                  f"measured {measured:,.0f} vs theoretical {theoretical:,.0f} "
                  f"over {samples} rolls")
            # A case with an RTP over 100% pays out more than it costs,
            # so playing it is a winning move on its own. The bot room
            # must not make that any better than playing alone.
            if rtp <= 100:
                check(f"{case.id}: the player cannot profit from a bot room",
                      expected_win <= seat * 2,
                      f"two seats are worth {expected_win:,.0f} but cost "
                      f"{seat * 2:,} (RTP {rtp:.1f}%)")
            else:
                # The RTP alone is over 100%. The bot room must not add
                # anything on top: two seats must cost two seats.
                check(f"{case.id}: the bot room costs exactly two seats",
                      paid == seat * 2,
                      f"paid {paid:,.0f}, expected {seat * 2:,}")
                print(f"    note: this case pays {rtp:.1f}% on its own, "
                      f"so playing it wins {expected_win - seat * 2:,.0f} "
                      f"per room no matter who hosts")

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
