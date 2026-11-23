import sqlite3

for name in ("CoreProtect", "WorldGuard"):
    con = sqlite3.connect(f"file:downloads/{name}.db?mode=ro", uri=True)
    ts = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    print(name, ts)
    for t in ts:
        print("   ", t, con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0])
    con.close()
