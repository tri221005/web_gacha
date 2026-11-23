"""Map Nexo items to the web catalogue in gacha.json.

The web gacha hands out items by id (e.g. "susanoo", "totem"). The NOTES say
the next step is "nexo give" to actually deliver items in-game. This script
checks which gacha.json ids have a matching Nexo item id, so we know what
can actually be delivered and what is currently fictional.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEXO_ITEMS = ROOT / "Nexo" / "items"

# Collect every nexo item id from all yml files
nexo_ids = {}
for yml in sorted(NEXO_ITEMS.rglob("*.yml")):
    text = yml.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        m = re.match(r"^([a-z0-9_]+):\s*$", line)
        if m:
            nexo_ids.setdefault(m.group(1), []).append(yml.relative_to(ROOT).as_posix())

cfg = json.loads((ROOT / "gacha.json").read_text(encoding="utf-8"))
web_ids = {}
for c in cfg["cases"]:
    for i in c["items"]:
        web_ids.setdefault(i["id"], {"name": i["name"], "cases": [], "rarity": i["rarity"]})
        web_ids[i["id"]]["cases"].append(c["id"])

print(f"Nexo item ids found: {len(nexo_ids)}")
print(f"Web catalogue ids:   {len(web_ids)}")
print()

print("=== web id -> matching Nexo item ===")
exact, fuzzy, none = [], [], []
for wid, info in sorted(web_ids.items()):
    if wid in nexo_ids:
        exact.append((wid, info, nexo_ids[wid]))
    else:
        # substring match either way
        cands = [n for n in nexo_ids if wid in n or n in wid]
        if cands:
            fuzzy.append((wid, info, cands))
        else:
            none.append((wid, info))

print(f"\n-- EXACT match ({len(exact)}) --")
for wid, info, files in exact:
    print(f"  {wid:20} {info['name']:26} {files}")

print(f"\n-- FUZZY / partial ({len(fuzzy)}) --")
for wid, info, cands in fuzzy:
    print(f"  {wid:20} {info['name']:26} -> {cands}")

print(f"\n-- NO Nexo item ({len(none)}) --")
for wid, info in none:
    print(f"  {wid:20} {info['name']:26} rarity={info['rarity']:12} cases={info['cases']}")

print()
print("=== summary ===")
print(f"  deliverable via nexo give : {len(exact)}/{len(web_ids)}")
print(f"  partially deliverable     : {len(fuzzy)}/{len(web_ids)}")
print(f"  fictional (no in-game item): {len(none)}/{len(web_ids)}")
