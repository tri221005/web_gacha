"""One-shot check: do all gacha.json item ids have a resolvable image?"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
cfg = json.loads((ROOT / "gacha.json").read_text(encoding="utf-8"))
exts = (".png", ".webp", ".jpg", ".jpeg", ".svg")
items_dir = ROOT / "app" / "static" / "items"
cases_dir = ROOT / "app" / "static" / "cases"

missing = []
ids = {}
for c in cfg["cases"]:
    for i in c["items"]:
        ids.setdefault(i["id"], []).append(c["id"])
        if not any((items_dir / f"{i['id']}{e}").exists() for e in exts):
            missing.append((c["id"], i["id"], i["name"]))

print("unique item ids:", len(ids))
print("MISSING IMAGES:", len(missing))
for m in missing:
    print("   ", m)

print()
print("-- case images --")
for c in cfg["cases"]:
    found = [e for e in exts if (cases_dir / f"{c['id']}{e}").exists()]
    if not found:
        print("   MISSING:", c["id"])
    else:
        print("   ", c["id"], "->", found[0])

print()
print("-- ids used in more than one case (price conflict risk) --")
for item_id, case_ids in ids.items():
    if len(case_ids) > 1:
        print("   ", item_id, "in", case_ids)
