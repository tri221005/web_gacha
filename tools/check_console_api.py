"""Check whether the PikaMC console endpoint returns command output."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app.config import PIKA_API_KEY, PIKA_BASE_URL, PIKA_SERVER_UUID  # noqa: E402


async def main() -> None:
    headers = {
        "Authorization": f"Bearer {PIKA_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    url = f"{PIKA_BASE_URL}/api/client/servers/{PIKA_SERVER_UUID}/command"
    async with httpx.AsyncClient(timeout=30) as c:
        for cmd in ("eco balance Trez1724", "list"):
            r = await c.post(url, headers=headers, json={"command": cmd})
            print(f"--- {cmd!r}")
            print("   status:", r.status_code)
            body = r.text
            print("   body:", body[:600])
            print()


asyncio.run(main())
