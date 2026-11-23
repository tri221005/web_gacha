"""Check the admin list sync between the web console and the server.

Run:  python tools/test_admin_sync.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import luckperms, store  # noqa: E402
from app.main import app  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

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


def admin_client() -> TestClient:
    client = TestClient(app)
    cookie = mint({"user": "hhh21", "login_name": "hhh21", "csrf": "test-csrf"})
    client.cookies.set("jv_session", cookie)
    return client


async def main() -> None:
    store.init()

    print("== server admin list ==")
    server_admins = await luckperms.fetch_server_admins(force=True)
    check("the server list is not empty", bool(server_admins), str(server_admins))
    check("hhh21 is an admin on the server",
          "hhh21" in [a.lower() for a in server_admins], str(server_admins))
    check("the list has no duplicates",
          len(server_admins) == len({a.lower() for a in server_admins}),
          str(server_admins))

    print()
    print("== the API ==")
    client = admin_client()
    r = client.get("/api/admin/admins")
    check("the admin list loads", r.status_code == 200, str(r.status_code))
    data = r.json()
    entries = {row["name"].lower(): row for row in data["admins"]}
    check("hhh21 is in the list", "hhh21" in entries, str(list(entries)))
    check("hhh21 is an admin on the server", entries.get("hhh21", {}).get("server") is True,
          str(entries.get("hhh21")))
    check("every server admin is in the list",
          all(a.lower() in entries for a in server_admins), str(list(entries)))
    check("the group name is reported", data.get("server_group") == "admin",
          str(data.get("server_group")))

    print()
    print("== a normal player cannot use it ==")
    guest = TestClient(app)
    guest_cookie = mint({"user": "shsuzy", "login_name": "shsuzy", "csrf": "x"})
    guest.cookies.set("jv_session", guest_cookie)
    r = guest.get("/api/admin/admins")
    check("a player gets 403", r.status_code == 403, str(r.status_code))
    r = guest.post("/api/admin/admins", json={"name": "shsuzy", "action": "grant"},
                   headers={"X-CSRF": "x"})
    check("a player cannot grant admin", r.status_code == 403, str(r.status_code))

    print()
    print("== bad input is refused ==")
    r = client.post("/api/admin/admins", json={"name": "", "action": "grant"},
                    headers={"X-CSRF": "test-csrf"})
    check("an empty name is refused", r.status_code == 400, str(r.status_code))
    r = client.post("/api/admin/admins", json={"name": "x", "action": "nonsense"},
                    headers={"X-CSRF": "test-csrf"})
    check("an unknown action is refused", r.status_code == 400, str(r.status_code))
    r = client.post("/api/admin/admins",
                    json={"name": "bad name; op Bob", "action": "grant"},
                    headers={"X-CSRF": "test-csrf"})
    check("a name that could split a command is refused",
          r.status_code == 400, str(r.status_code))

    print()
    print("== the CSRF token is required ==")
    r = client.post("/api/admin/admins",
                    json={"name": "shsuzy", "action": "grant"},
                    headers={"X-CSRF": "wrong"})
    check("a wrong CSRF token is refused", r.status_code == 403, str(r.status_code))

    print()
    print("== granting and revoking on the server ==")
    # Use a real account that is not an admin, so the round trip can be
    # seen end to end without touching an existing admin.
    target = "shsuzy"
    try:
        r = client.post("/api/admin/admins",
                        json={"name": target, "action": "grant"},
                        headers={"X-CSRF": "test-csrf"})
        check("granting works", r.status_code == 200, r.text[:200])
        granted = await luckperms.fetch_server_admins(force=True)
        check("the account is now an admin on the server",
              target in [a.lower() for a in granted], str(granted))

        r = client.get("/api/admin/admins")
        entries = {row["name"].lower(): row for row in r.json()["admins"]}
        check("the account shows as a web admin too",
              entries.get(target, {}).get("web") is True, str(entries.get(target)))

        r = client.post("/api/admin/admins",
                        json={"name": target, "action": "revoke"},
                        headers={"X-CSRF": "test-csrf"})
        check("revoking works", r.status_code == 200, r.text[:200])
        revoked = await luckperms.fetch_server_admins(force=True)
        check("the account is no longer an admin on the server",
              target not in [a.lower() for a in revoked], str(revoked))
    finally:
        # Make sure the test account is left the way it was found: it must
        # not be an admin on the server when the test ends.
        await luckperms.revoke_admin(target)
        store.remove_admin(target)

    print()
    print("== the sync endpoint ==")
    r = client.post("/api/admin/admins/sync", headers={"X-CSRF": "test-csrf"})
    check("the sync works", r.status_code == 200, r.text[:200])
    synced = await luckperms.fetch_server_admins(force=True)
    local = [row["name"].lower() for row in store.list_admin_records()
             if row["source"] == "server"]
    check("the local table matches the server",
          sorted(local) == sorted(a.lower() for a in synced),
          f"local={local} server={synced}")

    print()
    print("== the log records it ==")
    log = store.list_admin_log(20)
    actions = [row["action"] for row in log]
    check("the grant is in the log", "admin_grant" in actions, str(actions[:8]))
    check("the revoke is in the log", "admin_revoke" in actions, str(actions[:8]))
    check("the sync is in the log", "admin_sync" in actions, str(actions[:8]))

    print()
    print("== the console page has the tab ==")
    r = client.get("/admin?tab=admins")
    check("the admins tab renders", r.status_code == 200, str(r.status_code))
    check("the tab is there", 'data-tab="admins"' in r.text)
    check("the table is there", 'id="admins-body"' in r.text)


asyncio.run(main())
print(f"\n{PASSED} passed, {FAILED} failed")
raise SystemExit(1 if FAILED else 0)
