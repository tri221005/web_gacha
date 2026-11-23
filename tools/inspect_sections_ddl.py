"""Print the CREATE TABLE statements of every section in the consolidated dump."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
text = (ROOT / "downloads" / "server_all_databases.sql").read_text(
    encoding="utf-8", errors="replace")

# split on the "-- N. NAME" section markers
parts = re.split(r"^--\s*(\d+)\.\s*(.+)$", text, flags=re.M)
# parts[0] = preamble, then triples (num, name, body)
for i in range(1, len(parts), 3):
    num, name, body = parts[i], parts[i + 1].strip(), parts[i + 2]
    creates = re.findall(r"CREATE (?:CACHED )?TABLE .*?;", body, re.S)
    print(f"\n########## {num}. {name} ##########")
    for c in creates:
        print(c.strip()[:900])
    if not creates:
        print("  (no CREATE TABLE; body starts with)")
        print("  " + body.strip()[:400].replace("\n", "\n  "))
