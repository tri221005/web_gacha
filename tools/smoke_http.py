"""End-to-end smoke test against a running dev server.

Covers the public pages plus the authenticated ones (a session cookie is
minted directly, since the real login goes through the PikaMC API).
"""
import sys

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from tools.mint_cookie import mint  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
USER = "Trez1724"

failures = []


def check(label, cond, extra=""):
    print(f"  [{'OK ' if cond else 'FAIL'}] {label} {extra}")
    if not cond:
        failures.append(label)


cookie = mint({"user": USER, "login_name": USER, "csrf": "smoke-csrf"})

with httpx.Client(base_url=BASE, timeout=30, follow_redirects=True) as c:
    print("public routes:")
    for path in ("/", "/gacha", "/api/drops", "/battles", "/login"):
        r = c.get(path)
        check(f"GET {path}", r.status_code == 200, f"len={len(r.content)}")

with httpx.Client(base_url=BASE, timeout=30, follow_redirects=True,
                  cookies={"jv_session": cookie}) as c:
    print("authenticated routes:")
    for path in ("/gacha", "/inventory", "/upgrade", "/admin",
                 "/vi", "/bonus", "/battles", "/api/drops",
                 "/api/upgrade/targets"):
        r = c.get(path)
        check(f"GET {path}", r.status_code == 200, f"len={len(r.content)}")

    r = c.get("/api/drops")
    check("drops payload is JSON", r.headers.get("content-type", "")
          .startswith("application/json"))

print()
if failures:
    print(f"FAILURES: {failures}")
    sys.exit(1)
print("all smoke checks passed")
