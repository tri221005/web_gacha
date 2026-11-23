"""Debug why the LuckPerms section produced no tables."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
text = (ROOT / "downloads" / "server_all_databases.sql").read_text(
    encoding="utf-8", errors="replace")

parts = re.split(r"^--\s*(\d+)\.\s*(.+)$", text, flags=re.M)
print("split parts:", len(parts))
for i in range(1, min(len(parts), 10), 3):
    print(f"  [{i}] num={parts[i]!r} name={parts[i+1].strip()[:60]!r}")

body = parts[2]
print("\nbody len:", len(body))
print("body head:", body[:200].replace("\n", " | "))

DDL = re.compile(
    r"CREATE\s+(?:CACHED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r'[`"]?(?:PUBLIC[`.])?([\w]+)[`"]?\s*\((.*?)\)\s*;', re.S | re.I)
hits = list(DDL.finditer(body))
print("\nDDL hits:", len(hits), [h.group(1) for h in hits])

# try without the (.*?)\)\s*; requirement
DDL2 = re.compile(
    r"CREATE\s+(?:CACHED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r'[`"]?(?:PUBLIC[`.])?([\w]+)[`"]?\s*\(', re.S | re.I)
print("loose hits:", [m.group(1) for m in DDL2.finditer(body)])
