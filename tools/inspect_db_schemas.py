"""Print the SQLite schema of every downloaded plugin database."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in sorted((ROOT / "downloads").glob("*.db")):
    try:
        con = sqlite3.connect(f"file:{p.resolve().as_posix()}?mode=ro", uri=True)
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        print(f"\n=== {p.name} ===")
        for t in tables:
            cols = con.execute(f'PRAGMA table_info("{t}")').fetchall()
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            spec = ", ".join(f"{c[1]}:{c[2]}" + ("PK" if c[5] else "") for c in cols)
            print(f"  {t} ({n} rows) :: {spec}")
        con.close()
    except Exception as exc:
        print(f"\n=== {p.name} === ERROR {exc}")
