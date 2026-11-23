"""Download a file from the PikaMC server via the signed-url flow.

/files/download returns {"url": "<signed url>"}; fetch that to get the bytes.
"""
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import PIKA_API_KEY, PIKA_BASE_URL  # noqa: E402

SRV = "de021d06-8c2d-40c9-b470-31c5eb240d92"
BASE = PIKA_BASE_URL
H = {"Authorization": f"Bearer {PIKA_API_KEY}", "Accept": "application/json"}


def download(remote_path: str, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120.0, headers=H, follow_redirects=True) as c:
        r = c.get(f"{BASE}/api/client/servers/{SRV}/files/download",
                  params={"files": remote_path})
        r.raise_for_status()
        payload = r.json()
        url = payload["url"]
        print(f"  signed url ok -> fetching {len(url)} char url")
        with c.stream("GET", url) as resp:
            resp.raise_for_status()
            n = 0
            with out.open("wb") as fh:
                for chunk in resp.iter_bytes(1024 * 256):
                    fh.write(chunk)
                    n += len(chunk)
    return n


if __name__ == "__main__":
    targets = [
        ("/plugins/ExcellentEconomy/data.db", "downloads/ExcellentEconomy_data.db"),
        ("/plugins/AuthMe/authme.db", "downloads/AuthMe_authme.db"),
    ]
    root = Path(__file__).resolve().parent.parent
    for remote, local in targets:
        print(f"[{remote}]")
        try:
            n = download(remote, root / local)
            print(f"  saved {n:,} bytes -> {local}")
        except Exception as exc:
            print(f"  FAILED: {exc}")
