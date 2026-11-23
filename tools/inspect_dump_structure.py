"""Inspect the consolidated server_all_databases.sql to find the LuckPerms (H2) tables."""
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL = ROOT / "downloads" / "server_all_databases.sql"
text = SQL.read_text(encoding="utf-8", errors="replace")

print(f"file size: {len(text):,} chars")

# section headers look like: -- N. NAME (...)\n-- Source: ...
sections = re.findall(r"^--\s*(\d+)\.\s*(.+?)\n--\s*Source:\s*(.+?)$", text, re.M)
print(f"\n{len(sections)} sections:")
for num, name, source in sections:
    print(f"  {num:>2}. {name.strip():30} <- {source.strip()}")

print("\n=== all CREATE TABLE statements ===")
creates = re.findall(r'CREATE (?:CACHED )?TABLE "PUBLIC"\."([^"]+)"', text)
print(f"{len(creates)} tables")
for t in creates:
    print("  ", t)

print("\n=== how many INSERT INTO per table ===")
ins = Counter(re.findall(r'INSERT INTO "PUBLIC"\."([^"]+)"', text))
for t, n in ins.most_common():
    print(f"  {t:45} {n:>5} insert statements")
