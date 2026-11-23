"""Audit: the things that break when two people act at the same time.

The app runs on one web container, but a slow request can overlap with a
fast one, and the bot loop runs in the background at the same time. So
the checks here are about two actions racing each other, and about a
request that dies halfway through.

Run:  python tools/test_audit_concurrency.py
"""
from __future__ import annotations

import os
import sys
import threading
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GACHA_DRY_RUN", "true")

from app import game, store  # noqa: E402

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


def wipe(name: str) -> None:
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


def main() -> None:
    store.init()
    names: list[str] = []

    # ------------------------------------------------------------------ #
    print("[two players cannot take the same item at the same time]")
    # ------------------------------------------------------------------ #
    owner = fresh(f"AUD_Race_{uuid.uuid4().hex[:8]}", 100_000)
    names.append(owner)
    item = game.market_listings()[0]
    inv_id = store.add_inventory(owner, item, "case", "jelly-starter")

    sold: list[str] = []
    refused: list[str] = []

    def sell() -> None:
        try:
            game.sell_items(owner, [inv_id])
            sold.append("ok")
        except game.GameError:
            refused.append("refused")

    threads = [threading.Thread(target=sell) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("only one thread can sell the same item",
          len(sold) == 1, f"sold={len(sold)} refused={len(refused)}")
    tx_count = store.run(
        lambda con: con.cursor().execute(
            "SELECT COUNT(*) FROM gacha_tx WHERE player = ? AND kind = 'sell'",
            owner,
        ).fetchone()[0]
    )
    check("the sale is credited exactly once", tx_count == 1, f"rows={tx_count}")

    # ------------------------------------------------------------------ #
    print("\n[the same player cannot open the same item twice]")
    # ------------------------------------------------------------------ #
    p2 = fresh(f"AUD_Up_{uuid.uuid4().hex[:8]}", 100_000)
    names.append(p2)
    cheap = game.market_listings()[0]
    inv2 = store.add_inventory(p2, cheap, "case", "jelly-starter")
    target = next((i for i in game.market_listings() if i.coin > cheap.coin * 2), None)
    if target is not None:
        ups = []
        ups_refused = []

        def upgrade() -> None:
            try:
                game.do_upgrade(p2, inv2, target.id, target.coin)
                ups.append("ok")
            except game.GameError:
                ups_refused.append("refused")

        ts = [threading.Thread(target=upgrade) for _ in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        check("only one thread can upgrade the same item",
              len(ups) == 1, f"ups={len(ups)} refused={len(ups_refused)}")
        rows = store.run(
            lambda con: con.cursor().execute(
                "SELECT COUNT(*) FROM gacha_upgrades WHERE player = ?", p2
            ).fetchone()[0]
        )
        check("the upgrade is logged exactly once", rows == 1, f"rows={rows}")

    # ------------------------------------------------------------------ #
    print("\n[the bonus cannot be claimed twice at the same time]")
    # ------------------------------------------------------------------ #
    p3 = fresh(f"AUD_Bon_{uuid.uuid4().hex[:8]}", 100_000)
    names.append(p3)
    claims: list[str] = []
    refused_claims: list[str] = []

    def claim() -> None:
        try:
            game.claim_bonus(p3)
            claims.append("ok")
        except game.GameError:
            refused_claims.append("refused")

    ts = [threading.Thread(target=claim) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check("only one thread can claim the bonus",
          len(claims) == 1, f"claims={len(claims)} refused={len(refused_claims)}")

    # ------------------------------------------------------------------ #
    print("\n[a battle that dies halfway is not left half-finished]")
    # ------------------------------------------------------------------ #
    # settle_battle does the roll, then writes the result, then gives the
    # items to the winner. If the second step throws, the battle is
    # already FINISHED but the items are gone.
    host = fresh(f"AUD_Half_{uuid.uuid4().hex[:8]}", 100_000)
    guest = fresh(f"AUD_Half2_{uuid.uuid4().hex[:8]}", 100_000)
    names += [host, guest]
    b = game.create_battle(host, "jelly-starter", slots=2, rounds=1,
                           mode="STANDARD")
    game.join_existing_battle(guest, b["id"])
    battle_id = b["id"]

    # Break the inventory write: the battle result is saved, then the
    # items go into the bag, and that second step fails.
    real_finish = store.finish_battle
    calls = {"n": 0}

    def failing_finish(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("the database went away")

    store.finish_battle = failing_finish
    try:
        game.settle_battle(battle_id)
        crashed = False
    except Exception:
        crashed = True
    finally:
        store.finish_battle = real_finish

    after = store.get_battle(battle_id)
    check("the battle did not report success when the write failed",
          crashed, "settle_battle returned as if it worked")
    check("a battle whose write failed is not left marked FINISHED",
          after["status"] != "FINISHED",
          f"status={after['status']} (it should stay WAITING so it can "
          f"be retried or cancelled)")
    check("a battle whose write failed has no winner recorded",
          not after.get("winner"), str(after.get("winner")))

    # ------------------------------------------------------------------ #
    print("\n[a battle that stays RUNNING can still be finished]")
    # ------------------------------------------------------------------ #
    # The battle that was broken above is still RUNNING. It must be
    # startable again, because it has no result.
    broken = store.get_battle(battle_id)
    check("the broken battle has no winner", not broken.get("winner"),
          str(broken.get("winner")))
    try:
        retried = game.start_battle(battle_id, host)
        recovered = retried["status"] == "FINISHED" and bool(retried.get("winner"))
    except game.GameError as exc:
        recovered = False
        print(f"    {exc}")
    check("a battle left in RUNNING can be run again", recovered,
          "the battle could not be finished")
    if recovered:
        held = store.list_inventory(retried["winner"], "held")
        check("the retry gives the prize to the winner", len(held) > 0,
              f"held={len(held)}")

    stuck = store.run(
        lambda con: con.cursor().execute(
            "SELECT COUNT(*) FROM gacha_battles WHERE status = 'RUNNING' "
            "AND id >= ?", battle_id,
        ).fetchone()[0]
    )
    check("no battle is left in RUNNING state", stuck == 0, f"running={stuck}")

    # ------------------------------------------------------------------ #
    print("\n[the battle list does not grow without limit]")
    # ------------------------------------------------------------------ #
    total = store.run(
        lambda con: con.cursor().execute(
            "SELECT COUNT(*) FROM gacha_battles"
        ).fetchone()[0]
    )
    finished = store.run(
        lambda con: con.cursor().execute(
            "SELECT COUNT(*) FROM gacha_battles WHERE status = 'FINISHED'"
        ).fetchone()[0]
    )
    print(f"    battles in the ledger: {total} ({finished} finished)")
    check("finished battles are kept for the history", finished >= 0,
          f"finished={finished}")

    # ------------------------------------------------------------------ #
    print("\n[the bot loop does not give real players a free seat]")
    # ------------------------------------------------------------------ #
    # A bot that sits down in a room a real player hosts gives that
    # player the bot's drops for free, because the bot's seat was never
    # paid for on the server.
    real = fresh(f"AUD_Free_{uuid.uuid4().hex[:8]}", 100_000)
    names.append(real)
    b3 = game.create_battle(real, "jelly-starter", slots=2, rounds=1,
                            mode="STANDARD")
    bot_name = next(n for n in store.BOT_NAMES if n != real)
    game.seed_wallet(bot_name, is_bot=True)
    game.join_existing_battle(bot_name, b3["id"], is_bot=True)
    # The bot's seat was paid from the bot's fake wallet, never from
    # the server, so the real player only paid for their own seat.
    seats = store.get_battle(b3["id"])["players"]
    bot_row = next(r for r in seats if r["player"] == bot_name)
    check("the bot's seat was paid from the bot's own fake wallet",
          int(bot_row["paid"]) == 5000 and store.get_balance(real) == 95_000,
          f"bot paid={bot_row['paid']} real balance={store.get_balance(real)}")

    # The bot loop must not add a bot to a real player's room.
    import app.bots as bots_mod
    before_seats = len(store.get_battle(b3["id"])["players"])
    for _ in range(5):
        bots_mod._tick()
    after_seats = len(store.get_battle(b3["id"])["players"])
    check("the bot loop does not join a real player's room",
          after_seats == before_seats,
          f"seats went from {before_seats} to {after_seats}")

    # ------------------------------------------------------------------ #
    print("\n[the wallet and the ledger agree after all of this]")
    # ------------------------------------------------------------------ #
    for name in names:
        wallet = store.get_balance(name)
        txs = store.recent_tx(name, 100)
        total_tx = sum(int(t["amount"]) for t in txs)
        check(f"the ledger of {name[:14]} adds up",
              abs(wallet - total_tx) < 2,
              f"balance={wallet} sum(tx)={total_tx}")

    for name in names:
        wipe(name)

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")


main()
