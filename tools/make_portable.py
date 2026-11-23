"""Pack the files needed to run the web gacha on another machine.

    python tools/make_portable.py

The result is a zip with the application, the config template, the
requirements and the SQL schema. It leaves out the virtual environment
(it is rebuilt on the new machine), the downloaded plugin databases (they
are only used by the export tools) and the logs.

Run:  python tools/make_portable.py
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Everything the app needs at runtime.
INCLUDE_FILES = [
    "requirements.txt",
    ".env.example",
    "gacha.json",
    "start.bat",
    "HUONG_DAN_DU_AN.md",
    "HUONG_DAN_CAI_DAT_MOI.md",
]
INCLUDE_DIRS = ["app"]

# The SQL schema is 40 MB, so it stays out of the zip by default. The
# database is usually copied by hand, and the file is on the machine that
# already has it.
INCLUDE_SQL = False

SKIP_NAMES = {"__pycache__", ".venv", ".codegraph", ".ua", "downloads",
               "shots", "data", "caseforge-main", "Nexo"}
SKIP_SUFFIXES = {".pyc", ".log", ".err", ".zip", ".bak"}


def collect() -> list[Path]:
    out: list[Path] = []
    for name in INCLUDE_FILES:
        path = ROOT / name
        if path.exists():
            out.append(path)
    for folder in INCLUDE_DIRS:
        base = ROOT / folder
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_NAMES for part in path.parts):
                continue
            if path.suffix in SKIP_SUFFIXES:
                continue
            out.append(path)
    if INCLUDE_SQL:
        sql = ROOT / "jellyvale_full.sql"
        if sql.exists():
            out.append(sql)
    return out


def main() -> int:
    target = ROOT / "web-gacha-portable.zip"
    files = collect()
    total = sum(f.stat().st_size for f in files)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(ROOT))
    print(f"Wrote {target.name}: {len(files)} files, "
          f"{target.stat().st_size:,} bytes")
    print(f"  (source {total:,} bytes)")
    if not INCLUDE_SQL:
        print()
        print("The SQL schema is NOT in the zip. Copy jellyvale_full.sql by")
        print("hand if the new machine does not have the database yet:")
        print(f"  {ROOT / 'jellyvale_full.sql'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
