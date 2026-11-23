"""Focused probe for the confirmed findings (CSRF fallback, battle payment loss).

Run:  python tools/test_security_probe.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app import store  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> None:
    store.init()
    import app.main as main_mod

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                 timeout=30) as c:
        # A session with a user but no csrf entry — exactly what a browser
        # holds between the login POST and the first rendered page.
        cookie = mint({"user": "Alice", "login_name": "alice"})
        r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                         cookies={"jv_session": cookie})
        check("a session without a csrf entry is refused",
              r.status_code == 403,
              f"http={r.status_code} — the check must not compare None with None")

        # The same request with an empty session is refused.
        r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                         cookies={"jv_session": mint({})})
        check("a session without a user is refused", r.status_code == 401,
              f"http={r.status_code}")

        # Cross-site style request: the cookie is sent, the header is not.
        r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                         cookies={"jv_session": cookie},
                         headers={"Origin": "https://evil.example"})
        check("a cross-origin POST without the header is refused",
              r.status_code == 403, f"http={r.status_code}")

        # A wrong token is refused too.
        r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                         cookies={"jv_session": cookie},
                         headers={"x-csrf": "guessed-token"})
        check("a wrong csrf token is refused", r.status_code == 403,
              f"http={r.status_code}")

        # SameSite of the session cookie.
        r = await c.get("/login")
        raw = r.headers.get("set-cookie", "")
        check("the session cookie is SameSite=Lax",
              "samesite=lax" in raw.lower(), raw[:120])
        check("the session cookie is not marked Secure",
              "secure" not in raw.lower(),
              "the cookie would travel over plain HTTP")

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")


asyncio.run(main())
