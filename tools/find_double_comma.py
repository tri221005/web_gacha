import re
from pathlib import Path

text = Path("jellyvale_full.sql").read_text(encoding="utf-8", errors="replace")
for m in re.finditer(r",\s*,", text):
    i = m.start()
    print(repr(text[max(0, i - 250):i + 120]))
    print("---")
