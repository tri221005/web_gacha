"""Sanity-check the generated T-SQL dump for common syntax problems."""
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
text = (ROOT / "jellyvale_full.sql").read_text(encoding="utf-8", errors="replace")

print(f"size: {len(text):,} chars")
tables = re.findall(r"CREATE TABLE \[([\w]+)\]", text)
print(f"tables: {len(tables)}  unique: {len(set(tables))}")
dupes = [t for t, n in Counter(tables).items() if n > 1]
print(f"duplicates: {dupes}")

problems = Counter()
for pat in (r"NULL NOT NULL", r"NOT NULL NULL", r"DEFAULT GETUTCDATE\(\) NOT NULL",
            r"IDENTITY\(1,1\) NOT NULL NOT NULL", r"\[id\] INT IDENTITY.*IDENTITY",
            r"PRIMARY KEY \(\)", r",\s*,", r"\(\s*,", r"VALUES\s*;"):
    n = len(re.findall(pat, text))
    if n:
        problems[pat] = n
print("\nsyntax red flags:")
for p, n in problems.items():
    print(f"  {n:>6}  {p}")
if not problems:
    print("  none")

print("\n=== sample DDL ===")
for name in ("luckperms_LUCKPERMS_USER_PERMISSIONS", "authme_authme",
             "gacha_battle_players", "coreprotect_co_item",
             "simplelogin_users", "griefprevention_griefprevention_claims"):
    i = text.find(f"CREATE TABLE [{name}]")
    if i < 0:
        print(f"\n-- {name}: NOT FOUND")
        continue
    end = text.index(";", text.index(")", i)) + 1
    print(f"\n-- {name}")
    print(text[i:end])
