import sqlite3

for db, table in (("AuthMe", "authme"), ("zAuctionHouse", "zauctionhousev4_items")):
    con = sqlite3.connect(f"file:downloads/{db}.db?mode=ro", uri=True)
    cols = [c[1] for c in con.execute(f'PRAGMA table_info("{table}")')]
    pk = [c[1] for c in con.execute(f'PRAGMA table_info("{table}")') if c[5]]
    for p in pk:
        n = con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{p}" IS NULL').fetchone()[0]
        mn, mx = con.execute(f'SELECT MIN("{p}"), MAX("{p}") FROM "{table}"').fetchone()
        print(f"{db}.{table}.{p}: nulls={n} min={mn} max={mx}")
    con.close()
