"""Count tables/inserts per section of the consolidated dump for the 7 modules
that have no downloadable .db file."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
text = (ROOT / "downloads" / "server_all_databases.sql").read_text(
    encoding="utf-8", errors="replace")

parts = re.split(r"^--\s*(\d+)\.\s*(.+)$", text, flags=re.M)
for i in range(1, len(parts), 3):
    num, name, body = parts[i], parts[i + 1].strip(), parts[i + 2]
    tables = re.findall(r"CREATE (?:CACHED )?TABLE\s+[`\"]?([\w.]+)[`\"]?", body)
    inserts = re.findall(r"INSERT INTO\s+[`\"]?([\w.]+)[`\"]?", body)
    # count data rows: number of tuples in INSERT statements
    tuples = 0
    for stmt in re.findall(r"INSERT INTO.*?;", body, re.S):
        tuples += stmt.count("),") + 1 if stmt.count("),") else stmt.count(",")
    print(f"\n### {num}. {name}")
    print(f"   tables: {tables}")
    print(f"   insert stmts per table: { {t: inserts.count(t) for t in set(inserts)} }")
    print(f"   body size: {len(body):,} chars")
