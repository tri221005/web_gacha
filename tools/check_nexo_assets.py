"""Refined Nexo asset check: resolve namespaced refs against pack/assets and external packs."""
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEXO = ROOT / "Nexo"
ITEMS = NEXO / "items"
PACK = NEXO / "pack"
ASSETS = PACK / "assets"

# Build the set of asset paths available in pack/assets
available = set()
for ns_dir in ASSETS.iterdir():
    if not ns_dir.is_dir():
        continue
    ns = ns_dir.name
    for sub in ns_dir.rglob("*"):
        if sub.is_file():
            rel = sub.relative_to(ASSETS / ns).as_posix()
            available.add(f"{ns}:{rel}")

# Build the set of asset paths inside external packs
ext_paths = set()
ext_dir = PACK / "external_packs"
for zp in sorted(ext_dir.glob("*.zip")):
    try:
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():
                if n.startswith("assets/") and not n.endswith("/"):
                    rest = n[len("assets/"):]
                    if "/" in rest:
                        ns, rel = rest.split("/", 1)
                        ext_paths.add(f"{ns}:{rel}")
    except Exception as exc:
        print(f"  ! cannot read {zp.name}: {exc}")

print(f"assets in pack/assets : {len(available)}")
print(f"assets in external zips: {len(ext_paths)}")
print()

# Collect refs
tex_refs, model_refs = {}, {}
for yml in sorted(ITEMS.rglob("*.yml")):
    rel = yml.relative_to(ROOT).as_posix()
    cur = None
    for line in yml.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^([a-z0-9_]+):\s*$", line)
        if m:
            cur = m.group(1)
            continue
        s = line.strip()
        if s.startswith("texture:"):
            tex_refs.setdefault(s.split(":", 1)[1].strip().strip("'\""), []).append(f"{rel}:{cur}")
        elif s.startswith("model:"):
            model_refs.setdefault(s.split(":", 1)[1].strip().strip("'\""), []).append(f"{rel}:{cur}")


def resolve(ref: str, kind: str) -> bool:
    """Does this asset reference resolve?"""
    if ":" in ref:
        ns, path = ref.split(":", 1)
    else:
        ns, path = "minecraft", ref
    path = path.lstrip("/")
    cands = {f"{ns}:{path}"}
    cands.add(f"{ns}:{path}.png")
    cands.add(f"{ns}:{path}.json")
    if kind == "model":
        cands.add(f"{ns}:models/{path}.json")
        cands.add(f"{ns}:models/{path}")
    else:
        cands.add(f"{ns}:textures/{path}.png")
        cands.add(f"{ns}:textures/{path}")
    # modelengine paths live in their own namespace
    if ns == "modelengine":
        cands = set(cands)
    return bool(cands & available) or bool(cands & ext_paths)


print("=== TEXTURES ===")
missing = []
for tex, where in sorted(tex_refs.items()):
    if not resolve(tex, "texture"):
        missing.append((tex, where))
print(f"referenced: {len(tex_refs)}   unresolved: {len(missing)}")
for t, w in missing:
    print(f"  MISSING {t}  <- {w}")

print()
print("=== MODELS ===")
missing_m = []
for mdl, where in sorted(model_refs.items()):
    if not resolve(mdl, "model"):
        missing_m.append((mdl, where))
print(f"referenced: {len(model_refs)}   unresolved: {len(missing_m)}")
for m, w in missing_m[:25]:
    print(f"  MISSING {m}  <- {w}")
if len(missing_m) > 25:
    print(f"  ... and {len(missing_m) - 25} more")
