"""Smoke test for the admin console.

Covers: access control, the read APIs, the coin/ban writes and the case
editor. The case editor writes to `gacha.json`, so it works on a copy and
restores the original afterwards.
"""
from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import ADMIN_PASSWORD, ADMIN_USERS  # noqa: E402
from app.gacha import GACHA_FILE  # noqa: E402
from app.main import app  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

# The admin account comes from the config, so the test follows whatever
# ADMIN_USERS says without being edited every time it changes.
ADMIN = next(iter(ADMIN_USERS))
PLAYER = "StubPlayer"
PASSED = 0
FAILED = 0


def check(label: str, condition: bool, extra: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  OK   {label}")
    else:
        FAILED += 1
        print(f"  FAIL {label} {extra}")


def session(name: str) -> dict:
    cookie = mint({"user": name, "login_name": name, "csrf": "test-csrf-token"})
    return {"jv_session": cookie}


def main() -> int:
    client = TestClient(app)
    admin = session(ADMIN)
    guest = session("StubPlayer")

    print("== access control ==")
    r = client.get("/admin", follow_redirects=False)
    check("guest /admin -> redirect", r.status_code in (302, 303, 307), str(r.status_code))
    check("guest /admin -> admin login",
          "/admin/login" in r.headers.get("location", ""),
          r.headers.get("location", ""))
    r = client.get("/api/admin/overview")
    check("guest /api/admin/overview -> 401", r.status_code == 401, str(r.status_code))
    r = client.get("/api/admin/overview", cookies=guest)
    check("player /api/admin/overview -> 403", r.status_code == 403, str(r.status_code))
    r = client.get("/api/admin/players", cookies=guest)
    check("player /api/admin/players -> 403", r.status_code == 403, str(r.status_code))

    print("== read APIs ==")
    r = client.get("/admin", cookies=admin, follow_redirects=False)
    check("admin /admin -> 200", r.status_code == 200, str(r.status_code))
    check("admin page has tabs", "admin-tab" in r.text)
    r = client.get("/api/admin/overview", cookies=admin)
    check("overview -> 200", r.status_code == 200, str(r.status_code))
    check("overview has stats", "stats" in r.json())
    r = client.get("/api/admin/players", cookies=admin)
    check("players -> 200", r.status_code == 200, str(r.status_code))
    check("players list not empty", len(r.json().get("players", [])) > 0)
    r = client.get("/api/admin/tx", cookies=admin)
    check("tx -> 200", r.status_code == 200, str(r.status_code))
    r = client.get("/api/admin/inventory", cookies=admin)
    check("inventory -> 200", r.status_code == 200, str(r.status_code))
    r = client.get("/api/admin/battles", cookies=admin)
    check("battles -> 200", r.status_code == 200, str(r.status_code))
    r = client.get("/api/admin/cases", cookies=admin)
    check("cases -> 200", r.status_code == 200, str(r.status_code))
    check("cases carry rtp", "rtp" in (r.json().get("cases") or [{}])[0])
    r = client.get("/api/admin/server", cookies=admin)
    check("server -> 200", r.status_code == 200, str(r.status_code))

    print("== CSRF ==")
    r = client.post("/api/admin/players/Test/coin", cookies=admin,
                    json={"amount": 10, "direction": "give"})
    check("coin without csrf -> 403", r.status_code == 403, str(r.status_code))
    r = client.post("/api/admin/players/Test/ban", cookies=admin,
                    json={"banned": True}, headers={"X-CSRF": "wrong"})
    check("ban with bad csrf -> 403", r.status_code == 403, str(r.status_code))

    print("== ban ==")
    r = client.post(f"/api/admin/players/{PLAYER}/ban", cookies=admin,
                    json={"banned": True, "reason": "test"},
                    headers={"X-CSRF": "test-csrf-token"})
    check("ban -> 200", r.status_code == 200, r.text[:200])
    r = client.post("/api/case/jelly-starter/open", cookies=guest,
                    json={"count": 1}, headers={"X-CSRF": "test-csrf-token"})
    check("banned player blocked", r.status_code == 403, str(r.status_code))
    r = client.post(f"/api/admin/players/{PLAYER}/ban", cookies=admin,
                    json={"banned": False}, headers={"X-CSRF": "test-csrf-token"})
    check("unban -> 200", r.status_code == 200, r.text[:200])
    r = client.post(f"/api/admin/players/{ADMIN}/ban", cookies=admin,
                    json={"banned": True}, headers={"X-CSRF": "test-csrf-token"})
    check("admin cannot ban itself", r.status_code == 400, str(r.status_code))

    print("== audit log ==")
    r = client.get("/api/admin/log", cookies=admin)
    check("log -> 200", r.status_code == 200, str(r.status_code))
    log = r.json().get("log", [])
    check("log has entries", len(log) > 0, f"count={len(log)}")
    actions = {row["action"] for row in log}
    check("ban is logged", "ban" in actions, str(actions))
    check("unban is logged", "unban" in actions, str(actions))
    check("log records the admin", all(row["admin"] for row in log))

    print("== admin login page ==")
    # A fresh client: the shared one still carries the admin cookie from
    # the checks above, which would skip the login page entirely.
    login_client = TestClient(app)
    r = login_client.get("/admin/login")
    check("admin login page -> 200", r.status_code == 200, str(r.status_code))
    check("login form present", 'action="/admin/login"' in r.text)
    csrf = r.text.split('name="csrf" value="')[1].split('"')[0]
    check("csrf token in the form", bool(csrf))
    r = login_client.post("/admin/login", data={"username": "NotAnAdmin",
                                                "password": "x", "csrf": csrf},
                          follow_redirects=False)
    check("unknown admin -> error", "error=sai" in r.headers.get("location", ""),
          r.headers.get("location", ""))
    r = login_client.post("/admin/login", data={"username": ADMIN,
                                                "password": "x", "csrf": "wrong"},
                          follow_redirects=False)
    check("bad csrf -> error page", "error=phien" in r.headers.get("location", ""),
          r.headers.get("location", ""))

    # With ADMIN_PASSWORD set the console password is the only check. With
    # it empty, the Minecraft password is checked instead. The test covers
    # whichever one the config says.
    import hashlib

    def authme_hash(password: str, salt: str = "salt") -> str:
        inner = hashlib.sha256(password.encode()).hexdigest()
        return "$SHA$" + salt + "$" + hashlib.sha256(
            (inner + salt).encode()).hexdigest()

    async def fake_authme(username):
        return {"username": username, "realname": username,
                "password": authme_hash("hunter2")}

    import app.main as main_module
    original = main_module.find_authme_user
    main_module.find_authme_user = fake_authme
    try:
        good_password = ADMIN_PASSWORD or "hunter2"
        wrong_password = "hunter2" if ADMIN_PASSWORD else "wrong"
        r = login_client.post("/admin/login", data={"username": ADMIN,
                                                    "password": wrong_password,
                                                    "csrf": csrf},
                              follow_redirects=False)
        check("wrong password -> error",
              "error=sai" in r.headers.get("location", ""),
              r.headers.get("location", ""))
        r = login_client.post("/admin/login", data={"username": ADMIN,
                                                    "password": good_password,
                                                    "csrf": csrf},
                              follow_redirects=False)
        location = r.headers.get("location", "")
        check("admin can sign in", r.status_code == 303
              and location.rstrip("/").endswith("/admin"), location)
        r = login_client.get("/admin", follow_redirects=False)
        check("signed-in admin reaches the console", r.status_code == 200,
              str(r.status_code))
    finally:
        main_module.find_authme_user = original

    print("== case editor (on a copy) ==")
    backup = GACHA_FILE.with_suffix(".json.testbak")
    shutil.copy2(GACHA_FILE, backup)
    try:
        r = client.get("/api/admin/cases", cookies=admin)
        original = r.json()["cases"][0]
        edited = dict(original)
        edited["name"] = original["name"] + " [edited]"
        r = client.post("/api/admin/cases", cookies=admin, json={"case": edited},
                        headers={"X-CSRF": "test-csrf-token"})
        check("save case -> 200", r.status_code == 200, r.text[:300])
        r = client.get("/api/admin/cases", cookies=admin)
        names = [c["name"] for c in r.json()["cases"]]
        check("case name saved", edited["name"] in names, str(names[:3]))

        bad = dict(original)
        bad["pull_cost"] = 0
        r = client.post("/api/admin/cases", cookies=admin, json={"case": bad},
                        headers={"X-CSRF": "test-csrf-token"})
        check("zero cost rejected", r.status_code == 400, str(r.status_code))

        bad = dict(original)
        bad["id"] = "Bad ID!"
        r = client.post("/api/admin/cases", cookies=admin, json={"case": bad},
                        headers={"X-CSRF": "test-csrf-token"})
        check("bad id rejected", r.status_code == 400, str(r.status_code))

        bad = dict(original)
        bad["items"] = []
        r = client.post("/api/admin/cases", cookies=admin, json={"case": bad},
                        headers={"X-CSRF": "test-csrf-token"})
        check("empty items rejected", r.status_code == 400, str(r.status_code))
    finally:
        shutil.copy2(backup, GACHA_FILE)
        backup.unlink(missing_ok=True)

    r = client.get("/api/admin/cases", cookies=admin)
    check("config restored", r.json()["cases"][0]["name"] == original["name"])

    print("== player page ==")
    r = client.get(f"/admin/player/{PLAYER}", cookies=admin)
    check("player page -> 200", r.status_code == 200, str(r.status_code))
    check("player page shows balance", "Coin" in r.text)

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
