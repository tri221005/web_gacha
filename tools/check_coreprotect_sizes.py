import sqlite3

con = sqlite3.connect("file:downloads/CoreProtect.db?mode=ro", uri=True)
for t in ("co_entity", "co_container", "co_item", "co_block"):
    cols = con.execute(f'PRAGMA table_info("{t}")').fetchall()
    n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    total = sum(len(str(r)) for r in con.execute(f'SELECT * FROM "{t}"'))
    print(f"{t}: {n} rows, ~{total:,} chars")
    for c in cols:
        print(f"    {c[1]}:{c[2]}")
    row = con.execute(f'SELECT * FROM "{t}" LIMIT 1').fetchone()
    print("    sample row lengths:", [len(str(v)) for v in row])
con.close()
