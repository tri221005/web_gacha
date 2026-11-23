import sqlite3

for db, table, cols in (
    ("AuthMe", "authme", ("lastlogin", "regdate")),
    ("ExcellentEconomy", "excellenteconomy_users", ("last_seen",)),
    ("Nightcore", "nightcore_user_data", ("last_seen",)),
):
    con = sqlite3.connect(f"file:downloads/{db}.db?mode=ro", uri=True)
    for c in cols:
        mn, mx = con.execute(f'SELECT MIN({c}), MAX({c}) FROM "{table}"').fetchone()
        print(f"{db}.{table}.{c}: min={mn} max={mx}")
    con.close()
