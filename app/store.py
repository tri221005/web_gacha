"""Gacha ledger storage backed by SQL Server.

Replaces the previous local SQLite store. The schema lives in
`jellyvale_full.sql` (tables prefixed `gacha_`), so this module only speaks
T-SQL and never creates tables itself.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from typing import Any

import pyodbc

from .config import (
    SQL_DATABASE,
    SQL_DRIVER,
    SQL_ENCRYPT,
    SQL_PASSWORD,
    SQL_PORT,
    SQL_SERVER,
    SQL_TIMEOUT,
    SQL_TRUST_CERT,
    SQL_USER,
)

DB_PATH = SQL_DATABASE
_lock = threading.Lock()

BOT_NAMES = (
    "JellyBot",
    "ValeBot",
    "SlimeAI",
    "HoneyBot",
    "NightOwl",
    "ForgeBot",
    "GolemAI",
    "BeeKeeper",
)

_CONN: pyodbc.Connection | None = None


def _conn_str() -> str:
    """Build the ODBC connection string.

    A SQL login is used when `SQL_USER` is set, otherwise the Windows
    integrated login is used. The integrated login only works on Windows,
    so a Linux host has to provide a SQL login.
    """
    parts = [
        f"Driver={{{SQL_DRIVER}}};",
        f"Server={SQL_SERVER};",
    ]
    if SQL_PORT:
        parts.append(f"Port={SQL_PORT};")
    parts.append(f"Database={DB_PATH};")
    if SQL_USER:
        parts.append(f"UID={SQL_USER};")
        parts.append(f"PWD={SQL_PASSWORD};")
    else:
        parts.append("Trusted_Connection=yes;")
    parts.append(f"Encrypt={'yes' if SQL_ENCRYPT else 'no'};")
    parts.append(
        f"TrustServerCertificate={'yes' if SQL_TRUST_CERT else 'no'};"
    )
    return "".join(parts)


def connect() -> pyodbc.Connection:
    """Return the shared connection, reconnecting if the server dropped it."""
    global _CONN
    if _CONN is None:
        _CONN = pyodbc.connect(_conn_str(), timeout=SQL_TIMEOUT, autocommit=False)
    return _CONN


def _reset_connection() -> None:
    global _CONN
    try:
        if _CONN is not None:
            _CONN.close()
    except pyodbc.Error:
        pass
    _CONN = None


def run(fn):
    """Run fn(connection) inside a transaction and commit it.

    Any exception rolls the transaction back. Without that, a failed
    function would leave its partial writes in the open transaction, and the
    next `run()` would commit them along with its own work.

    A dropped connection is retried once on a fresh connection. The retry
    is safe because the failed attempt is rolled back before it: the
    money is written with relative updates, so running the function twice
    would add the money twice.
    """
    with _lock:
        for attempt in range(2):
            con = None
            try:
                con = connect()
                result = fn(con)
                con.commit()
                return result
            except pyodbc.Error:
                if con is not None:
                    try:
                        con.rollback()
                    except pyodbc.Error:
                        pass
                # The connection may be the problem, so it is dropped and
                # the next attempt opens a new one.
                _reset_connection()
                if attempt:
                    raise
            except Exception:
                if con is not None:
                    try:
                        con.rollback()
                    except pyodbc.Error:
                        pass
                raise
        raise RuntimeError("unreachable")


def init() -> None:
    """Check the SQL Server database is reachable and the schema is loaded.

    A failure here is reported but not raised. The web container has to
    survive a database that is not up yet or that blinks, otherwise the
    hosting platform restarts it in a loop and it never recovers on its
    own. Every request that needs the ledger already handles a failed
    connection, and `/health` reports the database as down.
    """
    with _lock:
        try:
            con = connect()
        except pyodbc.Error as exc:
            logging.getLogger(__name__).warning(
                "Khong ket noi duoc SQL Server (%s). Web se thu lai o request "
                "sau.", exc
            )
            return
        try:
            cur = con.cursor()
            cur.execute("SELECT COUNT(*) FROM sys.tables WHERE name LIKE 'gacha[_]%'")
            count = cur.fetchone()[0]
            if not count:
                logging.getLogger(__name__).warning(
                    "Khong tim thay bang gacha_ trong SQL Server. "
                    "Hay nap jellyvale_full.sql truoc."
                )
                return
            con.commit()
        except Exception:
            _reset_connection()


def now() -> int:
    return int(time.time())


def row_dict(row) -> dict[str, Any] | None:
    """Convert a pyodbc Row into a plain dict."""
    if row is None:
        return None
    return {col[0]: row[idx] for idx, col in enumerate(row.cursor_description)}


def rows(items: Iterable) -> list[dict[str, Any]]:
    return [row_dict(item) for item in items]


def _cur(con: pyodbc.Cursor):
    return con.cursor()


# --------------------------------------------------------------------------- #
# Wallets
# --------------------------------------------------------------------------- #
def ensure_wallet(player: str, seed: int = 0, is_bot: bool = False) -> int:
    def inner(con) -> int:
        cur = _cur(con)
        cur.execute("SELECT balance FROM gacha_wallets WHERE player = ?", player)
        row = cur.fetchone()
        if row:
            return int(row[0])
        cur.execute(
            "INSERT INTO gacha_wallets (player, balance, is_bot, created_at) "
            "VALUES (?, ?, ?, ?)",
            player, max(0, int(seed)), 1 if is_bot else 0, now(),
        )
        if seed:
            cur.execute(
                "INSERT INTO gacha_tx (player, kind, amount, note, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                player, "seed", int(seed), "nap vi web", now(),
            )
        return max(0, int(seed))

    return run(inner)


def get_balance(player: str) -> int:
    def inner(con) -> int:
        cur = _cur(con)
        cur.execute("SELECT balance FROM gacha_wallets WHERE player = ?", player)
        row = cur.fetchone()
        return int(row[0]) if row else 0

    return run(inner)


def credit(player: str, amount: int, kind: str, note: str = "") -> int:
    amount = int(amount)
    if amount <= 0:
        return get_balance(player)

    def inner(con) -> int:
        cur = _cur(con)
        cur.execute(
            "UPDATE gacha_wallets SET balance = balance + ? WHERE player = ?",
            amount, player,
        )
        if cur.rowcount == 0:
            cur.execute(
                "INSERT INTO gacha_wallets (player, balance, is_bot, created_at) "
                "VALUES (?, ?, 0, ?)",
                player, amount, now(),
            )
        cur.execute(
            "INSERT INTO gacha_tx (player, kind, amount, note, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            player, kind, amount, note, now(),
        )
        cur.execute("SELECT balance FROM gacha_wallets WHERE player = ?", player)
        return int(cur.fetchone()[0])

    return run(inner)


def set_balance(player: str, amount: int, kind: str = "sync",
               note: str = "") -> int:
    """Set the absolute balance and log the delta.

    Used to mirror the live PikaMC balance into the local ledger: the web
    wallet then always matches what the server actually holds.
    """
    amount = max(0, int(amount))

    def inner(con) -> int:
        cur = _cur(con)
        cur.execute(
            "SELECT balance FROM gacha_wallets WHERE player = ?", player
        )
        row = cur.fetchone()
        old = int(row[0]) if row else 0
        delta = amount - old
        if row:
            cur.execute(
                "UPDATE gacha_wallets SET balance = ? WHERE player = ?",
                amount, player,
            )
        else:
            cur.execute(
                "INSERT INTO gacha_wallets (player, balance, is_bot, created_at) "
                "VALUES (?, ?, 0, ?)",
                player, amount, now(),
            )
        if delta:
            cur.execute(
                "INSERT INTO gacha_tx (player, kind, amount, note, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                player, kind, delta, note, now(),
            )
        return amount

    return run(inner)


def debit(player: str, amount: int, kind: str, note: str = "") -> int:
    amount = int(amount)
    if amount <= 0:
        return get_balance(player)

    def inner(con) -> int:
        cur = _cur(con)
        # The guard is in the UPDATE itself, so two requests that arrive
        # at the same time cannot both take the Coin. The row count says
        # how many rows changed, and a row that did not change is a
        # wallet that did not have enough.
        cur.execute(
            "UPDATE gacha_wallets SET balance = balance - ? "
            "WHERE player = ? AND balance >= ?",
            amount, player, amount,
        )
        if cur.rowcount == 0:
            # The wallet is missing or too light. Either way the Coin
            # cannot be taken, so the caller has to refund.
            raise ValueError("Khong du Coin.")
        cur.execute(
            "SELECT balance FROM gacha_wallets WHERE player = ?", player
        )
        balance = int(cur.fetchone()[0])
        cur.execute(
            "INSERT INTO gacha_tx (player, kind, amount, note, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            player, kind, -amount, note, now(),
        )
        return balance

    return run(inner)


def open_case_atomic(player: str, cost: int, prizes: list[dict[str, Any]],
                     case_id: str, pull_cost: int, is_bot: bool = False,
                     dry: bool = False) -> list[int]:
    """Debit the Coin and hand out the prizes in one transaction.

    The payout and the charge have to move together. If the charge was
    committed but the prize insert failed, the player would pay for
    nothing. If the prize was committed but the charge was not, the
    player would get the items for free.

    `prizes` are the public dicts of the items that were rolled. The
    returned list holds the inventory id of every prize, in the same
    order.
    """
    if not prizes:
        return []

    def inner(con) -> list[int]:
        cur = _cur(con)
        cur.execute(
            "UPDATE gacha_wallets SET balance = balance - ? "
            "WHERE player = ? AND balance >= ?",
            cost, player, cost,
        )
        if cur.rowcount == 0:
            raise ValueError("Khong du Coin.")
        cur.execute(
            "INSERT INTO gacha_tx (player, kind, amount, note, created_at) "
            "VALUES (?, 'open', ?, ?, ?)",
            player, -cost, f"{case_id} x{len(prizes)}", now(),
        )
        ids: list[int] = []
        for prize in prizes:
            cur.execute(
                """
                INSERT INTO gacha_inventory (
                    player, item_id, name, rarity, value, image, color, source,
                    status, case_id, created_at
                ) OUTPUT INSERTED.id
                VALUES (?, ?, ?, ?, ?, ?, ?, 'case', 'held', ?, ?)
                """,
                player, prize["id"], prize["name"], prize["rarity"],
                int(prize["coin"]), prize["image"], prize["color"],
                case_id, now(),
            )
            ids.append(int(cur.fetchone()[0]))
            cur.execute(
                """
                INSERT INTO gacha_drops (
                    player, is_bot, item_id, name, rarity, value, image, color,
                    case_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                player, 1 if is_bot else 0, prize["id"], prize["name"],
                prize["rarity"], int(prize["coin"]), prize["image"],
                prize["color"], case_id, now(),
            )
            cur.execute(
                """
                INSERT INTO gacha_pulls (
                    player, cost, prize_id, prize_name, rarity, prize_coin,
                    created_at, case_id, dry_run
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                player, pull_cost, prize["id"], prize["name"], prize["rarity"],
                int(prize["coin"]), now(), case_id, 1 if dry else 0,
            )
        return ids

    return run(inner)

# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #
def add_inventory(player: str, item, source: str, case_id: str = "") -> int:
    public = item.as_public() if hasattr(item, "as_public") else item

    def inner(con) -> int:
        cur = _cur(con)
        cur.execute(
            """
            INSERT INTO gacha_inventory (
                player, item_id, name, rarity, value, image, color, source, status,
                case_id, created_at
            ) OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'held', ?, ?)
            """,
            player, public["id"], public["name"], public["rarity"],
            int(public["coin"]), public["image"], public["color"], source,
            case_id, now(),
        )
        return int(cur.fetchone()[0])

    return run(inner)


def get_inventory_item(item_pk: int) -> dict[str, Any] | None:
    def inner(con) -> dict[str, Any] | None:
        cur = _cur(con)
        cur.execute("SELECT * FROM gacha_inventory WHERE id = ?", item_pk)
        return row_dict(cur.fetchone())

    return run(inner)


def list_inventory(player: str, status: str = "held") -> list[dict[str, Any]]:
    def inner(con) -> list[dict[str, Any]]:
        cur = _cur(con)
        cur.execute(
            "SELECT * FROM gacha_inventory WHERE player = ? AND status = ? "
            "ORDER BY value DESC, id DESC",
            player, status,
        )
        return rows(cur.fetchall())

    return run(inner)


def set_inventory_status(item_pks: list[int], status: str,
                        only_from: str | None = None) -> None:
    if not item_pks:
        return

    def inner(con) -> None:
        cur = _cur(con)
        for pk in item_pks:
            if only_from:
                cur.execute(
                    "UPDATE gacha_inventory SET status = ? "
                    "WHERE id = ? AND status = ?", status, pk, only_from,
                )
            else:
                cur.execute(
                    "UPDATE gacha_inventory SET status = ? WHERE id = ?", status, pk
                )

    run(inner)


def claim_inventory(item_pks: list[int], player: str) -> list[dict[str, Any]]:
    """Move items from `held` to `selling` in one transaction.

    The UPDATE only touches rows that are still `held` and still belong to
    the player, so two concurrent requests cannot both claim the same item.
    Rows that were already claimed are not returned, and the caller sees a
    short list and refuses the whole sale.
    """
    if not item_pks:
        return []

    def inner(con) -> list[dict[str, Any]]:
        cur = _cur(con)
        placeholders = ",".join("?" * len(item_pks))
        cur.execute(
            "UPDATE gacha_inventory SET status = 'selling' "
            f"WHERE id IN ({placeholders}) AND player = ? AND status = 'held'",
            *item_pks, player,
        )
        claimed = cur.rowcount
        if claimed != len(item_pks):
            raise ValueError("mot vai pham da duoc ban.")
        cur.execute(
            "SELECT * FROM gacha_inventory "
            f"WHERE id IN ({placeholders}) AND player = ?",
            *item_pks, player,
        )
        return rows(cur.fetchall())

    return run(inner)


def sell_items_atomic(player: str, item_pks: list[int], kind: str = "sell",
                      note: str = "") -> dict[str, Any] | None:
    """Claim the items, mark them sold and pay the money in one transaction.

    The three steps have to move together. If the claim was committed but
    the payout was not, the player would lose the items for nothing. If
    the payout was committed but the claim was not, the player could sell
    the same item twice.

    Returns None when the items were already claimed by someone else.
    """
    if not item_pks:
        return None

    def inner(con) -> dict[str, Any] | None:
        cur = _cur(con)
        placeholders = ",".join("?" * len(item_pks))
        cur.execute(
            "UPDATE gacha_inventory SET status = 'sold' "
            f"WHERE id IN ({placeholders}) AND player = ? AND status IN "
            "('held', 'selling')",
            *item_pks, player,
        )
        if cur.rowcount != len(item_pks):
            return None
        cur.execute(
            "SELECT * FROM gacha_inventory "
            f"WHERE id IN ({placeholders}) AND player = ?",
            *item_pks, player,
        )
        claimed = rows(cur.fetchall())
        total = sum(int(row["value"]) for row in claimed)
        cur.execute(
            "UPDATE gacha_wallets SET balance = balance + ? WHERE player = ?",
            total, player,
        )
        if cur.rowcount == 0:
            cur.execute(
                "INSERT INTO gacha_wallets (player, balance, is_bot, created_at) "
                "VALUES (?, ?, 0, ?)",
                player, total, now(),
            )
        cur.execute(
            "INSERT INTO gacha_tx (player, kind, amount, note, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            player, kind, total, note or f"{len(item_pks)} món", now(),
        )
        cur.execute(
            "SELECT balance FROM gacha_wallets WHERE player = ?", player
        )
        balance = int(cur.fetchone()[0])
        return {
            "sold": len(claimed),
            "amount": total,
            "balance": balance,
            "items": claimed,
        }

    return run(inner)


def claim_upgrade_stake(item_pk: int, player: str) -> dict[str, Any]:
    """Take the item that is being upgraded out of the bag.

    The UPDATE only touches a row that is still `held` and still belongs to
    the player, so two requests cannot upgrade the same item at the same
    time: the second one sees zero rows changed and is refused.
    """
    def inner(con) -> dict[str, Any]:
        cur = _cur(con)
        cur.execute(
            "UPDATE gacha_inventory SET status = 'upgrading' "
            "WHERE id = ? AND player = ? AND status = 'held'",
            item_pk, player,
        )
        if cur.rowcount != 1:
            raise ValueError("mon da duoc dung.")
        cur.execute("SELECT * FROM gacha_inventory WHERE id = ?", item_pk)
        return row_dict(cur.fetchone())

    return run(inner)


def release_upgrade_stake(item_pk: int) -> None:
    """Put a stake back into the bag when the upgrade could not be made."""
    def inner(con) -> None:
        cur = _cur(con)
        cur.execute(
            "UPDATE gacha_inventory SET status = 'held' "
            "WHERE id = ? AND status = 'upgrading'",
            item_pk,
        )

    run(inner)


# --------------------------------------------------------------------------- #
# Drops / pulls
# --------------------------------------------------------------------------- #
def record_drop(player: str, item, case_id: str, is_bot: bool = False) -> None:
    public = item.as_public() if hasattr(item, "as_public") else item

    def inner(con) -> None:
        cur = _cur(con)
        cur.execute(
            """
            INSERT INTO gacha_drops (
                player, is_bot, item_id, name, rarity, value, image, color,
                case_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            player, 1 if is_bot else 0, public["id"], public["name"],
            public["rarity"], int(public["coin"]), public["image"], public["color"],
            case_id, now(),
        )
        cur.execute(
            "DELETE FROM gacha_drops WHERE id NOT IN "
            "(SELECT TOP 200 id FROM gacha_drops ORDER BY id DESC)"
        )

    run(inner)


def recent_drops(limit: int = 30) -> list[dict[str, Any]]:
    def inner(con) -> list[dict[str, Any]]:
        cur = _cur(con)
        cur.execute(
            "SELECT TOP (?) * FROM gacha_drops ORDER BY id DESC", limit
        )
        return rows(cur.fetchall())

    return run(inner)


def record_pull(player: str, cost: int, prize, case_id: str = "",
                dry: bool = False) -> None:
    public = prize.as_public() if hasattr(prize, "as_public") else prize

    def inner(con) -> None:
        cur = _cur(con)
        cur.execute(
            """
            INSERT INTO gacha_pulls (
                player, cost, prize_id, prize_name, rarity, prize_coin,
                created_at, case_id, dry_run
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            player, cost, public["id"], public["name"], public["rarity"],
            int(public["coin"]), now(), case_id, 1 if dry else 0,
        )

    run(inner)


def record_upgrade(player: str, stake: dict, target: dict, chance: float,
                   roll: float, won: bool) -> None:
    def inner(con) -> None:
        cur = _cur(con)
        cur.execute(
            """
            INSERT INTO gacha_upgrades (
                player, stake_name, stake_value, target_name, target_value,
                chance, roll, won, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            player, stake["name"], int(stake["coin"]), target["name"],
            int(target["coin"]), chance, roll, 1 if won else 0, now(),
        )

    run(inner)


# --------------------------------------------------------------------------- #
# Bonus
# --------------------------------------------------------------------------- #
def last_bonus(player: str) -> int:
    def inner(con) -> int:
        cur = _cur(con)
        cur.execute("SELECT last_claim FROM gacha_bonus WHERE player = ?", player)
        row = cur.fetchone()
        return int(row[0]) if row else 0

    return run(inner)


def claim_bonus_slot(player: str, since: int) -> bool:
    """Take the daily bonus slot, or report that it was already taken.

    The UPDATE only touches a row whose last claim is older than `since`,
    so two requests at the same time cannot both take the bonus: the
    second one sees zero rows changed.
    """
    stamp = now()

    def inner(con) -> bool:
        cur = _cur(con)
        cur.execute(
            "UPDATE gacha_bonus SET last_claim = ? "
            "WHERE player = ? AND last_claim < ?",
            stamp, player, since,
        )
        if cur.rowcount == 1:
            return True
        cur.execute(
            "SELECT last_claim FROM gacha_bonus WHERE player = ?", player
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO gacha_bonus (player, last_claim) VALUES (?, ?)",
                player, stamp,
            )
            return True
        return False

    return run(inner)


def claim_bonus_and_credit(player: str, amount: int, since: int) -> bool:
    """Take the daily bonus slot and pay the prize in one transaction.

    The slot and the money have to move together. If the slot were taken
    first and the money failed to arrive, the player would lose the day
    with nothing to show for it. If the money arrived first and the slot
    failed, the player could claim the bonus over and over.

    Returns False when the slot was already taken today.
    """
    stamp = now()

    def inner(con) -> bool:
        cur = _cur(con)
        cur.execute(
            "UPDATE gacha_bonus SET last_claim = ? "
            "WHERE player = ? AND last_claim < ?",
            stamp, player, since,
        )
        if cur.rowcount == 0:
            cur.execute(
                "SELECT last_claim FROM gacha_bonus WHERE player = ?", player
            )
            row = cur.fetchone()
            if row is not None:
                return False
            cur.execute(
                "INSERT INTO gacha_bonus (player, last_claim) VALUES (?, ?)",
                player, stamp,
            )
        # The money goes in the same transaction, so the slot and the
        # prize always agree.
        cur.execute(
            "UPDATE gacha_wallets SET balance = balance + ? WHERE player = ?",
            amount, player,
        )
        if cur.rowcount == 0:
            cur.execute(
                "INSERT INTO gacha_wallets (player, balance, is_bot, created_at) "
                "VALUES (?, ?, 0, ?)",
                player, amount, now(),
            )
        cur.execute(
            "INSERT INTO gacha_tx (player, kind, amount, note, created_at) "
            "VALUES (?, 'bonus', ?, ?, ?)",
            player, amount, "vòng bonus ngày", now(),
        )
        return True

    return run(inner)


# --------------------------------------------------------------------------- #
# Battles
# --------------------------------------------------------------------------- #
def create_battle(host: str, case_id: str, rounds: int, slots: int, mode: str,
                  paid: int, host_is_bot: bool) -> int:
    def inner(con) -> int:
        cur = _cur(con)
        cur.execute(
            """
            INSERT INTO gacha_battles (
                host, case_id, rounds, slots, mode, status, created_at
            ) OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, 'WAITING', ?)
            """,
            host, case_id, rounds, slots, mode, now(),
        )
        battle_id = int(cur.fetchone()[0])
        cur.execute(
            """
            INSERT INTO gacha_battle_players (
                battle_id, player, is_bot, slot, total, paid
            ) VALUES (?, ?, ?, 0, 0, ?)
            """,
            battle_id, host, 1 if host_is_bot else 0, paid,
        )
        return battle_id

    return run(inner)


def delete_battle(battle_id: int) -> None:
    """Remove a battle that was never paid for.

    Used when the server refused the payment: the seat must not stay in the
    lobby, and the drops that were rolled must not stay with the winner.
    """
    def inner(con) -> None:
        cur = _cur(con)
        cur.execute("DELETE FROM gacha_battle_drops WHERE battle_id = ?", battle_id)
        cur.execute("DELETE FROM gacha_battle_players WHERE battle_id = ?", battle_id)
        cur.execute("DELETE FROM gacha_battles WHERE id = ?", battle_id)

    run(inner)


def get_battle(battle_id: int) -> dict[str, Any] | None:
    def inner(con) -> dict[str, Any] | None:
        cur = _cur(con)
        cur.execute("SELECT * FROM gacha_battles WHERE id = ?", battle_id)
        battle = row_dict(cur.fetchone())
        if not battle:
            return None
        cur.execute(
            "SELECT * FROM gacha_battle_players WHERE battle_id = ? ORDER BY slot",
            battle_id,
        )
        battle["players"] = rows(cur.fetchall())
        cur.execute(
            "SELECT * FROM gacha_battle_drops WHERE battle_id = ? ORDER BY round, id",
            battle_id,
        )
        battle["drops"] = rows(cur.fetchall())
        return battle

    return run(inner)


def list_battles() -> dict[str, list[dict[str, Any]]]:
    def inner(con) -> dict[str, list[dict[str, Any]]]:
        cur = _cur(con)
        cur.execute(
            """
            SELECT TOP 40 b.*, s.seated
            FROM gacha_battles b
            OUTER APPLY (
                SELECT COUNT(p.player) AS seated
                FROM gacha_battle_players p
                WHERE p.battle_id = b.id
            ) s
            WHERE b.status IN ('WAITING', 'RUNNING')
            ORDER BY b.id DESC
            """
        )
        open_rows = rows(cur.fetchall())
        cur.execute(
            """
            SELECT TOP 12 b.*, s.seated
            FROM gacha_battles b
            OUTER APPLY (
                SELECT COUNT(p.player) AS seated
                FROM gacha_battle_players p
                WHERE p.battle_id = b.id
            ) s
            WHERE b.status = 'FINISHED'
            ORDER BY b.id DESC
            """
        )
        finished = rows(cur.fetchall())
        ids = [row["id"] for row in open_rows + finished]
        players_by: dict[int, list] = {}
        if ids:
            placeholders = ",".join("?" * len(ids))
            cur.execute(
                f"SELECT * FROM gacha_battle_players WHERE battle_id IN ({placeholders}) "
                "ORDER BY slot",
                *ids,
            )
            for player in cur.fetchall():
                p = row_dict(player)
                players_by.setdefault(p["battle_id"], []).append(p)
        for row in open_rows + finished:
            row["players"] = players_by.get(row["id"], [])
        return {"open": open_rows, "finished": finished}
    return run(inner)


def join_battle(battle_id: int, player: str, is_bot: bool, paid: int) -> dict:
    def inner(con) -> dict:
        cur = _cur(con)
        cur.execute("SELECT * FROM gacha_battles WHERE id = ?", battle_id)
        battle = row_dict(cur.fetchone())
        if not battle:
            raise ValueError("Khong co tran nay.")
        if battle["status"] != "WAITING":
            raise ValueError("Tran da bat dau.")
        cur.execute(
            "SELECT player FROM gacha_battle_players WHERE battle_id = ? AND player = ?",
            battle_id, player,
        )
        if cur.fetchone():
            raise ValueError("Ban da ngoi tran nay.")
        cur.execute(
            "SELECT COUNT(*) FROM gacha_battle_players WHERE battle_id = ?", battle_id
        )
        seated = int(cur.fetchone()[0])
        if seated >= battle["slots"]:
            raise ValueError("Het cho.")
        cur.execute(
            """
            INSERT INTO gacha_battle_players (
                battle_id, player, is_bot, slot, total, paid
            ) VALUES (?, ?, ?, ?, 0, ?)
            """,
            battle_id, player, 1 if is_bot else 0, seated, paid,
        )
        battle["seated"] = seated + 1
        return battle

    return run(inner)


def leave_battle(battle_id: int, player: str) -> bool:
    """Remove a player from a waiting battle.

    Returns True when a seat was actually freed, so the caller knows the
    local debit has to be refunded.
    """
    def inner(con) -> bool:
        cur = _cur(con)
        cur.execute(
            "DELETE FROM gacha_battle_players WHERE battle_id = ? AND player = ?",
            battle_id, player,
        )
        return cur.rowcount > 0

    return run(inner)


def set_battle_status(battle_id: int, status: str, **extra) -> None:
    fields = ["status = ?"]
    values: list[Any] = [status]
    for key in ("winner", "started_at", "finished_at"):
        if key in extra:
            fields.append(f"{key} = ?")
            values.append(extra[key])
    values.append(battle_id)

    def inner(con) -> None:
        cur = _cur(con)
        cur.execute(
            f"UPDATE gacha_battles SET {', '.join(fields)} WHERE id = ?", *values
        )

    run(inner)


def finish_battle(battle_id: int, totals: dict[str, int],
                  drops: list[dict[str, Any]], winner: str,
                  items: list[dict[str, Any]],
                  drops_log: list[dict[str, Any]] | None = None) -> None:
    """Save the battle result and give the items to the winner.

    Both happen in one transaction. When they were two separate writes, a
    failure between them left the battle marked FINISHED with a winner,
    while the items never reached the bag and the winner lost them for
    good. The transaction rolls both back, so the battle stays open.
    """
    stamp = now()

    def inner(con) -> None:
        cur = _cur(con)
        for player, total in totals.items():
            cur.execute(
                "UPDATE gacha_battle_players SET total = ? "
                "WHERE battle_id = ? AND player = ?",
                total, battle_id, player,
            )
        for drop in drops:
            cur.execute(
                """
                INSERT INTO gacha_battle_drops (
                    battle_id, player, round, item_id, name, rarity, value,
                    image, color
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                battle_id, drop["player"], drop["round"], drop["id"], drop["name"],
                drop["rarity"], drop["value"], drop["image"], drop["color"],
            )
        for item in items:
            cur.execute(
                """
                INSERT INTO gacha_inventory (
                    player, item_id, name, rarity, value, image, color, source,
                    status, case_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'battle', 'held', ?, ?)
                """,
                winner, item["id"], item["name"], item["rarity"],
                int(item["coin"]), item["image"], item["color"],
                item.get("case_id", ""), stamp,
            )
        for entry in drops_log or []:
            cur.execute(
                """
                INSERT INTO gacha_drops (
                    player, is_bot, item_id, name, rarity, value, image, color,
                    case_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                entry["player"], 1 if entry["is_bot"] else 0, entry["id"],
                entry["name"], entry["rarity"], int(entry["coin"]),
                entry["image"], entry["color"], entry.get("case_id", ""), stamp,
            )
        cur.execute(
            "UPDATE gacha_battles SET status = 'FINISHED', winner = ?, "
            "started_at = COALESCE(started_at, ?), finished_at = ? WHERE id = ?",
            winner, stamp, stamp, battle_id,
        )
        cur.execute(
            "DELETE FROM gacha_drops WHERE id NOT IN "
            "(SELECT TOP 200 id FROM gacha_drops ORDER BY id DESC)"
        )

    run(inner)


def cleanup_old_battles(days: int = 30) -> int:
    """Remove battles that finished long ago.

    The bot loop creates battles all day, so the table grows without
    limit. The lobby only ever shows the newest ones, so the old ones
    are dead weight. The battle drops go with them.
    """
    cutoff = now() - days * 24 * 3600

    def inner(con) -> int:
        cur = _cur(con)
        cur.execute(
            "DELETE FROM gacha_battle_drops WHERE battle_id IN "
            "(SELECT id FROM gacha_battles WHERE status = 'FINISHED' "
            "AND finished_at IS NOT NULL AND finished_at < ?)",
            cutoff,
        )
        cur.execute(
            "DELETE FROM gacha_battle_players WHERE battle_id IN "
            "(SELECT id FROM gacha_battles WHERE status = 'FINISHED' "
            "AND finished_at IS NOT NULL AND finished_at < ?)",
            cutoff,
        )
        cur.execute(
            "DELETE FROM gacha_battles WHERE status = 'FINISHED' "
            "AND finished_at IS NOT NULL AND finished_at < ?",
            cutoff,
        )
        return cur.rowcount

    return run(inner)


def waiting_battles() -> list[dict[str, Any]]:
    def inner(con) -> list[dict[str, Any]]:
        cur = _cur(con)
        cur.execute(
            """
            SELECT b.*, s.seated
            FROM gacha_battles b
            OUTER APPLY (
                SELECT COUNT(p.player) AS seated
                FROM gacha_battle_players p
                WHERE p.battle_id = b.id
            ) s
            WHERE b.status = 'WAITING'
            ORDER BY b.id ASC
            """
        )
        return rows(cur.fetchall())

    return run(inner)


def battle_player_names(battle_id: int) -> set[str]:
    def inner(con) -> set[str]:
        cur = _cur(con)
        cur.execute(
            "SELECT player FROM gacha_battle_players WHERE battle_id = ?", battle_id
        )
        return {row[0] for row in cur.fetchall()}

    return run(inner)


def recent_tx(player: str, limit: int = 20) -> list[dict[str, Any]]:
    def inner(con) -> list[dict[str, Any]]:
        cur = _cur(con)
        cur.execute(
            "SELECT TOP (?) * FROM gacha_tx WHERE player = ? ORDER BY id DESC",
            limit, player,
        )
        return rows(cur.fetchall())

    return run(inner)


def stats() -> dict[str, Any]:
    def inner(con) -> dict[str, Any]:
        cur = _cur(con)
        cur.execute(
            """
            SELECT COUNT(*) AS n, COALESCE(SUM(cost), 0) AS spent,
                   COALESCE(SUM(prize_coin), 0) AS paid
            FROM gacha_pulls
            """
        )
        total = row_dict(cur.fetchone())
        cur.execute(
            "SELECT rarity, COUNT(*) AS n, COALESCE(SUM(prize_coin), 0) AS paid "
            "FROM gacha_pulls GROUP BY rarity ORDER BY n DESC"
        )
        by_rarity = rows(cur.fetchall())
        cur.execute(
            """
            SELECT TOP 40 player, cost, prize_name, rarity, prize_coin, created_at,
                   case_id, dry_run
            FROM gacha_pulls ORDER BY id DESC
            """
        )
        recent = rows(cur.fetchall())
        cur.execute(
            """
            SELECT TOP 15 player, COUNT(*) AS n, COALESCE(SUM(cost), 0) AS spent
            FROM gacha_pulls GROUP BY player ORDER BY n DESC
            """
        )
        top = rows(cur.fetchall())

        def scalar(sql: str) -> int:
            cur.execute(sql)
            return int(cur.fetchone()[0])

        battles_n = scalar(
            "SELECT COUNT(*) FROM gacha_battles WHERE status = 'FINISHED'")
        sells = scalar(
            "SELECT COUNT(*) FROM gacha_inventory WHERE status = 'sold'")
        held = scalar(
            "SELECT COUNT(*) FROM gacha_inventory WHERE status = 'held'")
        cur.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(won), 0) AS wins FROM gacha_upgrades"
        )
        upgrades = row_dict(cur.fetchone())
        users_n = scalar(
            "SELECT COUNT(*) FROM gacha_wallets WHERE is_bot = 0")
        return {
            "pulls": total["n"],
            "spent": total["spent"],
            "paid": total["paid"],
            "net": total["spent"] - total["paid"],
            "by_rarity": by_rarity,
            "recent": recent,
            "top": top,
            "battles": battles_n,
            "sells": sells,
            "held": held,
            "upgrades": upgrades["n"],
            "upgrade_wins": upgrades["wins"],
            "users": users_n,
        }

    return run(inner)


# --------------------------------------------------------------------------- #
# Admin queries
# --------------------------------------------------------------------------- #
def log_admin(action: str, target: str = "", detail: str = "",
              admin: str = "") -> None:
    """Record what an admin did.

    Money moves and bans have to be traceable: without this there is no
    way to tell afterwards who changed a wallet.
    """
    def inner(con) -> None:
        if not _audit_available(con):
            return
        cur = _cur(con)
        cur.execute(
            "INSERT INTO gacha_admin_log (admin, action, target, detail, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            admin, action, target, detail, now(),
        )

    try:
        run(inner)
    except Exception:
        # The log must never break the action it is recording.
        pass


def list_admin_log(limit: int = 100) -> list[dict[str, Any]]:
    def inner(con) -> list[dict[str, Any]]:
        if not _audit_available(con):
            return []
        cur = _cur(con)
        cur.execute(
            "SELECT TOP (?) * FROM gacha_admin_log ORDER BY id DESC", limit
        )
        return rows(cur.fetchall())

    return run(inner)


def list_wallets(search: str = "", include_bots: bool = True,
                 limit: int = 100) -> list[dict[str, Any]]:
    """Wallets for the admin player list, richest first.

    `search` matches a name that starts with or contains the text; the
    parameterised query keeps a quote in the box from breaking the SQL.
    """
    def inner(con) -> list[dict[str, Any]]:
        cur = _cur(con)
        where = []
        params: list[Any] = []
        if not include_bots:
            where.append("w.is_bot = 0")
        if search:
            where.append("w.player LIKE ?")
            params.append(f"%{search}%")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        banned = "(SELECT COUNT(*) FROM gacha_bans b WHERE b.player = w.player) AS banned" \
            if _bans_available(con) else "0 AS banned"
        cur.execute(
            f"""
            SELECT TOP (?) w.player, w.balance, w.is_bot, w.created_at,
                   (SELECT COUNT(*) FROM gacha_pulls p
                     WHERE p.player = w.player) AS pulls,
                   (SELECT COALESCE(SUM(p.cost), 0) FROM gacha_pulls p
                     WHERE p.player = w.player) AS spent,
                   (SELECT COUNT(*) FROM gacha_inventory i
                     WHERE i.player = w.player AND i.status = 'held') AS held,
                   {banned}
            FROM gacha_wallets w
            {clause}
            ORDER BY w.balance DESC, w.player ASC
            """,
            limit, *params,
        )
        return rows(cur.fetchall())

    return run(inner)


def list_tx_all(search: str = "", kind: str = "", limit: int = 100
                ) -> list[dict[str, Any]]:
    """Transaction ledger across every player, for the admin console."""
    def inner(con) -> list[dict[str, Any]]:
        cur = _cur(con)
        where = []
        params: list[Any] = []
        if search:
            where.append("player LIKE ?")
            params.append(f"%{search}%")
        if kind:
            where.append("kind = ?")
            params.append(kind)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        cur.execute(
            f"""
            SELECT TOP (?) * FROM gacha_tx
            {clause}
            ORDER BY id DESC
            """,
            limit, *params,
        )
        return rows(cur.fetchall())

    return run(inner)


def list_inventory_all(search: str = "", status: str = "", limit: int = 100
                       ) -> list[dict[str, Any]]:
    """Inventory across every player, for the admin console."""
    def inner(con) -> list[dict[str, Any]]:
        cur = _cur(con)
        where = []
        params: list[Any] = []
        if search:
            where.append("player LIKE ?")
            params.append(f"%{search}%")
        if status:
            where.append("status = ?")
            params.append(status)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        cur.execute(
            f"""
            SELECT TOP (?) * FROM gacha_inventory
            {clause}
            ORDER BY id DESC
            """,
            limit, *params,
        )
        return rows(cur.fetchall())

    return run(inner)


def admin_battles(limit: int = 60) -> list[dict[str, Any]]:
    """Every battle with its seats, newest first."""
    def inner(con) -> list[dict[str, Any]]:
        cur = _cur(con)
        cur.execute(
            "SELECT TOP (?) * FROM gacha_battles ORDER BY id DESC", limit
        )
        battles = rows(cur.fetchall())
        if not battles:
            return []
        ids = [row["id"] for row in battles]
        placeholders = ",".join("?" * len(ids))
        cur.execute(
            f"SELECT * FROM gacha_battle_players WHERE battle_id IN ({placeholders}) "
            "ORDER BY slot",
            *ids,
        )
        seats: dict[int, list] = {}
        for seat in cur.fetchall():
            row = row_dict(seat)
            seats.setdefault(row["battle_id"], []).append(row)
        for row in battles:
            row["players"] = seats.get(row["id"], [])
        return battles

    return run(inner)


# --------------------------------------------------------------------------- #
# Optional tables
# --------------------------------------------------------------------------- #
# The bans table and the admin log were added after the first release, so an
# older database may not have them yet. The first query that fails marks the
# table as missing and the feature turns itself off instead of breaking
# every game request.
_bans_ready: bool | None = None
_audit_ready: bool | None = None
# The cached ban list and when it was filled.
_ban_cache: tuple[float, set[str]] | None = None
_ban_lock = threading.Lock()
_BAN_CACHE_SECONDS = 5.0


def _table_exists(con, name: str) -> bool:
    cur = _cur(con)
    cur.execute("SELECT COUNT(*) FROM sys.tables WHERE name = ?", name)
    return bool(cur.fetchone()[0])


def _bans_available(con) -> bool:
    global _bans_ready
    if _bans_ready is None:
        _bans_ready = _table_exists(con, "gacha_bans")
    return _bans_ready


def _audit_available(con) -> bool:
    global _audit_ready
    if _audit_ready is None:
        _audit_ready = _table_exists(con, "gacha_admin_log")
    return _audit_ready


# --------------------------------------------------------------------------- #
# Bans
# --------------------------------------------------------------------------- #


def _bans_available(con) -> bool:
    global _bans_ready
    if _bans_ready is None:
        cur = _cur(con)
        cur.execute("SELECT COUNT(*) FROM sys.tables WHERE name = 'gacha_bans'")
        _bans_ready = bool(cur.fetchone()[0])
    return _bans_ready


def list_bans() -> list[dict[str, Any]]:
    def inner(con) -> list[dict[str, Any]]:
        if not _bans_available(con):
            return []
        cur = _cur(con)
        cur.execute("SELECT * FROM gacha_bans ORDER BY created_at DESC")
        return rows(cur.fetchall())

    return run(inner)


def is_banned(player: str) -> bool:
    """True when the player is banned.

    The ban list is small and changes rarely, so it is cached for a few
    seconds. Without the cache every single game request would hit the
    database, and the ban check is on the hot path.
    """
    global _ban_cache
    with _ban_lock:
        stamp = _ban_cache[0] if _ban_cache else 0.0
        if _ban_cache and time.time() - stamp < _BAN_CACHE_SECONDS:
            return player.lower() in _ban_cache[1]
    names = _banned_names()
    with _ban_lock:
        _ban_cache = (time.time(), names)
    return player.lower() in names


def _banned_names() -> set[str]:
    """The lower-cased names of every banned account."""
    def inner(con) -> set[str]:
        if not _bans_available(con):
            return set()
        cur = _cur(con)
        cur.execute("SELECT player FROM gacha_bans")
        return {row[0].lower() for row in cur.fetchall()}

    try:
        return run(inner)
    except Exception:
        return set()


def _invalidate_ban_cache() -> None:
    global _ban_cache
    with _ban_lock:
        _ban_cache = None


def set_ban(player: str, reason: str = "") -> None:
    def inner(con) -> None:
        if not _bans_available(con):
            raise RuntimeError("Bang gacha_bans chua ton tai.")
        cur = _cur(con)
        cur.execute(
            "MERGE gacha_bans AS t USING (SELECT ? AS player) AS s "
            "ON LOWER(t.player) = LOWER(s.player) "
            "WHEN MATCHED THEN UPDATE SET reason = ?, created_at = ? "
            "WHEN NOT MATCHED THEN INSERT (player, reason, created_at) "
            "VALUES (?, ?, ?);",
            player, reason, now(), player, reason, now(),
        )

    run(inner)
    _invalidate_ban_cache()


def lift_ban(player: str) -> None:
    def inner(con) -> None:
        if not _bans_available(con):
            return
        cur = _cur(con)
        cur.execute(
            "DELETE FROM gacha_bans WHERE LOWER(player) = LOWER(?)", player
        )

    run(inner)
    _invalidate_ban_cache()


# --------------------------------------------------------------------------- #
# Admins
# --------------------------------------------------------------------------- #
# The web console keeps its own admin list in `gacha_admins`. It is kept
# in step with the LuckPerms group on the Minecraft server: an account
# that is an admin on the server is an admin here too, and the other way
# round.
_admin_ready: bool | None = None


def _admins_available(con) -> bool:
    global _admin_ready
    if _admin_ready is None:
        _admin_ready = _table_exists(con, "gacha_admins")
    return _admin_ready


def list_admins() -> list[str]:
    """The accounts the web console lets in, lower-cased."""
    def inner(con) -> list[str]:
        if not _admins_available(con):
            return []
        cur = _cur(con)
        cur.execute("SELECT name FROM gacha_admins")
        return [row[0].lower() for row in cur.fetchall()]

    return run(inner)


def list_admin_records() -> list[dict[str, Any]]:
    """The web admin list with where each entry came from."""
    def inner(con) -> list[dict[str, Any]]:
        if not _admins_available(con):
            return []
        cur = _cur(con)
        cur.execute("SELECT name, source, created_at FROM gacha_admins "
                    "ORDER BY name")
        return rows(cur.fetchall())

    return run(inner)


def add_admin(name: str, source: str = "web") -> None:
    """Put an account on the web admin list."""
    def inner(con) -> None:
        if not _admins_available(con):
            raise RuntimeError("Bang gacha_admins chua ton tai.")
        cur = _cur(con)
        cur.execute(
            "MERGE gacha_admins AS t USING (SELECT ? AS name) AS s "
            "ON LOWER(t.name) = LOWER(s.name) "
            "WHEN MATCHED THEN UPDATE SET source = ? "
            "WHEN NOT MATCHED THEN INSERT (name, source, created_at) "
            "VALUES (?, ?, ?);",
            name, source, name, source, now(),
        )

    run(inner)


def remove_admin(name: str) -> None:
    """Take an account off the web admin list."""
    def inner(con) -> None:
        if not _admins_available(con):
            return
        cur = _cur(con)
        cur.execute("DELETE FROM gacha_admins WHERE LOWER(name) = LOWER(?)",
                    name)

    run(inner)


def replace_admins(names: list[str], source: str = "server") -> None:
    """Replace the server-sourced entries with the given list.

    The entries that were added by hand on the web are kept: only the
    ones that were copied from the server are replaced.
    """
    def inner(con) -> None:
        if not _admins_available(con):
            return
        cur = _cur(con)
        cur.execute("DELETE FROM gacha_admins WHERE source = ?", source)
        for name in names:
            cur.execute(
                "IF NOT EXISTS (SELECT 1 FROM gacha_admins "
                "WHERE LOWER(name) = LOWER(?)) "
                "INSERT INTO gacha_admins (name, source, created_at) "
                "VALUES (?, ?, ?);",
                name, name, source, now(),
            )

    run(inner)
