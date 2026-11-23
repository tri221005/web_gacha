"""A health check of the whole system.

It looks at the things that decide whether the site actually works: the
database connection, the indexes the queries rely on, the case config,
the bot wallets and the leftover test rows.

Run:  python tools/health_check.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import store  # noqa: E402
from app.gacha import case_rtp, load_cases  # noqa: E402

# The indexes the slow queries need. Without them the ledger tables get
# scanned end to end and the site gets slow as the data grows.
NEEDED_INDEXES = [
    ("gacha_inventory", ["player", "status"]),
    ("gacha_drops", ["id"]),
    ("gacha_pulls", ["case_id"]),
    ("gacha_tx", ["player", "id"]),
    ("gacha_battles", ["status", "id"]),
]

ok = True


def report(name: str, passed: bool, detail: str = "") -> None:
    global ok
    if not passed:
        ok = False
    print(f"  [{'OK' if passed else '!!'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> None:
    print("== Database ==")
    started = time.time()
    try:
        store.init()
        one = store.run(lambda con: con.cursor().execute("SELECT 1").fetchone())
        report("the database answers", one is not None,
               f"{time.time() - started:.0f} ms")
    except Exception as exc:
        report("the database answers", False, str(exc))
        return

    print("\n== Indexes ==")
    rows = store.run(lambda con: con.cursor().execute(
        "SELECT t.name AS table_name, i.name AS index_name, "
        "       COL_NAME(ic.object_id, ic.column_id) AS column_name, "
        "       ic.key_ordinal "
        "FROM sys.indexes i "
        "JOIN sys.tables t ON t.object_id = i.object_id "
        "JOIN sys.index_columns ic ON ic.object_id = i.object_id "
        "AND ic.index_id = i.index_id "
        "WHERE t.name LIKE 'gacha[_]%' AND i.is_hypothetical = 0 "
        "  AND i.type > 0 "
        "ORDER BY t.name, i.name, ic.key_ordinal"
    ).fetchall())
    have: dict[str, set[str]] = {}
    for row in rows:
        d = dict(store.row_dict(row))
        have.setdefault(d["table_name"], set()).add(d["column_name"])
    for table, columns in NEEDED_INDEXES:
        got = have.get(table, set())
        missing = [c for c in columns if c not in got]
        report(f"{table} is indexed on {', '.join(columns)}", not missing,
               "missing " + ", ".join(missing) if missing else "")

    print("\n== Cases ==")
    cases = load_cases()
    report("there is at least one case", bool(cases), f"{len(cases)} cases")
    for case in cases:
        rtp = case_rtp(case) * 100
        flag = "  (over 100, the house loses money)" if rtp > 100 else ""
        print(f"       {case.id:18} cost={case.pull_cost:>7,}  RTP={rtp:6.1f}%{flag}")

    print("\n== Wallets ==")
    rows = store.run(lambda con: con.cursor().execute(
        "SELECT player, is_bot, balance FROM gacha_wallets ORDER BY player"
    ).fetchall())
    people = [dict(store.row_dict(r)) for r in rows]
    bots = [w for w in people if w.get("is_bot")]
    humans = [w for w in people if not w.get("is_bot")]
    report("the bot wallets exist", len(bots) >= 8, f"{len(bots)} bots")
    report("there are real players", bool(humans),
           ", ".join(w["player"] for w in humans))

    print("\n== Test leftovers ==")
    for table, column in (("gacha_wallets", "player"),
                           ("gacha_tx", "player"),
                           ("gacha_inventory", "player")):
        n = store.run(lambda con, t=table, c=column: con.cursor().execute(
            f"SELECT COUNT(*) FROM {t} WHERE {c} LIKE 'AUD[_]%' "
            f"OR {c} LIKE 'RC[_]%' OR {c} IN "
            "('StubPlayer','joinplayer','Broke','Alice','Mallory','Injector')"
        ).fetchone()[0])
        report(f"{table} has no test rows left", n == 0, f"{n} rows")

    print("\n" + ("All good." if ok else "There are problems above."))


main()
