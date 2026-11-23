"""Generate a complete SQL Server (T-SQL) dump of every JellyVale data source.

Sources merged into one file:
  * plugin databases downloaded from the PikaMC panel (SQLite -> T-SQL)
  * the server's own consolidated dump for modules with no downloadable file
  * the local web gacha ledger (data/gacha.db) -> GACHA_* schema

Run:  python tools/export_sqlserver.py --out jellyvale_full.sql
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import PIKA_API_KEY, PIKA_BASE_URL  # noqa: E402

SRV = "de021d06-8c2d-40c9-b470-31c5eb240d92"
BASE = PIKA_BASE_URL
H = {"Authorization": f"Bearer {PIKA_API_KEY}", "Accept": "application/json"}
ROOT = Path(__file__).resolve().parent.parent
DL = ROOT / "downloads"

# plugin -> (remote path, table prefix)
REMOTE_DATABASES: list[tuple[str, str, str]] = [
    ("AdvancedRedeem", "/plugins/AdvancedRedeem/data.db", "advancedredeem"),
    ("AuthMe", "/plugins/AuthMe/authme.db", "authme"),
    ("Boombox", "/plugins/Boombox/storage.db", "boombox"),
    ("ExcellentCrates", "/plugins/ExcellentCrates/data.db", "excellentcrates"),
    ("ExcellentEconomy", "/plugins/ExcellentEconomy/data.db", "excellenteconomy"),
    ("Floodgate", "/plugins/floodgate/linked-players.db", "floodgate"),
    ("Nightcore", "/plugins/nightcore/data.db", "nightcore"),
    ("PlayerPoints", "/plugins/PlayerPoints/playerpoints.db", "playerpoints"),
    ("VJobs", "/plugins/VJobs/local.db", "vjobs"),
    ("zAuctionHouse", "/plugins/zAuctionHouse/database.db", "zauctionhouse"),
    ("zMenu", "/plugins/zMenu/database.db", "zmenu"),
    ("EconomyShopGUI", "/plugins/EconomyShopGUI/transactions/transactions.db", "economyshopgui"),
    ("GSit", "/plugins/GSit/data/data.db", "gsit"),
    ("WorldGuard", "/plugins/WorldGuard/cache/profiles.sqlite", "worldguard"),
    ("CoreProtect", "/plugins/CoreProtect/database.db", "coreprotect"),
]

# Tables whose data is too large to inline (CoreProtect block/entity logs).
SKIP_TABLES: dict[str, set[str]] = {
    "CoreProtect": {"co_block", "co_entity"},
}

SECTION_PREFIX = {
    "LUCKPERMS": "luckperms",
    "SIMPLELOGIN": "simplelogin",
    "EXCELLENTECONOMY": "excellenteconomy",
    "ZAUCTIONHOUSE": "zauctionhouse",
    "ECONOMYSHOPGUI": "economyshopgui",
    "ZMENU": "zmenu",
    "GSIT": "gsit",
    "WORLDGUARD": "worldguard",
    "GRIEFPREVENTION": "griefprevention",
    "SETHOME": "sethome",
    "EXCELLENTCRATES": "excellentcrates",
    "NIGHTCORE": "nightcore",
    "FLOODGATE": "floodgate",
    "BETTERTEAMS": "betterteams",
    "COREPROTECT": "coreprotect",
}

DEFAULT_MAP = {
    "CURRENT_TIMESTAMP": "GETUTCDATE()",
    "NULL": "NULL",
}


# --------------------------------------------------------------------------- #
# Type / literal helpers
# --------------------------------------------------------------------------- #
def tsql_type(sqlite_type: str, *, identity: bool = False,
              key: bool = False, key_cols: int = 1) -> str:
    """Map a SQLite type to a T-SQL type. NOT NULL is handled by the caller."""
    t = (sqlite_type or "").upper()
    if identity:
        return "INT IDENTITY(1,1)"
    if "INT" in t:
        # BIGINT: plugin tables store epoch-millisecond timestamps that
        # overflow INT.
        return "BIGINT"
    if any(k in t for k in ("REAL", "FLOA", "DOUB", "NUMERIC", "DECIMAL")):
        return "FLOAT"
    if "BOOL" in t or t == "BIT":
        return "BIT"
    if "BLOB" in t:
        return "VARBINARY(MAX)"
    if any(k in t for k in ("TIMESTAMP", "DATETIME", "DATE", "TIME")):
        return "DATETIME2(3)"
    if any(k in t for k in ("CHAR", "VARCHAR", "TEXT", "CLOB", "STRING")):
        # A key column cannot be NVARCHAR(MAX) -> cap it, and share the
        # 900-byte clustered-index budget between composite key columns.
        if key:
            return "NVARCHAR(450)" if key_cols <= 1 else \
                f"NVARCHAR({max(32, 440 // key_cols)})"
        if t.startswith("TEXT") or "LONGTEXT" in t or t == "CLOB" or t == "STRING":
            return "NVARCHAR(MAX)"
        return "NVARCHAR(255)"
    return "NVARCHAR(255)"


def ident(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def safe_table(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not name or not name[0].isalpha():
        name = "t_" + name
    return name[:120]


def lit(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if not raw:
            return "0x"
        return "0x" + raw.hex()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return "NULL"
        return repr(round(value, 10))
    text = str(value)
    return "N'" + text.replace("'", "''") + "'"


def lit_cell(value: Any, is_time: bool = False) -> str:
    """Render a value, converting Unix-epoch integers stored in time columns.

    Plugins are inconsistent: some store seconds, others milliseconds.
    1e11 seconds is year 5138, 1e11 milliseconds is 1973 -- so anything
    above 1e11 is milliseconds.
    """
    if is_time and isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = int(value)
        if seconds >= 100_000_000_000:
            seconds //= 1000
        return f"DATEADD(SECOND, {seconds}, CAST('1970-01-01' AS DATETIME2(3)))"
    return lit(value)


def default_expr(raw: str, ctype: str) -> str | None:
    """Render a SQLite default value as a T-SQL default, type-aware."""
    d = (raw or "").strip()
    if not d:
        return None
    up = d.upper()
    if up == "CURRENT_TIMESTAMP":
        return "GETUTCDATE()"
    t = (ctype or "").upper()
    is_num = any(k in t for k in ("INT", "REAL", "FLOA", "DOUB", "DEC", "NUM"))
    is_date = any(k in t for k in ("TIMESTAMP", "DATETIME", "DATE", "TIME"))
    if d.startswith("'") and d.endswith("'"):
        inner = d[1:-1]
        if is_num:
            try:
                return str(float(inner)) if "." in inner else str(int(inner))
            except ValueError:
                return None
        if is_date:
            # Plugins store '0' as a placeholder epoch -> drop the default.
            return None
        return "N'" + inner.replace("'", "''") + "'"
    if re.fullmatch(r"-?\d+", d):
        # A raw epoch millisecond value is far outside INT range -> drop it.
        if abs(int(d)) > 2_000_000_000:
            return None
        return d
    if re.fullmatch(r"-?\d+\.\d+", d):
        return d
    if up in ("NULL", "TRUE", "FALSE"):
        return "1" if up == "TRUE" else "0" if up == "FALSE" else "NULL"
    return None


def is_identity(ctype: str, *, pk: bool = False, pk_count: int = 1) -> bool:
    """True when a SQLite column is an AUTOINCREMENT rowid alias.

    In SQLite a column declared exactly `INTEGER PRIMARY KEY` is an alias for
    the rowid and is filled in automatically. A composite primary key is not.
    """
    t = (ctype or "").upper().replace(" ", "")
    if t.startswith("INTEGER") and "AUTOINCREMENT" in t.replace("_", ""):
        return True
    return pk and pk_count == 1 and t == "INTEGER"


def is_time_type(ctype: str) -> bool:
    t = (ctype or "").upper()
    return any(k in t for k in ("TIMESTAMP", "DATETIME", "DATE", "TIME"))


def key_type(sqlite_type: str, key_cols: int) -> str:
    """Key columns must fit in a 900-byte clustered index.

    A single-column key may be NVARCHAR(450); a composite key has to share
    the budget between its columns. Every NVARCHAR(n) costs 2*n bytes.
    """
    t = (sqlite_type or "").upper()
    if "INT" in t:
        return "INT"
    if "BLOB" in t:
        return "VARBINARY(900)"
    if key_cols <= 1:
        return "NVARCHAR(450)"
    # 900 bytes total, 2 bytes per character, minus a little headroom.
    return f"NVARCHAR({max(32, 440 // key_cols)})"


def is_epoch_ms_type(sqlite_type: str) -> bool:
    """Columns storing a Unix-epoch value that can exceed INT (milliseconds)."""
    t = (sqlite_type or "").upper()
    return "INT" in t and not any(k in t for k in ("TINY", "SMALL"))


# SQL Server caps an INSERT statement at 1000 row value expressions.
INSERT_CHUNK = 900


def _emit_inserts(target: str, collist_sql: str,
                   values: list[str]) -> list[str]:
    """Split a row list into INSERT statements of at most INSERT_CHUNK rows."""
    out: list[str] = []
    for i in range(0, len(values), INSERT_CHUNK):
        chunk = values[i:i + INSERT_CHUNK]
        out.append(f"INSERT INTO {ident(target)} ({collist_sql}) VALUES\n"
                   + ",\n".join(chunk) + ";")
    return out


# --------------------------------------------------------------------------- #
# SQLite -> T-SQL
# --------------------------------------------------------------------------- #
def convert_sqlite_db(db_path: Path, prefix: str,
                     skip_tables: Iterable[str] = ()) -> tuple[str, list[tuple], set[str]]:
    """Return (tsql_text, [(table, rows)], {source_table_names})."""
    con = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        out: list[str] = []
        stats: list[tuple] = []
        covered: set[str] = set()
        skip = {s.lower() for s in skip_tables}
        for table in tables:
            covered.add(table.lower())
            if table.lower() in skip:
                out.append(f"-- table {table}: schema omitted (payload too large)")
                continue
            cols = con.execute(f'PRAGMA table_info("{table}")').fetchall()
            if not cols:
                continue
            target = safe_table(f"{prefix}_{table}")
            pk: list[str] = []
            body: list[str] = []
            pk_count = sum(1 for c in cols if c[5])
            # An AUTOINCREMENT column whose values are all NULL is not a real
            # rowid alias (AuthMe ships id=NULL) -> treat it as a plain column.
            null_pk = {
                safe_table(c[1]) for c in cols
                if is_identity(c[2], pk=bool(c[5]), pk_count=pk_count) and c[5]
                and con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{c[1]}" IS NULL'
                                ).fetchone()[0] == con.execute(
                    f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            }
            for c in cols:
                cname, ctype, notnull, dflt, is_pk = c[1], c[2], c[3], c[4], c[5]
                cname = safe_table(cname)
                if is_identity(ctype, pk=bool(is_pk), pk_count=pk_count) \
                        and cname not in null_pk:
                    body.append(f"    {ident(cname)} INT IDENTITY(1,1) NOT NULL")
                    pk.append(cname)
                    continue
                if is_pk and cname in null_pk:
                    body.append(f"    {ident(cname)} {tsql_type(ctype)} NULL")
                    continue
                ctype_sql = key_type(ctype, pk_count) if is_pk else tsql_type(ctype)
                line = f"    {ident(cname)} {ctype_sql}"
                if notnull:
                    line += " NOT NULL"
                if dflt is not None:
                    expr = default_expr(str(dflt), ctype)
                    if expr:
                        line += f" DEFAULT {expr}"
                body.append(line)
                if is_pk:
                    pk.append(cname)
            if pk:
                body.append(f"    CONSTRAINT {ident('PK_' + target)} PRIMARY KEY ("
                            + ", ".join(ident(c) for c in pk) + ")")
            out.append(f"DROP TABLE IF EXISTS {ident(target)};")
            out.append(f"CREATE TABLE {ident(target)} (\n" + ",\n".join(body) + "\n);")

            rows = con.execute(f'SELECT * FROM "{table}"').fetchall()
            stats.append((target, len(rows)))
            if not rows:
                continue
            names = [safe_table(c[1]) for c in cols]
            time_cols = {safe_table(c[1]) for c in cols if is_time_type(c[2])}
            identity_cols = [safe_table(c[1]) for c in cols
                             if is_identity(c[2], pk=bool(c[5]), pk_count=pk_count)
                             and safe_table(c[1]) not in null_pk]
            if identity_cols:
                out.append(f"SET IDENTITY_INSERT {ident(target)} ON;")
            collist = ", ".join(ident(n) for n in names)
            vals = ["(" + ", ".join(lit_cell(row[n], n in time_cols)
                                   for n in names) + ")" for row in rows]
            out.extend(_emit_inserts(target, collist, vals))
            if identity_cols:
                out.append(f"SET IDENTITY_INSERT {ident(target)} OFF;")
            out.append("")
        return "\n".join(out), stats, covered
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Consolidated server dump -> T-SQL
# --------------------------------------------------------------------------- #
def _strip_public(body: str) -> str:
    return body.replace('"PUBLIC".', "").replace('"PUBLIC"', "")


def _split_top(text: str, sep: str = ",") -> list[str]:
    """Split on a separator at nesting depth 0, ignoring separators in strings."""
    parts: list[str] = []
    depth = 0
    buf = ""
    in_str = False
    for ch in text:
        if ch == "'":
            in_str = not in_str
        if not in_str:
            if ch in "([":
                depth += 1
                if depth == 1 and not buf.strip():
                    buf = ""  # drop the row's opening paren
                    continue
            elif ch in ")]":
                depth -= 1
            elif ch == sep and depth == 0:
                parts.append(buf.strip())
                buf = ""
                continue
        buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return parts


DDL_RE = re.compile(
    r"CREATE\s+(?:CACHED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r'([`"]?)([\w]+)\1\s*\(', re.I)
INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+([`\"]?)([\w]+)\1\s*(?:\(([^)]*)\))?\s*VALUES(.*?);",
    re.S | re.I)


def convert_server_dump(dump_path: Path,
                        covered: set[str]) -> tuple[str, list[tuple]]:
    text = dump_path.read_text(encoding="utf-8", errors="replace")
    parts = re.split(r"^--\s*(\d+)\.\s*(.+)$", text, flags=re.M)
    out: list[str] = []
    stats: list[tuple] = []
    for i in range(1, len(parts) - 2, 3):
        name = parts[i + 1].strip()
        body = _strip_public(parts[i + 2])
        key = name.split()[0].upper()
        prefix = SECTION_PREFIX.get(key)
        if not prefix:
            continue

        ddl: dict[str, str] = {}
        for m in DDL_RE.finditer(body):
            start = m.start()
            # capture the balanced parenthesis body
            i2 = m.end()
            depth = 1
            in_str = False
            while i2 < len(body) and depth:
                ch = body[i2]
                if ch == "'":
                    in_str = not in_str
                elif not in_str:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                i2 += 1
            ddl[m.group(2)] = body[start:i2]

        grouped: dict[str, list[tuple[str, str | None, str]]] = {}
        for m in INSERT_RE.finditer(body):
            grouped.setdefault(m.group(2), []).append((m.group(0), m.group(3), m.group(4)))

        # column names per table, so an INSERT without a column list can be
        # mapped onto the real columns instead of placeholders.
        ddl_columns: dict[str, list[str]] = {}
        for tbl, ddl_sql in ddl.items():
            inner = ddl_sql[ddl_sql.index("(") + 1: ddl_sql.rindex(")")]
            cols: list[str] = []
            for col in _split_top(inner):
                up = col.upper()
                if up.startswith(("PRIMARY KEY", "FOREIGN KEY", "UNIQUE",
                                  "CONSTRAINT")):
                    continue
                m = re.match(r'^[`"]?([\w]+)[`"]?\s+', col)
                if m:
                    cols.append(m.group(1))
            ddl_columns[tbl] = cols

        for tbl in sorted(set(ddl) | set(grouped)):
            if tbl.lower() == "sqlite_sequence":
                continue
            if tbl.lower() in covered:
                continue
            target = safe_table(f"{prefix}_{tbl}")
            if tbl not in ddl:
                continue
            ddl_sql, identity_cols = convert_create_table(ddl[tbl], target)
            out.append(f"DROP TABLE IF EXISTS {ident(target)};")
            out.append(ddl_sql)
            stmts = grouped.get(tbl, [])
            stats.append((target, len(stmts)))
            if identity_cols:
                out.append(f"SET IDENTITY_INSERT {ident(target)} ON;")
            for raw, collist, values in stmts:
                rendered = convert_insert(raw, collist, values, target,
                                         ddl_columns.get(tbl))
                if rendered:
                    out.append(rendered)
            if identity_cols:
                out.append(f"SET IDENTITY_INSERT {ident(target)} OFF;")
            out.append("")
    return "\n".join(out), stats


def _pk_columns(col: str) -> list[str]:
    """Extract the column list of a PRIMARY KEY clause."""
    if "(" not in col or ")" not in col:
        return []
    inner = col[col.index("(") + 1:col.rindex(")")]
    return [c.strip().strip('`"') for c in inner.split(",") if c.strip()]


def convert_create_table(ddl: str, target: str) -> tuple[str, list[str]]:
    """Return (tsql_create_table, identity_column_names)."""
    inner = ddl[ddl.index("(") + 1: ddl.rindex(")")]
    body: list[str] = []
    pk: list[str] = []
    identity: list[str] = []
    # first pass: which columns are part of the primary key, and how many
    key_cols: set[str] = set()
    pk_count = 0
    for col in _split_top(inner):
        if "PRIMARY KEY" in col.upper():
            cols = _pk_columns(col)
            key_cols |= set(cols)
            pk_count += len(cols)
    for col in _split_top(inner):
        up = col.upper()
        if up.startswith("PRIMARY KEY"):
            pk += _pk_columns(col)
            continue
        if up.startswith("FOREIGN KEY") or up.startswith("UNIQUE"):
            continue
        if up.startswith("CONSTRAINT"):
            if "PRIMARY KEY" in up:
                pk += _pk_columns(col)
            continue
        m = re.match(r'^[`"]?([\w]+)[`"]?\s+(.*)$', col, re.S)
        if not m:
            continue
        cname, rest = m.group(1), m.group(2)
        rest_up = rest.upper()
        if "IDENTITY" in rest_up or rest_up.startswith("GENERATED"):
            body.append(f"    {ident(safe_table(cname))} INT IDENTITY(1,1) NOT NULL")
            pk.append(cname)
            identity.append(safe_table(cname))
            continue
        tm = re.match(r"([A-Za-z]+(?:\s*\([^)]*\))?)", rest)
        ctype = tm.group(1) if tm else "TEXT"
        null = "NOT NULL" if "NOT NULL" in rest_up else "NULL"
        body.append(f"    {ident(safe_table(cname))} "
                    f"{tsql_type(ctype, key=cname in key_cols, key_cols=pk_count)} "
                    f"{null}")
    if pk:
        body.append(f"    CONSTRAINT {ident('PK_' + target)} PRIMARY KEY ("
                    + ", ".join(ident(safe_table(c)) for c in pk) + ")")
    return (f"CREATE TABLE {ident(target)} (\n" + ",\n".join(body) + "\n);", identity)


def convert_insert(raw: str, collist: str | None, values: str,
                   target: str,
                   ddl_cols: list[str] | None = None) -> str:
    names = ([c.strip().strip('`"') for c in collist.split(",")]
             if collist else [])
    rows = _split_rows(values)
    rendered: list[str] = []
    for row in rows:
        cells = _split_top(row)
        if names and len(cells) != len(names):
            continue
        if not names:
            # No column list in the statement: use the table's real columns.
            names = list(ddl_cols or [])
            if len(cells) != len(names):
                continue
        rendered.append("(" + ", ".join(convert_cell(c) for c in cells) + ")")
    if not rendered:
        return ""
    collist_sql = ", ".join(ident(safe_table(n)) for n in names)
    return "\n".join(_emit_inserts(target, collist_sql, rendered))


def _split_rows(values: str) -> list[str]:
    """Split a VALUES tuple list into individual rows (outer parens removed)."""
    rows: list[str] = []
    depth = 0
    buf = ""
    in_str = False
    for ch in values:
        if ch == "'":
            in_str = not in_str
        if not in_str:
            if ch == "(":
                depth += 1
                if depth == 1:
                    buf = ""  # drop the row's opening paren
                continue
            if ch == ")":
                depth -= 1
                if depth == 0:
                    rows.append(buf)
                    buf = ""
                continue
        buf += ch
    return rows


def convert_cell(cell: str) -> str:
    cell = cell.strip()
    if not cell:
        return "NULL"
    up = cell.upper()
    if up == "NULL":
        return "NULL"
    if up in ("TRUE", "FALSE"):
        return "1" if up == "TRUE" else "0"
    if cell.startswith("'") and cell.endswith("'"):
        inner = cell[1:-1].replace("''", "'")
        return "N'" + inner.replace("'", "''") + "'"
    if re.fullmatch(r"-?\d+", cell):
        return cell
    if re.fullmatch(r"-?\d+\.\d+([eE][-+]?\d+)?", cell):
        return cell
    return "N'" + cell.replace("'", "''") + "'"


# --------------------------------------------------------------------------- #
# Local web ledger -> T-SQL
# --------------------------------------------------------------------------- #
def sql_server_available() -> bool:
    """True when the configured SQL Server database is reachable."""
    try:
        import pyodbc

        from app.config import SQL_DATABASE, SQL_SERVER
    except ImportError:
        return False
    conn_str = (
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server={SQL_SERVER};Database={SQL_DATABASE};"
        "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;"
    )
    try:
        with pyodbc.connect(conn_str, timeout=5) as cn:
            cn.cursor().execute("SELECT 1")
        return True
    except Exception:
        return False


def export_gacha_ledger_from_mssql() -> tuple[str, list[tuple]]:
    """Export the gacha_* tables that live in SQL Server.

    Emits the full schema (CREATE TABLE) plus every row, so the dump stays
    self-contained: loading it into an empty database reproduces the ledger.
    """
    import pyodbc

    from app.config import SQL_DATABASE, SQL_SERVER
    from tools.init_gacha_schema import GACHA_TABLES

    conn_str = (
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server={SQL_SERVER};Database={SQL_DATABASE};"
        "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;"
    )
    out: list[str] = []
    stats: list[tuple] = []
    with pyodbc.connect(conn_str, timeout=120) as cn:
        cur = cn.cursor()
        cur.execute(
            "SELECT t.name FROM sys.tables t WHERE t.name LIKE 'gacha[_]%' "
            "ORDER BY t.name"
        )
        tables = [r[0] for r in cur.fetchall()]
        for table in tables:
            cur.execute("SELECT * FROM " + ident(table))
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            stats.append((table, len(rows)))

            spec = GACHA_TABLES.get(table)
            if spec:
                target_cols, pk = spec
                out.append(f"DROP TABLE IF EXISTS {ident(table)};")
                out.append(
                    f"CREATE TABLE {ident(table)} (\n    {target_cols},\n"
                    f"    CONSTRAINT {ident('PK_' + table)} {pk}\n);"
                )
            else:
                # Unknown table: keep whatever shape the server has.
                cur.execute(
                    "SELECT c.name, c.is_identity FROM sys.columns c "
                    "JOIN sys.tables t ON c.object_id = t.object_id "
                    "WHERE t.name = ?", table
                )
                colinfo = cur.fetchall()
                lines = []
                pk_cols = []
                for name, is_identity in colinfo:
                    cur.execute(
                        "SELECT TYPE_NAME(user_type_id), is_nullable FROM "
                        "sys.columns WHERE object_id = OBJECT_ID(?) AND name = ?",
                        table, name,
                    )
                    ctype, nullable = cur.fetchone()
                    if is_identity:
                        lines.append(f"    {ident(name)} INT IDENTITY(1,1) NOT NULL")
                        pk_cols.append(name)
                        continue
                    sql_type = "NVARCHAR(450)" if "char" in (ctype or "").lower() \
                        else ctype or "NVARCHAR(450)"
                    if nullable:
                        sql_type += " NULL"
                    else:
                        sql_type += " NOT NULL"
                    lines.append(f"    {ident(name)} {sql_type}")
                out.append(f"DROP TABLE IF EXISTS {ident(table)};")
                out.append(
                    f"CREATE TABLE {ident(table)} (\n" + ",\n".join(lines) + "\n);"
                )
            if not rows:
                out.append("")
                continue
            has_identity = "id" in cols and table in (
                "gacha_pulls", "gacha_inventory", "gacha_drops",
                "gacha_battles", "gacha_battle_drops", "gacha_upgrades",
                "gacha_contracts", "gacha_tx",
            )
            if has_identity:
                out.append(f"SET IDENTITY_INSERT {ident(table)} ON;")
            collist = ", ".join(ident(c) for c in cols)
            vals = ["(" + ", ".join(lit(v) for v in row) + ")" for row in rows]
            out.extend(_emit_inserts(table, collist, vals))
            if has_identity:
                out.append(f"SET IDENTITY_INSERT {ident(table)} OFF;")
            out.append("")
    return "\n".join(out), stats


def export_gacha_ledger(db_path: Path) -> tuple[str, list[tuple]]:
    """Export the gacha ledger.

    Prefers the SQL Server copy (the live ledger) and falls back to a local
    SQLite file when one is still around.
    """
    if sql_server_available():
        return export_gacha_ledger_from_mssql()
    if not db_path.exists():
        return "", []
    con = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out: list[str] = []
    stats: list[tuple] = []
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for table in tables:
            cols = con.execute(f'PRAGMA table_info("{table}")').fetchall()
            if not cols:
                continue
            target = f"gacha_{table}"
            pk: list[str] = []
            body: list[str] = []
            pk_count = sum(1 for c in cols if c[5])
            for c in cols:
                cname, ctype, notnull, _dflt, is_pk = c[1], c[2], c[3], c[4], c[5]
                cname = safe_table(cname)
                if is_identity(ctype, pk=bool(is_pk), pk_count=pk_count):
                    body.append(f"    {ident(cname)} INT IDENTITY(1,1) NOT NULL")
                    pk.append(cname)
                    continue
                ctype_sql = key_type(ctype, pk_count) if is_pk else tsql_type(ctype)
                line = f"    {ident(cname)} {ctype_sql}"
                if notnull:
                    line += " NOT NULL"
                body.append(line)
                if is_pk:
                    pk.append(cname)
            if pk:
                body.append(f"    CONSTRAINT {ident('PK_' + target)} PRIMARY KEY ("
                            + ", ".join(ident(c) for c in pk) + ")")
            out.append(f"DROP TABLE IF EXISTS {ident(target)};")
            out.append(f"CREATE TABLE {ident(target)} (\n" + ",\n".join(body) + "\n);")

            rows = con.execute(f'SELECT * FROM "{table}"').fetchall()
            stats.append((target, len(rows)))
            if not rows:
                out.append("")
                continue
            names = [safe_table(c[1]) for c in cols]
            time_cols = {safe_table(c[1]) for c in cols if is_time_type(c[2])}
            identity_cols = [safe_table(c[1]) for c in cols
                             if is_identity(c[2], pk=bool(c[5]), pk_count=pk_count)]
            if identity_cols:
                out.append(f"SET IDENTITY_INSERT {ident(target)} ON;")
            collist = ", ".join(ident(n) for n in names)
            vals = ["(" + ", ".join(lit_cell(row[n], n in time_cols)
                                   for n in names) + ")" for row in rows]
            out.extend(_emit_inserts(target, collist, vals))
            if identity_cols:
                out.append(f"SET IDENTITY_INSERT {ident(target)} OFF;")
            out.append("")
    finally:
        con.close()
    return "\n".join(out), stats


# --------------------------------------------------------------------------- #
# PikaMC download
# --------------------------------------------------------------------------- #
def signed_url(client: httpx.Client, remote_path: str) -> str:
    last = None
    for attempt in range(8):
        r = client.get(f"{BASE}/api/client/servers/{SRV}/files/download",
                       params={"files": remote_path})
        if r.status_code == 429:
            wait = 3 * (attempt + 1)
            print(f"       rate-limited, waiting {wait}s", flush=True)
            time.sleep(wait)
            last = r
            continue
        r.raise_for_status()
        return r.json()["url"]
    raise RuntimeError(f"rate limited: {last}")


def download(client: httpx.Client, remote_path: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = signed_url(client, remote_path)
    n = 0
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in resp.iter_bytes(1024 * 256):
                fh.write(chunk)
                n += len(chunk)
    return n


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="jellyvale_full.sql")
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--skip-gacha", action="store_true",
                    help="do not include the gacha ledger (it lives in SQL Server)")
    args = ap.parse_args()

    DL.mkdir(exist_ok=True)
    header = [
        "/* ==========================================================================",
        "   JellyVale - MASTER SQL SERVER (T-SQL) DUMP",
        "   Server  : JellyVale (Paper 26.2) @ hub.pikamc.vn",
        f"   UUID    : {SRV}",
        "   Source  : PikaMC panel API (/files/download) + local web ledger",
        "   Dialect : T-SQL (SQL Server 2019+)",
        "   Load    : sqlcmd -S <server> -E -d <db> -i jellyvale_full.sql",
        "            (file is UTF-8 with BOM so Vietnamese text stays intact)",
        " ========================================================================== */",
        "",
        "SET NOCOUNT ON;",
        "SET XACT_ABORT ON;",
        "GO",
        "",
        "-- Drop every table this script owns so the dump can be re-applied.",
    ]

    chunks: list[str] = []
    covered: set[str] = set()
    stats: list[tuple[str, str, int]] = []

    print("== plugin databases (downloaded) ==", flush=True)
    with httpx.Client(timeout=300.0, headers=H, follow_redirects=True) as client:
        for plugin, remote, prefix in REMOTE_DATABASES:
            local = DL / f"{plugin}.db"
            if not args.no_download or not local.exists():
                try:
                    size = download(client, remote, local)
                    print(f"  downloaded {plugin:18} {size:>12,} bytes", flush=True)
                except Exception as exc:
                    print(f"  FAIL {plugin:18} {str(exc)[:70]}", flush=True)
                    continue
            if not local.exists():
                continue
            try:
                sql, st, cov = convert_sqlite_db(
                    local, prefix, skip_tables=SKIP_TABLES.get(plugin, set()))
            except Exception as exc:
                print(f"  FAIL {plugin:18} convert: {str(exc)[:70]}", flush=True)
                continue
            covered |= cov
            chunks.append(f"\n-- {'=' * 60}\n-- PLUGIN: {plugin}\n"
                          f"-- SOURCE: {remote}\n-- {'=' * 60}\n{sql}")
            for t, n in st:
                stats.append((plugin, t, n))
            print(f"  exported {plugin:18} {len(st):2} tables", flush=True)

    dump = DL / "server_all_databases.sql"
    if dump.exists():
        print("\n== consolidated server dump ==", flush=True)
        sql, st = convert_server_dump(dump, covered)
        chunks.append(f"\n-- {'=' * 60}\n-- SERVER CONSOLIDATED DUMP\n"
                      f"-- SOURCE: /server_all_databases.sql\n-- {'=' * 60}\n{sql}")
        for t, n in st:
            stats.append(("server-dump", t, n))
        print(f"  exported {len(st)} tables", flush=True)

    print("\n== web gacha ledger ==", flush=True)
    if args.skip_gacha:
        print("  skipped (--skip-gacha)")
    else:
        sql, st = export_gacha_ledger(ROOT / "data" / "gacha.db")
        if sql:
            chunks.append(f"\n-- {'=' * 60}\n-- WEB GACHA LEDGER\n"
                          f"-- SOURCE: SQL Server gacha_* tables\n-- {'=' * 60}\n{sql}")
            for t, n in st:
                stats.append(("gacha", t, n))
            print(f"  exported {len(st)} tables", flush=True)
    footer = ["\n-- {'=' * 60}", "-- END OF DUMP", "-- {'=' * 60}", "GO", ""]
    out_path = ROOT / args.out
    # utf-8-sig: the BOM makes sqlcmd / SSMS read the file as UTF-8 instead of
    # the system ANSI code page, which would mangle Vietnamese text.
    out_path.write_text("\n".join(header) + "\n".join(chunks) + "\n".join(footer),
                        encoding="utf-8-sig")

    print()
    print(f"Wrote {out_path.name}: {out_path.stat().st_size:,} bytes, {len(stats)} tables")
    for src, t, n in stats:
        print(f"  {src:14} {t:55} {n:>8,} stmt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
