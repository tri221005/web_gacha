"""Try to download the module DBs that only exist inside the consolidated dump."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.pika_download import download  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

candidates = [
    ("/plugins/SimpleLogin/passwords.db", "SimpleLogin.db"),
    ("/plugins/WorldGuard/cache/profiles.sqlite", "WorldGuard.db"),
    ("/plugins/GriefPreventionData/ClaimData1", "GP_ClaimData1.db"),
    ("/plugins/GriefPreventionData/PlayerData1", "GP_PlayerData1.db"),
    ("/plugins/BetterTeamsBACKUP.zip", "BetterTeams.zip"),
    ("/plugins/SetHome/homes.yml", "SetHome_homes.yml"),
    ("/plugins/CoreProtect/database.db", "CoreProtect.db"),
]

for remote, local in candidates:
    print(f"[{remote}]")
    try:
        n = download(remote, ROOT / "downloads" / local)
        print(f"  OK {n:,} bytes -> {local}")
    except Exception as exc:
        msg = str(exc)
        print(f"  FAIL {msg[:100]}")
