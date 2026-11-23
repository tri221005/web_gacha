"""Check that the console still works when the server cannot be reached.

The admin list has three sources. When the server is down, the two local
ones have to carry on working, and the console must not lock itself out.
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
    env_admin = next(iter(ADMIN_USERS))

    print("== the server is unreachable ==")
    original_export = luckperms._export_users
    original_console = luckperms._console
    original_base = luckperms.PIKA_BASE_URL

    # Point the module at a port nothing listens on. The real code path
    # runs, so the test also covers the network failure handling.
    luckperms.PIKA_BASE_URL = "http://127.0.0.1:9"

    # Forget the cached list, so the code really has to talk to the server.
    luckperms._cache["admins"] = None
    luckperms._cache["at"] = 0.0
    try:
        client = TestClient(app)
        r = client.get("/admin/login")
        csrf = r.text.split('name="csrf" value="')[1].split('"')[0]
        r = client.post("/admin/login", data={"username": env_admin,
                                              "password": ADMIN_PASSWORD or "x",
                                              "csrf": csrf},
                        follow_redirects=False)
        location = r.headers.get("location", "")
        check("the .env admin can still sign in", r.status_code == 303
              and location.rstrip("/").endswith("/admin"), location)
        r = client.get("/admin", follow_redirects=False)
        check("the console still opens", r.status_code == 200, str(r.status_code))

        print()
        print("== the admin list still answers ==")
        r = client.get("/api/admin/admins")
        check("the list endpoint works", r.status_code == 200, str(r.status_code))
        data = r.json()
        check("the server error is reported", bool(data.get("server_error")),
              str(data.get("server_error")))
        names = {row["name"].lower() for row in data["admins"]}
        check("the .env admin is still listed", env_admin in names, str(names))

        print()
        print("== a server change is refused, not half done ==")
        # The sign-in gave the session a new CSRF token, so read it back
        # from the console page before changing anything.
        page = client.get("/admin").text
        csrf = page.split('name="csrf" content="')[1].split('"')[0]
        r = client.post("/api/admin/admins",
                        json={"name": "shsuzy", "action": "grant"},
                        headers={"X-CSRF": csrf})
        check("the grant fails cleanly", r.status_code == 503, str(r.status_code))
        local = {row["name"].lower() for row in store.list_admin_records()}
        check("nothing was written locally", "shsuzy" not in local, str(local))
    finally:
        luckperms._export_users = original_export
        luckperms._console = original_console
        luckperms.PIKA_BASE_URL = original_base
        luckperms._cache["at"] = 0.0
        store.remove_admin("shsuzy")


asyncio.run(main())
print(f"\n{PASSED} passed, {FAILED} failed")
raise SystemExit(1 if FAILED else 0)
