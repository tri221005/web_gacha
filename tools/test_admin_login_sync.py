"""Check that an account can sign in when it is an admin on the server.

The web console keeps its list in step with the LuckPerms group on the
server, so an account that was made an admin there can sign in here even
when it is not in `.env`.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import luckperms, store  # noqa: E402
from app.config import ADMIN_PASSWORD, ADMIN_USERS  # noqa: E402
from app.main import app  # noqa: E402

PASSED = 0
FAILED = 0


def check(label: str, ok: bool, extra: str = "") -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  OK   {label}")
    else:
        FAILED += 1
        print(f"  FAIL {label} {extra}")


async def main() -> None:
    store.init()
    target = "shsuzy"

    print("== an account that is not an admin cannot sign in ==")
    client = TestClient(app)
    r = client.get("/admin/login")
    csrf = r.text.split('name="csrf" value="')[1].split('"')[0]
    r = client.post("/admin/login", data={"username": target,
                                          "password": ADMIN_PASSWORD or "x",
                                          "csrf": csrf},
                    follow_redirects=False)
    check("the sign-in is refused",
          "error=sai" in r.headers.get("location", ""),
          r.headers.get("location", ""))

    print()
    print("== the same account can sign in once the server says so ==")
    await luckperms.grant_admin(target)
    try:
        admins = await luckperms.fetch_server_admins(force=True)
        check("the account is an admin on the server",
              target in [a.lower() for a in admins], str(admins))
        check("the account is not in .env",
              target not in ADMIN_USERS, str(ADMIN_USERS))

        client = TestClient(app)
        r = client.get("/admin/login")
        csrf = r.text.split('name="csrf" value="')[1].split('"')[0]
        r = client.post("/admin/login", data={"username": target,
                                              "password": ADMIN_PASSWORD or "x",
                                              "csrf": csrf},
                        follow_redirects=False)
        location = r.headers.get("location", "")
        check("the sign-in works", r.status_code == 303
              and location.rstrip("/").endswith("/admin"), location)
        r = client.get("/admin", follow_redirects=False)
        check("the console opens", r.status_code == 200, str(r.status_code))
    finally:
        await luckperms.revoke_admin(target)
        store.remove_admin(target)

    print()
    print("== the account is locked out again ==")
    client = TestClient(app)
    r = client.get("/admin/login")
    csrf = r.text.split('name="csrf" value="')[1].split('"')[0]
    r = client.post("/admin/login", data={"username": target,
                                          "password": ADMIN_PASSWORD or "x",
                                          "csrf": csrf},
                    follow_redirects=False)
    check("the sign-in is refused again",
          "error=sai" in r.headers.get("location", ""),
          r.headers.get("location", ""))

    final = await luckperms.fetch_server_admins(force=True)
    check("the server list is back to normal",
          target not in [a.lower() for a in final], str(final))


asyncio.run(main())
print(f"\n{PASSED} passed, {FAILED} failed")
raise SystemExit(1 if FAILED else 0)
