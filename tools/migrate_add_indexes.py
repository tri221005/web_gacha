"""Add the indexes the gacha ledger needs.

Every lookup in the app filters on a column that had no index, so the
database had to read the whole table. `gacha_inventory` alone had almost
20,000 rows and grows with every pull.

The indexes are added here and in `jellyvale_full.sql`, so a fresh
install gets them too. Running this twice is harmless.

Run:  python tools/migrate_add_indexes.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import store  # noqa: E402

# (index name, table, columns, extra)
INDEXES = [
    # The bag page and the admin inventory page filter on these.
    ("ix_gacha_inventory_player_status", "gacha_inventory",
     "(player, status)", ""),
    # The live drop strip reads the newest rows.
    ("ix_gacha_drops_id_desc", "gacha_drops", "(id DESC)", ""),
    # The stats page groups pulls by case and by player.
    ("ix_gacha_pulls_case_id", "gacha_pulls", "(case_id)", ""),
    ("ix_gacha_pulls_player", "gacha_pulls", "(player)", ""),
    # The wallet history and the admin transaction list.
    ("ix_gacha_tx_player_id", "gacha_tx", "(player, id DESC)", ""),
    # The lobby lists open battles, the bot loop looks for waiting ones.
    ("ix_gacha_battles_status", "gacha_battles", "(status, id DESC)", ""),
    # The battle seats and the drops of one battle.
    ("ix_gacha_battle_players_battle", "gacha_battle_players", "(battle_id)", ""),
    ("ix_gacha_battle_drops_battle", "gacha_battle_drops", "(battle_id)", ""),
    # The upgrade history and the drop history of one player.
    ("ix_gacha_upgrades_player", "gacha_upgrades", "(player)", ""),
    ("ix_gacha_drops_player", "gacha_drops", "(player)", ""),
]


def main() -> None:
    store.init()
    for name, table, columns, extra in INDEXES:
        ddl = (
            f"CREATE {extra} INDEX {name} ON {table} {columns}"
        )
        try:
            store.run(lambda con, ddl=ddl: con.cursor().execute(ddl))
            print(f"  created  {name} on {table} {columns}")
        except Exception as exc:
            if "already exists" in str(exc).lower() or "27029" in str(exc):
                print(f"  exists   {name}")
            else:
                print(f"  FAILED   {name}: {exc}")
    print("done")


main()
