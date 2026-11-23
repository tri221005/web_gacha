"""Inspect the real data in data/gacha.db: is it fake or real?"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "gacha.db"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

tables = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("TABLES:", ", ".join(tables))
print()

print("=== row counts ===")
for t in tables:
    try:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:16} {n}")
    except Exception as exc:
        print(f"  {t:16} ERR {exc}")

print()
print("=== wallets (real players vs bots) ===")
for r in con.execute("SELECT player, balance, is_bot, created_at FROM wallets ORDER BY is_bot, balance DESC"):
    tag = "BOT " if r["is_bot"] else "USER"
    print(f"  {tag} {r['player']:22} balance={r['balance']:>12,}  created={r['created_at']}")

print()
print("=== real (non-bot) pulls ===")
rows = con.execute("""
    SELECT player, case_id, cost, prize_name, rarity, prize_coin, dry_run, created_at
    FROM pulls WHERE player NOT IN (SELECT player FROM wallets WHERE is_bot=1)
    ORDER BY id DESC LIMIT 20
""").fetchall()
if not rows:
    print("  (none)")
for r in rows:
    print(f"  {r['player']:16} {r['case_id']:16} cost={r['cost']:>8,} -> {r['prize_name']:24} "
          f"({r['rarity']:12}) {r['prize_coin']:>10,}  dry={r['dry_run']}")

print()
print("=== dry_run vs live split ===")
for r in con.execute("SELECT dry_run, COUNT(*) n, SUM(cost) spent FROM pulls GROUP BY dry_run"):
    kind = "DRY (fake coin)" if r["dry_run"] else "LIVE (real coin)"
    print(f"  {kind:22} pulls={r['n']:5}  spent={r['spent'] or 0:,}")

print()
print("=== ledger (tx) by kind ===")
for r in con.execute("SELECT kind, COUNT(*) n, SUM(amount) total FROM tx GROUP BY kind ORDER BY n DESC"):
    print(f"  {r['kind']:14} n={r['n']:6}  sum={r['total'] or 0:,}")

print()
print("=== battles ===")
for r in con.execute("SELECT status, COUNT(*) n FROM battles GROUP BY status"):
    print(f"  {r['status']:10} {r['n']}")

print()
print("=== inventory status ===")
for r in con.execute("SELECT status, COUNT(*) n FROM inventory GROUP BY status"):
    print(f"  {r['status']:10} {r['n']}")

print()
print("=== upgrades / contracts / bonus ===")
print("  upgrades:", con.execute("SELECT COUNT(*) FROM upgrades").fetchone()[0],
      " wins:", con.execute("SELECT COALESCE(SUM(won),0) FROM upgrades").fetchone()[0])
print("  contracts:", con.execute("SELECT COUNT(*) FROM contracts").fetchone()[0])
print("  bonus claims:", con.execute("SELECT COUNT(*) FROM bonus").fetchone()[0])

con.close()
