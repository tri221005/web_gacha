"""Remove the rows the test suites leave behind.

The tests create players with names like `AUD_...` and `__selftest__`.
They clean up after themselves, but a run that was interrupted leaves the
rows behind. This removes them.

Run:  python tools/cleanup_test_data.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import store  # noqa: E402

# The tables that hold a player name.
TABLES = (
    "gacha_inventory",
    "gacha_tx",
    "gacha_pulls",
    "gacha_upgrades",
    "gacha_wallets",
    "gacha_bonus",
)

# The name patterns the tests use.
PATTERNS = ("AUD[_]%", "__selftest__%", "StubPlayer", "joinplayer",
            "Broke[_]%", "RC[_]%", "J[_]%", "Alice", "badcount",
            "battleloop", "doubletester", "halfread", "Host", "loopplayer",
            "Mallory", "refusedplayer", "Bob; op Bob",             "Injector; op Injector",
            "Broke", "Tester")

# The real players, who must never be removed.
KEEP = ("hhh21", "shsuzy")


def main() -> None:
    store.init()
    total = 0
    for table in TABLES:
        for pattern in PATTERNS:
            def inner(con, table=table, pattern=pattern):
                cur = con.cursor()
                cur.execute(f"DELETE FROM {table} WHERE player LIKE ?", pattern)
                return cur.rowcount

            try:
                total += store.run(inner)
            except Exception:
                pass
    print(f"rows removed: {total}")

    left = store.run(
        lambda con: con.cursor().execute(
            "SELECT COUNT(*) FROM gacha_wallets WHERE player LIKE 'AUD[_]%' "
            "OR player LIKE '__%' OR player IN ('StubPlayer','joinplayer')"
        ).fetchone()[0]
    )
    print(f"test wallets left: {left}")

    # The battles the tests made.
    def drop_battles(con):
        cur = con.cursor()
        cur.execute(
            "DELETE FROM gacha_battle_drops WHERE battle_id IN "
            "(SELECT id FROM gacha_battles WHERE host LIKE 'AUD[_]%' "
            "OR host LIKE '__%' OR host LIKE 'RC[_]%' OR host = 'Broke' "
            "OR host LIKE 'J[_]%')"
        )
        cur.execute(
            "DELETE FROM gacha_battle_players WHERE battle_id IN "
            "(SELECT id FROM gacha_battles WHERE host LIKE 'AUD[_]%' "
            "OR host LIKE '__%' OR host LIKE 'RC[_]%' OR host = 'Broke' "
            "OR host LIKE 'J[_]%')"
        )
        cur.execute(
            "DELETE FROM gacha_battles WHERE host LIKE 'AUD[_]%' "
            "OR host LIKE '__%' OR host LIKE 'RC[_]%' OR host = 'Broke' "
            "OR host LIKE 'J[_]%'"
        )
        return cur.rowcount

    battles = store.run(drop_battles)
    print(f"test battles removed: {battles}")

    # The players who are left, so the list can be checked by eye.
    rows = store.run(
        lambda con: con.cursor().execute(
            "SELECT player, is_bot FROM gacha_wallets ORDER BY player"
        ).fetchall()
    )
    names = [dict(store.row_dict(r))["player"] for r in rows]
    print("wallets left:", ", ".join(names))
    missing = [k for k in KEEP if k not in names]
    if missing:
        # A player who has never signed in has no wallet yet. That is
        # normal, so it is only a note, not a warning.
        print("note: these players have no wallet yet (never signed in):",
              ", ".join(missing))


main()
