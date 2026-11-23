"""Report the size of each section of the generated T-SQL dump."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
p = ROOT / "jellyvale_full.sql"
text = p.read_text(encoding="utf-8", errors="replace")
print(f"total: {len(text):,} chars")

marks = [(m.start(), m.group(0)) for m in re.finditer(r"^-- (PLUGIN|SOURCE|WEB GACHA|SERVER CONSOLIDATED).*$", text, re.M)]
marks = [(0, "HEAD")] + marks + [(len(text), "END")]

sizes = []
for i in range(len(marks) - 1):
    start, label = marks[i]
    end = marks[i + 1][0]
    sizes.append((end - start, label))
for size, label in sorted(sizes, reverse=True)[:20]:
    print(f"  {size:>14,}  {label}")

print()
print("=== biggest tables ===")
for _ in re.finditer(r"^INSERT INTO \[([\w]+)\]", text, re.M):
    pass
# measure per-table insert blocks
tbl = None
acc: dict[str, int] = {}
for line in text.splitlines():
    m = re.match(r"INSERT INTO \[([\w]+)\]", line)
    if m:
        tbl = m.group(1)
    if tbl and line.startswith("("):
        acc[tbl] = acc.get(tbl, 0) + len(line)
for t, s in sorted(acc.items(), key=lambda x: -x[1])[:20]:
    print(f"  {s:>14,}  {t}")
