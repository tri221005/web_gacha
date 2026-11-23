"""Create the gacha_* schema (no data) in SQL Server.

The full dump `jellyvale_full.sql` carries the server data; this script only
makes sure the ledger tables the app writes to exist.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import SQL_DATABASE, SQL_SERVER  # noqa: E402

# table -> (columns ddl, primary key ddl)
GACHA_TABLES: dict[str, tuple[str, str]] = {
    "gacha_pulls": (
        "id INT IDENTITY(1,1) NOT NULL, player NVARCHAR(450) NOT NULL, "
        "cost BIGINT NOT NULL, prize_id NVARCHAR(450) NOT NULL, "
        "prize_name NVARCHAR(450) NOT NULL, rarity NVARCHAR(450) NOT NULL, "
        "prize_coin BIGINT NOT NULL, created_at BIGINT NOT NULL, "
        "case_id NVARCHAR(450) NOT NULL DEFAULT '', "
        "dry_run BIGINT NOT NULL DEFAULT 0",
        "PRIMARY KEY (id)",
    ),
    "gacha_wallets": (
        "player NVARCHAR(450) NOT NULL, balance BIGINT NOT NULL DEFAULT 0, "
        "is_bot BIGINT NOT NULL DEFAULT 0, created_at BIGINT NOT NULL",
        "PRIMARY KEY (player)",
    ),
    "gacha_inventory": (
        "id INT IDENTITY(1,1) NOT NULL, player NVARCHAR(450) NOT NULL, "
        "item_id NVARCHAR(450) NOT NULL, name NVARCHAR(450) NOT NULL, "
        "rarity NVARCHAR(450) NOT NULL, value BIGINT NOT NULL, "
        "image NVARCHAR(450) NOT NULL, color NVARCHAR(450) NOT NULL, "
        "source NVARCHAR(450) NOT NULL, status NVARCHAR(450) NOT NULL DEFAULT 'held', "
        "case_id NVARCHAR(450) NOT NULL DEFAULT '', created_at BIGINT NOT NULL",
        "PRIMARY KEY (id)",
    ),
    "gacha_drops": (
        "id INT IDENTITY(1,1) NOT NULL, player NVARCHAR(450) NOT NULL, "
        "is_bot BIGINT NOT NULL DEFAULT 0, item_id NVARCHAR(450) NOT NULL, "
        "name NVARCHAR(450) NOT NULL, rarity NVARCHAR(450) NOT NULL, "
        "value BIGINT NOT NULL, image NVARCHAR(450) NOT NULL, "
        "color NVARCHAR(450) NOT NULL, case_id NVARCHAR(450) NOT NULL DEFAULT '', "
        "created_at BIGINT NOT NULL",
        "PRIMARY KEY (id)",
    ),
    "gacha_battles": (
        "id INT IDENTITY(1,1) NOT NULL, host NVARCHAR(450) NOT NULL, "
        "case_id NVARCHAR(450) NOT NULL, rounds BIGINT NOT NULL DEFAULT 1, "
        "slots BIGINT NOT NULL, mode NVARCHAR(450) NOT NULL DEFAULT 'STANDARD', "
        "status NVARCHAR(450) NOT NULL, winner NVARCHAR(450) NULL, "
        "created_at BIGINT NOT NULL, started_at BIGINT NULL, "
        "finished_at BIGINT NULL",
        "PRIMARY KEY (id)",
    ),
    "gacha_battle_players": (
        "battle_id BIGINT NOT NULL, player NVARCHAR(440) NOT NULL, "
        "is_bot BIGINT NOT NULL DEFAULT 0, slot BIGINT NOT NULL, "
        "total BIGINT NOT NULL DEFAULT 0, paid BIGINT NOT NULL",
        "PRIMARY KEY (battle_id, player)",
    ),
    "gacha_battle_drops": (
        "id INT IDENTITY(1,1) NOT NULL, battle_id BIGINT NOT NULL, "
        "player NVARCHAR(450) NOT NULL, round BIGINT NOT NULL, "
        "item_id NVARCHAR(450) NOT NULL, name NVARCHAR(450) NOT NULL, "
        "rarity NVARCHAR(450) NOT NULL, value BIGINT NOT NULL, "
        "image NVARCHAR(450) NOT NULL, color NVARCHAR(450) NOT NULL",
        "PRIMARY KEY (id)",
    ),
    "gacha_upgrades": (
        "id INT IDENTITY(1,1) NOT NULL, player NVARCHAR(450) NOT NULL, "
        "stake_name NVARCHAR(450) NOT NULL, stake_value BIGINT NOT NULL, "
        "target_name NVARCHAR(450) NOT NULL, target_value BIGINT NOT NULL, "
        "chance FLOAT NOT NULL, roll FLOAT NOT NULL, won BIGINT NOT NULL, "
        "created_at BIGINT NOT NULL",
        "PRIMARY KEY (id)",
    ),
    "gacha_contracts": (
        "id INT IDENTITY(1,1) NOT NULL, player NVARCHAR(450) NOT NULL, "
        "stake_value BIGINT NOT NULL, item_count BIGINT NOT NULL, "
        "reward_id NVARCHAR(450) NULL, reward_name NVARCHAR(450) NULL, "
        "reward_value BIGINT NULL, created_at BIGINT NOT NULL",
        "PRIMARY KEY (id)",
    ),
    "gacha_bonus": (
        "player NVARCHAR(450) NOT NULL, last_claim BIGINT NOT NULL",
        "PRIMARY KEY (player)",
    ),
    "gacha_tx": (
        "id INT IDENTITY(1,1) NOT NULL, player NVARCHAR(450) NOT NULL, "
        "kind NVARCHAR(450) NOT NULL, amount BIGINT NOT NULL, "
        "note NVARCHAR(450) NOT NULL DEFAULT '', created_at BIGINT NOT NULL",
        "PRIMARY KEY (id)",
    ),
    "gacha_bans": (
        "player NVARCHAR(450) NOT NULL, reason NVARCHAR(450) NOT NULL DEFAULT '', "
        "created_at BIGINT NOT NULL",
        "PRIMARY KEY (player)",
    ),
    "gacha_admin_log": (
        "id INT IDENTITY(1,1) NOT NULL, admin NVARCHAR(450) NOT NULL, "
        "action NVARCHAR(450) NOT NULL, target NVARCHAR(450) NOT NULL DEFAULT '', "
        "detail NVARCHAR(450) NOT NULL DEFAULT '', created_at BIGINT NOT NULL",
        "PRIMARY KEY (id)",
    ),
}


def build_schema() -> str:
    """DDL that creates every gacha table when it does not exist yet."""
    parts = []
    for table, (cols, pk) in GACHA_TABLES.items():
        parts.append(
            f"IF OBJECT_ID('{table}') IS NULL\n"
            f"CREATE TABLE {table} (\n    {cols},\n    CONSTRAINT PK_{table} {pk}\n);"
        )
    return "\n".join(parts)


GACHA_SCHEMA = build_schema()


def main() -> int:
    import pyodbc

    conn_str = (
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server={SQL_SERVER};Database={SQL_DATABASE};"
        "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;"
    )
    with pyodbc.connect(conn_str, timeout=30, autocommit=True) as cn:
        cn.cursor().execute(GACHA_SCHEMA)
    print(f"gacha schema ready in {SQL_DATABASE} @ {SQL_SERVER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
