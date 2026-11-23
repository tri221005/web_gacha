"""Check the PikaMC API key: read access plus the control.console scope."""
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
        print("key prefix:", PIKA_API_KEY[:10])

        r = await c.get(f"{PIKA_BASE_URL}/api/client/servers", headers=headers,
                        params={"page": 1, "per_page": 5, "scope": "owned"})
        print(f"\nlist servers -> HTTP {r.status_code}")
        if r.status_code == 200:
            for s in r.json().get("servers", {}).get("data", []):
                print(f"  {s.get('name'):20} {s.get('uuid')}")
        else:
            print("  ", r.text[:200])

        r = await c.post(
            f"{PIKA_BASE_URL}/api/client/servers/{PIKA_SERVER_UUID}/command",
            headers=headers, json={"command": "list"},
        )
        print(f"\ncontrol.console -> HTTP {r.status_code}")
        print("  ", r.text[:200])

        r = await c.post(
            f"{PIKA_BASE_URL}/api/client/servers/{PIKA_SERVER_UUID}/files/sqlite-query",
            headers=headers,
            json={
                "file": "/plugins/ExcellentEconomy/data.db",
                "query": "SELECT name, money FROM excellenteconomy_users LIMIT 3",
                "rows": 3,
                "read_only": True,
            },
        )
        print(f"\nfiles.query-raw -> HTTP {r.status_code}")
        print("  ", r.text[:300])


asyncio.run(main())
