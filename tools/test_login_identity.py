"""Verify the real login form works against live PikaMC AuthMe data.

The password is not known, so this checks the negative path plus the
identity that the app derives from the AuthMe row.
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app.pika import find_authme_user, find_economy_user  # noqa: E402
from app.security import verify_authme_sha256  # noqa: E402

BASE = "http://127.0.0.1:8099"


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        # 1. wrong password must be rejected
        r = await c.get("/login")
        csrf = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
        r = await c.post("/login", data={
            "username": "Trez1724", "password": "definitely-wrong-pw", "csrf": csrf,
        }, follow_redirects=False)
        print(f"wrong password -> HTTP {r.status_code}, location={r.headers.get('location')}")
        assert r.status_code == 303 and "error=sai" in r.headers.get("location", ""), \
            "wrong password was NOT rejected"

        # 2. the app must resolve the identity the same way PikaMC does
        for name in ("Trez1724", "hhh21", "shsuzy"):
            auth = await find_authme_user(name)
            eco = await find_economy_user(auth["username"])
            print(f"\n{name}:")
            print(f"  authme.username = {auth['username']!r}")
            print(f"  authme.realname = {auth['realname']!r}")
            print(f"  session user    = {auth['realname'] or auth['username']!r}")
            print(f"  session login   = {auth['username']!r}")
            print(f"  economy name    = {eco['name']!r}")
            print(f"  economy money   = {eco['money']}")
            assert str(auth["realname"]).lower() == str(eco["name"]).lower()
            assert str(auth["username"]).lower() == str(eco["name"]).lower()

        # 3. the password hash format must match what the app verifies
        auth = await find_authme_user("Trez1724")
        pwd = str(auth["password"])
        print(f"\nhash format ok: {pwd.startswith('$SHA$')} (len {len(pwd)})")
        assert verify_authme_sha256("wrong", pwd) is False
        assert verify_authme_sha256("", pwd) is False

    print("\nLOGIN IDENTITY CHECKS PASSED")


asyncio.run(main())
