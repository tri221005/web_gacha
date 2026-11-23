import sqlite3

con = sqlite3.connect("file:downloads/AuthMe.db?mode=ro", uri=True)
for r in con.execute("SELECT id, lastlogin, regdate FROM authme LIMIT 5"):
    print(r)
print("---distinct types---")
for r in con.execute("SELECT DISTINCT typeof(lastlogin), typeof(regdate) FROM authme"):
    print(r)
print("--- odd values ---")
for r in con.execute("SELECT lastlogin, regdate FROM authme WHERE lastlogin NOT GLOB '[0-9]*' OR regdate NOT GLOB '[0-9]*' LIMIT 5"):
    print(r)
con.close()
