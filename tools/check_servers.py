"""List every PikaMC server and find the JellyVale one."""
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
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{PIKA_BASE_URL}/api/client/servers", headers=headers,
                        params={"page": 1, "per_page": 50, "scope": "owned",
                                "sort": "created"})
        print(f"list servers -> HTTP {r.status_code}\n")
        for s in r.json().get("servers", {}).get("data", []):
            print(f"  uuid     : {s.get('uuid')}")
            print(f"  short    : {s.get('uuid_short')}")
            print(f"  name     : {s.get('name')}")
            print(f"  status   : {s.get('status')}  limit={s.get('limits', {}).get('players')}")
            print()

        print(f"configured PIKA_SERVER_UUID = {PIKA_SERVER_UUID!r}\n")
        for sid in (PIKA_SERVER_UUID, "de021d06-8c2d-40c9-b470-31c5eb240d92"):
            r = await c.get(f"{PIKA_BASE_URL}/api/client/servers/{sid}", headers=headers)
            print(f"GET server/{sid} -> HTTP {r.status_code}")
            if r.status_code == 200:
                item = r.json().get("server") or r.json()
                print(f"  name  : {item.get('name')}")
                print(f"  uuid  : {item.get('uuid')}")
                print(f"  short : {item.get('uuid_short')}")
                print(f"  ident : {item.get('identifier')}")
            else:
                print("  ", r.text[:200])
            print()


asyncio.run(main())
