"""Probe: unhandled input types and missing authorization checks.

Run:  python tools/test_security_probe6.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app import store  # noqa: E402
from app.config import ADMIN_USERS  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

# The admin account comes from the config, so the probe follows whatever
# ADMIN_USERS says without being edited every time it changes.
ADMIN_NAME = next(iter(ADMIN_USERS))

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
        cookie = mint({"user": "Alice", "login_name": "alice", "csrf": "x"})

        print("[bad types in the JSON body]")
        async def post(path, body, **kw):
            """Return the status code, counting a crash as a 500."""
            try:
                r = await c.post(path, json=body, cookies={"jv_session": cookie},
                                 headers={"x-csrf": "x"}, **kw)
                return r.status_code
            except Exception:
                return 500

        for path, body in (
            ("/api/inventory/sell", {"ids": ["not-a-number"]}),
            ("/api/inventory/sell", {"ids": {"a": 1}}),
            ("/api/inventory/sell", {"ids": [1.5]}),
            ("/api/inventory/sell", "a string body"),
            ("/api/upgrade", {"inventory_id": "abc", "target_id": 1, "target_coin": 1}),
            ("/api/case/jelly-starter/open", {"count": "abc"}),
            ("/api/case/jelly-starter/open", {"count": [1, 2]}),
            ("/api/battles", {"case_id": None, "slots": "x", "rounds": "y"}),
        ):
            code = await post(path, body)
            check(f"{path} with a bad body does not crash the server",
                  code < 500, f"http={code} body={body}")

        print("\n[missing authorization]")
        # Any logged-in user can add bots to somebody else's battle.
        store.ensure_wallet("Host", seed=100000)
        battle_id = store.create_battle("Host", "jelly-starter", 1, 2, "STANDARD",
                                        5000, False)

        # The payment is stubbed out: this check is about who may call the
        # bots, not about the money. Without the stub the host would need
        # a real PikaMC account, and the bot seat would cost real Coin.
        real_take = main_mod.pika_take

        async def fake_take(player, amount, kind="sync"):
            return store.get_balance(player)

        main_mod.pika_take = fake_take
        try:
            r = await c.post(f"/api/battles/{battle_id}/bots", json={},
                             cookies={"jv_session": cookie},
                             headers={"x-csrf": "x"})
            check("a player cannot add bots to another player's battle",
                  r.status_code == 403,
                  f"http={r.status_code} battle={battle_id} host=Host")
            # The host can.
            host_cookie = mint({"user": "Host", "login_name": "host", "csrf": "x"})
            r = await c.post(f"/api/battles/{battle_id}/bots", json={},
                             cookies={"jv_session": host_cookie},
                             headers={"x-csrf": "x"})
            check("the host can add bots to their own battle",
                  r.status_code == 200, f"http={r.status_code}")
        finally:
            main_mod.pika_take = real_take

        print("\n[public endpoints]")
        # A guest client: this one carries the logged-in cookie from the
        # requests above.
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     timeout=30) as guest:
            r = await guest.get("/api/drops")
            data = r.json()
            players = [d.get("player") for d in (data.get("drops") or [])]
            check("/api/drops is public but hides the player names from a guest",
                  r.status_code == 200 and not any(players),
                  f"http={r.status_code} players={players[:5]}")
        r = await c.get("/setup")
        check("/setup is public", r.status_code == 200, f"http={r.status_code}")
        r = await c.get("/api/battles/1")
        check("/api/battles/{id} is public", r.status_code in (200, 404),
              f"http={r.status_code}")

        print("\n[session cookie flags]")
        r = await c.get("/login")
        raw = r.headers.get("set-cookie", "").lower()
        check("the session cookie has HttpOnly", "httponly" in raw, raw[:150])
        check("the session cookie has SameSite=Lax", "samesite=lax" in raw,
              raw[:150])
        check("the session cookie has no Secure flag", "secure" not in raw,
              "the cookie would travel over plain HTTP")

        print("\n[admin page]")
        r = await c.get("/admin", cookies={"jv_session": cookie})
        check("a normal player cannot open the admin page",
              r.status_code in (303, 302) or "/gacha" in str(r.headers.get("location", "")),
              f"http={r.status_code} location={r.headers.get('location')}")
        admin_cookie = mint({"user": ADMIN_NAME, "login_name": ADMIN_NAME.lower(),
                             "csrf": "x"})
        r = await c.get("/admin", cookies={"jv_session": admin_cookie})
        check("the admin page opens for the admin", r.status_code == 200,
              f"http={r.status_code}")

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")


asyncio.run(main())
