"""Migrate the gacha_* tables to the final schema, keeping all rows.

The original tables came out of the SQLite dump: their `id` columns were
plain INT (no IDENTITY) and the string columns were NVARCHAR(MAX), which
SQL Server will not accept as an index key. This rebuilds each table with
the schema the app expects and copies the data across.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyodbc  # noqa: E402

from app.config import SQL_DATABASE, SQL_SERVER  # noqa: E402
from tools.init_gacha_schema import GACHA_TABLES  # noqa: E402

# table -> ordered (new_column, old_column) pairs. The old column may be
# absent from the source table, in which case the new column is skipped.
PLAN: dict[str, list[tuple[str, str]]] = {
    "gacha_pulls": [
        ("id", "id"), ("player", "player"), ("cost", "cost"),
        ("prize_id", "prize_id"), ("prize_name", "prize_name"),
        ("rarity", "rarity"), ("prize_coin", "prize_coin"),
        ("created_at", "created_at"), ("case_id", "case_id"),
        ("dry_run", "dry_run"),
    ],
    "gacha_wallets": [
        ("player", "player"), ("balance", "balance"), ("is_bot", "is_bot"),
        ("created_at", "created_at"),
    ],
    "gacha_inventory": [
        ("id", "id"), ("player", "player"), ("item_id", "item_id"),
        ("name", "name"), ("rarity", "rarity"), ("value", "value"),
        ("image", "image"), ("color", "color"), ("source", "source"),
        ("status", "status"), ("case_id", "case_id"),
        ("created_at", "created_at"),
    ],
    "gacha_drops": [
        ("id", "id"), ("player", "player"), ("is_bot", "is_bot"),
        ("item_id", "item_id"), ("name", "name"), ("rarity", "rarity"),
        ("value", "value"), ("image", "image"), ("color", "color"),
        ("case_id", "case_id"), ("created_at", "created_at"),
    ],
    "gacha_battles": [
        ("id", "id"), ("host", "host"), ("case_id", "case_id"),
        ("rounds", "rounds"), ("slots", "slots"), ("mode", "mode"),
        ("status", "status"), ("winner", "winner"),
        ("created_at", "created_at"), ("started_at", "started_at"),
        ("finished_at", "finished_at"),
    ],
    "gacha_battle_players": [
        ("battle_id", "battle_id"), ("player", "player"), ("is_bot", "is_bot"),
        ("slot", "slot"), ("total", "total"), ("paid", "paid"),
    ],
    "gacha_battle_drops": [
        ("id", "id"), ("battle_id", "battle_id"), ("player", "player"),
        ("round", "round"), ("item_id", "item_id"), ("name", "name"),
        ("rarity", "rarity"), ("value", "value"), ("image", "image"),
        ("color", "color"),
    ],
    "gacha_upgrades": [
        ("id", "id"), ("player", "player"), ("stake_name", "stake_name"),
        ("stake_value", "stake_value"), ("target_name", "target_name"),
        ("target_value", "target_value"), ("chance", "chance"),
        ("roll", "roll"), ("won", "won"), ("created_at", "created_at"),
    ],
    "gacha_contracts": [
        ("id", "id"), ("player", "player"), ("stake_value", "stake_value"),
        ("item_count", "item_count"), ("reward_id", "reward_id"),
        ("reward_name", "reward_name"), ("reward_value", "reward_value"),
        ("created_at", "created_at"),
    ],
    "gacha_bonus": [
        ("player", "player"), ("last_claim", "last_claim"),
    ],
    "gacha_tx": [
        ("id", "id"), ("player", "player"), ("kind", "kind"),
        ("amount", "amount"), ("note", "note"), ("created_at", "created_at"),
    ],
}

# tables whose `id` column is an IDENTITY in the target schema
IDENTITY_TABLES = {
    table for table, (cols, _) in GACHA_TABLES.items()
    if cols.startswith("id INT IDENTITY")
}


def main() -> int:
    conn_str = (
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server={SQL_SERVER};Database={SQL_DATABASE};"
        "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;"
    )
    with pyodbc.connect(conn_str, timeout=180, autocommit=False) as cn:
        cur = cn.cursor()

        for table, cols in PLAN.items():
            cur.execute(
                "SELECT COUNT(*) FROM sys.tables WHERE name = ?", table
            )
            if not cur.fetchone()[0]:
                print(f"{table:24} absent")
                continue

            cur.execute(
                "SELECT c.name, c.is_identity, c.max_length "
                "FROM sys.columns c "
                "JOIN sys.tables t ON c.object_id = t.object_id "
                "WHERE t.name = ?", table
            )
            info = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
            if not info:
                print(f"{table:24} has no columns")
                continue

            needs = any(
                info[name][1] == -1
                or (name == "id" and not info[name][0] and table in IDENTITY_TABLES)
                for name in info
            )
            if not needs:
                print(f"{table:24} already up to date")
                continue

            target_cols, pk = GACHA_TABLES[table]
            tmp = f"__mig_{table}"
            cur.execute(f"DROP TABLE IF EXISTS [{tmp}]")
            cur.execute(
                f"CREATE TABLE [{tmp}] ({target_cols}, CONSTRAINT PK_{tmp} {pk})"
            )

            usable = [(new, old) for new, old in cols if old in info]
            collist = ", ".join(f"[{new}]" for new, _ in usable)
            srclist = ", ".join(f"[{old}]" for _, old in usable)

            if table in IDENTITY_TABLES and "id" in info:
                cur.execute(f"SET IDENTITY_INSERT [{tmp}] ON")
            cur.execute(
                f"INSERT INTO [{tmp}] ({collist}) SELECT {srclist} FROM [{table}]"
            )
            moved = cur.rowcount
            if table in IDENTITY_TABLES and "id" in info:
                cur.execute(f"SET IDENTITY_INSERT [{tmp}] OFF")

            cur.execute(f"DROP TABLE [{table}]")
            cur.execute(f"sp_rename '{tmp}', '{table}'")
            cn.commit()
            print(f"{table:24} migrated, {moved:,} rows")

    print("gacha schema migration done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
