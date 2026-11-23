"""Check whether the console endpoint returns command output."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app.config import PIKA_API_KEY, PIKA_BASE_URL, PIKA_SERVER_UUID  # noqa: E402

HEADERS = {
    "Authorization": f"Bearer {PIKA_API_KEY}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        url = f"{PIKA_BASE_URL}/api/client/servers/{PIKA_SERVER_UUID}/command"
        for payload in (
            {"command": "list"},
            {"command": "eco balance Trez1724"},
            {"command": "eco balance Trez1724", "raw": True},
            {"command": "list", "waitForCompletion": True},
        ):
            r = await c.post(url, headers=HEADERS, json=payload)
            body = r.text.strip()
            print(f"payload={payload}")
            print(f"  -> HTTP {r.status_code}  body={body[:400]!r}\n")


asyncio.run(main())
