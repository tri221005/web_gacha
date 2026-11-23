import sqlite3

for name, table in (("AuthMe", "authme"), ("VJobs", "job_meta")):
    con = sqlite3.connect(f"file:downloads/{name}.db?mode=ro", uri=True)
    print(f"=== {name}.{table} ===")
    for c in con.execute(f'PRAGMA table_info("{table}")'):
        print("  ", c)
    con.close()

con = sqlite3.connect("file:data/gacha.db?mode=ro", uri=True)
print("=== gacha.battle_players ===")
for c in con.execute('PRAGMA table_info("battle_players")'):
    print("  ", c)
con.close()
