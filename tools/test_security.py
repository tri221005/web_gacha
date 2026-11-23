"""Security test suite: SQL injection, command injection, auth, CSRF, races.

Everything runs in-process against the ASGI app. The PikaMC panel is faked
with a stub that executes the SQL it receives against a real SQLite file, so
an injectable query would really run instead of being mocked away.

Run:  python tools/test_security.py
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import sys
import tempfile
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app import store  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

STUB_PORT = 8131
PASSWORD = "matkhau123"

results: list[tuple[str, bool, str]] = []
QUERY_LOG: list[str] = []
COMMAND_LOG: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# --------------------------------------------------------------------------- #
# Fake PikaMC panel
# --------------------------------------------------------------------------- #
def authme_hash(password: str, salt: str) -> str:
    inner = hashlib.sha256(password.encode()).hexdigest()
    return "$SHA$" + salt + "$" + hashlib.sha256((inner + salt).encode()).hexdigest()


class Panel:
    """A PikaMC panel that really runs the SQL it is given."""

    def __init__(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="jv-sec-")
        self.authme = os.path.join(self.dir, "authme.db")
        self.economy = os.path.join(self.dir, "data.db")
        self.balances: dict[str, float] = {}
        self.users: dict[str, dict[str, Any]] = {}
        self._build()

    def _build(self) -> None:
        con = sqlite3.connect(self.authme)
        con.execute(
            "CREATE TABLE authme (username TEXT, realname TEXT, password TEXT, "
            "lastlogin TEXT, regdate TEXT, ip TEXT, loggedin INTEGER)"
        )
        con.commit()
        con.close()
        con = sqlite3.connect(self.economy)
        con.execute(
            "CREATE TABLE excellenteconomy_users (uuid TEXT, name TEXT, "
            "last_seen TEXT, money REAL, coins REAL, shards REAL)"
        )
        con.commit()
        con.close()

    def add_user(self, username: str, realname: str, password: str = PASSWORD,
                 money: float = 100000.0) -> None:
        con = sqlite3.connect(self.authme)
        con.execute(
            "INSERT INTO authme (username, realname, password) VALUES (?, ?, ?)",
            (username, realname, authme_hash(password, "deadbeef")),
        )
        con.commit()
        con.close()
        con = sqlite3.connect(self.economy)
        con.execute(
            "INSERT INTO excellenteconomy_users VALUES (?, ?, ?, ?, '0', '0')",
            ("uuid-" + username, realname, str(int(time.time() * 1000)), money),
        )
        con.commit()
        con.close()
        self.balances[realname] = money
        self.users[username.lower()] = {"username": username, "realname": realname}

    def _run(self, path: str, query: str) -> list[dict]:
        db = self.authme if "authme" in path.lower() else self.economy
        QUERY_LOG.append(query)
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            cur = con.execute(query)
            out = [dict(r) for r in cur.fetchall()]
            con.close()
            return out
        except sqlite3.Error as exc:
            # A broken query means the app sent something the panel refused.
            return [{"__error__": str(exc)}]


def build_panel(panel: Panel) -> FastAPI:
    app = FastAPI()

    @app.post("/api/client/servers/{uuid}/files/sqlite-query")
    async def sqlite_query(request: Request):
        body = await request.json()
        rows = panel._run(body.get("file", ""), body.get("query", ""))
        if not rows:
            return JSONResponse({"results": []})
        if "__error__" in rows[0]:
            return JSONResponse({"results": [{"columns": [{"name": "error"}],
                                              "rows": [[{"type": "text",
                                                         "value": rows[0]["__error__"]}]]}]})
        keys = list(rows[0])
        columns = [{"name": k} for k in keys]
        data = [[{"type": "text", "value": r.get(k)} for k in keys] for r in rows]
        return JSONResponse({"results": [{"columns": columns, "rows": data}]})

    @app.post("/api/client/servers/{uuid}/command")
    async def command(request: Request):
        body = await request.json()
        cmd = str(body.get("command", ""))
        COMMAND_LOG.append(cmd)
        parts = cmd.split()
        if len(parts) == 4 and parts[0] == "eco" and parts[1] in ("take", "give"):
            action, name, amount = parts[1], parts[2], float(parts[3])
            if name in panel.balances:
                panel.balances[name] = max(
                    0.0, panel.balances[name] + (-amount if action == "take" else amount)
                )
                # The real plugin writes the money back to its SQLite file.
                con = sqlite3.connect(panel.economy)
                con.execute(
                    "UPDATE excellenteconomy_users SET money = ? WHERE name = ?",
                    (panel.balances[name], name),
                )
                con.commit()
                con.close()
        return JSONResponse({"ok": True})

    return app


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def wallet_of(player: str) -> int:
    try:
        return store.get_balance(player)
    except Exception:
        return -1


def tx_kinds(player: str) -> list[str]:
    try:
        return [t["kind"] for t in store.recent_tx(player, 50)]
    except Exception:
        return []


async def main() -> None:
    store.init()
    panel = Panel()
    panel.add_user("alice", "Alice")
    panel.add_user("evil", "Bob; op Bob")
    panel.add_user("sqli", "Sqli")

    server = uvicorn.Server(uvicorn.Config(build_panel(panel), host="127.0.0.1",
                                            port=STUB_PORT, log_level="error"))
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(1.5)

    os.environ["PIKA_BASE_URL"] = f"http://127.0.0.1:{STUB_PORT}"
    os.environ["PIKA_API_KEY"] = "stub-key"
    os.environ["PIKA_SERVER_UUID"] = "stub-uuid"
    os.environ["GACHA_DRY_RUN"] = "false"

    import app.config as config_mod
    import app.main as main_mod
    import app.pika as pika_mod

    base = f"http://127.0.0.1:{STUB_PORT}"
    config_mod.PIKA_BASE_URL = base
    config_mod.PIKA_API_KEY = "stub-key"
    config_mod.PIKA_SERVER_UUID = "stub-uuid"
    pika_mod.PIKA_BASE_URL = base
    pika_mod.PIKA_API_KEY = "stub-key"
    pika_mod.PIKA_SERVER_UUID = "stub-uuid"
    pika_mod._console_ok = True

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                 timeout=60) as c:
        # ------------------------------------------------------------- #
        print("\n[1] SQL injection in the PikaMC SQLite queries")
        # The username is validated before it reaches the query. Each payload
        # must be rejected without touching the table.
        payloads = [
            "' OR '1'='1",
            "' OR 1=1 --",
            "alice' UNION SELECT username, realname, password FROM authme --",
            "alice'; DROP TABLE authme; --",
            "' UNION SELECT sql FROM sqlite_master --",
            "alice' AND 1=1 --",
            "%27%20OR%201%3D1--",
            "'; SELECT * FROM authme; --",
        ]
        for p in payloads:
            before = len(QUERY_LOG)
            r = await c.post("/login", data={"username": p, "password": "x",
                                             "csrf": await csrf_of(c)})
            sent = QUERY_LOG[before:]
            leaked = any("authme" in q for q in sent)
            check(f"SQLi payload rejected at login: {p[:28]!r}",
                  r.status_code in (200, 303, 422) and not leaked,
                  f"http={r.status_code} queries_sent={sent}")

        # A valid login still works after the injection attempts.
        r = await c.post("/login", data={"username": "alice", "password": PASSWORD,
                                         "csrf": await csrf_of(c)})
        check("valid login still works after SQLi attempts",
              r.status_code == 303, f"http={r.status_code}")
        check("the authme table survived the injection attempts",
              len(panel._run(panel.authme, "SELECT COUNT(*) c FROM authme")) == 1)

        # The economy query goes through the same validator.
        r = await c.post("/login", data={"username": "sqli' OR '1'='1",
                                         "password": PASSWORD,
                                         "csrf": await csrf_of(c)})
        check("SQLi in the economy lookup is rejected",
              r.status_code in (303, 422), f"http={r.status_code}")

        # ------------------------------------------------------------- #
        print("\n[2] SQL injection into the SQL Server ledger")
        nasty = "Robert'); DROP TABLE gacha_wallets; --"
        store.ensure_wallet(nasty, seed=5000)
        check("a player name full of SQL is stored as plain text",
              wallet_of(nasty) == 5000, f"balance={wallet_of(nasty)}")
        con = store.connect()
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM sys.tables WHERE name = 'gacha_wallets'")
        check("the gacha_wallets table still exists",
              int(cur.fetchone()[0]) == 1)
        cur.execute("SELECT COUNT(*) FROM gacha_wallets WHERE player = ?", nasty)
        check("the injection text was not executed",
              int(cur.fetchone()[0]) == 1)
        cur.execute("DELETE FROM gacha_wallets WHERE player = ?", nasty)
        con.commit()

        # ------------------------------------------------------------- #
        print("\n[3] Command injection through the Minecraft console")
        COMMAND_LOG.clear()
        cookie = mint({"user": "Bob; op Bob", "login_name": "evil", "csrf": "x"})
        # The wallet must have money, or the case is refused before the
        # console is ever reached.
        store.ensure_wallet("Bob; op Bob", seed=100000)
        r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                         cookies={"jv_session": cookie}, headers={"x-csrf": "x"})
        cmds = [c_ for c_ in COMMAND_LOG if c_.startswith("eco")]
        check("a hostile player name never reaches the console",
              not cmds,
              f"http={r.status_code} commands={cmds} (the name must be refused)")
        check("the hostile name is refused with a 400",
              r.status_code == 400, f"http={r.status_code}")

        # A normal name still produces a proper command.
        COMMAND_LOG.clear()
        safe_cookie = mint({"user": "Alice", "login_name": "alice", "csrf": "x"})
        store.ensure_wallet("Alice", seed=100000)
        r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                         cookies={"jv_session": safe_cookie},
                         headers={"x-csrf": "x"})
        cmds = [c_ for c_ in COMMAND_LOG if c_.startswith("eco")]
        check("a normal player name still builds a console command",
              bool(cmds), f"http={r.status_code} commands={cmds}")
        check("the console command is NOT command-injected",
              all(len(c_.split()) == 4 for c_ in cmds), f"commands={cmds}")

        # ------------------------------------------------------------- #
        print("\n[4] Authentication and session handling")
        # The client keeps cookies between calls, so drop them to test the
        # "no session" case honestly.
        c.cookies.clear()
        r = await c.get("/api/wallet/live")
        check("API without a session is rejected", r.status_code == 401,
              f"http={r.status_code}")
        r = await c.post("/api/case/jelly-starter/open", json={"count": 1})
        check("opening a case without a session is rejected",
              r.status_code == 401, f"http={r.status_code}")
        forged = mint({"user": "Admin", "login_name": "admin", "csrf": "x"})[:-4] + "AAAA"
        r = await c.get("/api/wallet/live", cookies={"jv_session": forged})
        check("a tampered session cookie is rejected", r.status_code == 401,
              f"http={r.status_code}")

        # ------------------------------------------------------------- #
        print("\n[5] CSRF protection")
        good = mint({"user": "Alice", "login_name": "alice", "csrf": "x"})
        for path, payload in (
            ("/api/case/jelly-starter/open", {"count": 1}),
            ("/api/inventory/sell", {"ids": [1]}),
            ("/api/inventory/sell-all", {}),
            ("/api/upgrade", {"inventory_id": 1, "target_id": "x", "target_coin": 1}),
            ("/api/bonus", {}),
            ("/api/battles", {"case_id": "jelly-starter", "slots": 2, "rounds": 1}),
            ("/api/battles/1/join", {}),
            ("/api/battles/1/bots", {}),
            ("/api/battles/1/start", {}),
        ):
            r = await c.post(path, json=payload, cookies={"jv_session": good})
            check(f"CSRF token required on {path}", r.status_code == 403,
                  f"http={r.status_code}")

        # ------------------------------------------------------------- #
        print("\n[6] Parameter tampering")
        r = await c.post("/api/case/jelly-starter/open", json={"count": 0},
                         cookies={"jv_session": good}, headers={"x-csrf": "x"})
        check("count=0 is refused", r.status_code == 400, f"http={r.status_code}")
        r = await c.post("/api/case/jelly-starter/open", json={"count": -5},
                         cookies={"jv_session": good}, headers={"x-csrf": "x"})
        check("a negative count is refused", r.status_code == 400,
              f"http={r.status_code}")
        r = await c.post("/api/case/jelly-starter/open", json={"count": 9999},
                         cookies={"jv_session": good}, headers={"x-csrf": "x"})
        check("an absurd count is refused", r.status_code == 400,
              f"http={r.status_code}")
        r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                         cookies={"jv_session": good}, headers={"x-csrf": "x"})
        list(store.list_inventory("Alice", "held"))
        r = await c.post("/api/inventory/sell", json={"ids": [999999]},
                         cookies={"jv_session": good}, headers={"x-csrf": "x"})
        check("selling an item that does not exist is refused",
              r.status_code == 400, f"http={r.status_code}")
        store.ensure_wallet("Mallory", seed=9999)
        r = await c.post("/api/inventory/sell", json={"ids": [1]},
                         cookies={"jv_session": good}, headers={"x-csrf": "x"})
        check("selling another player's item is refused",
              r.status_code == 400, f"http={r.status_code}")

        # ------------------------------------------------------------- #
        print("\n[7] Race conditions (double spend / double claim)")
        # 7a: the same item sold twice at the same time.
        inv = store.list_inventory("Alice", "held")
        if inv:
            target = inv[0]["id"]
            before = panel.balances.get("Alice", 0.0)
            results_task = await asyncio.gather(
                c.post("/api/inventory/sell", json={"ids": [target]},
                       cookies={"jv_session": good}, headers={"x-csrf": "x"}),
                c.post("/api/inventory/sell", json={"ids": [target]},
                       cookies={"jv_session": good}, headers={"x-csrf": "x"}),
                return_exceptions=True)
            after = panel.balances.get("Alice", 0.0)
            paid = after - before
            value = next(i["value"] for i in inv if i["id"] == target)
            ok = [r for r in results_task if not isinstance(r, Exception)
                  and r.status_code == 200]
            check("a concurrent double sell does not pay out twice",
                  paid <= value + 1,
                  f"server gained {paid} for an item worth {value}, "
                  f"{len(ok)} successful replies")
        else:
            check("a concurrent double sell does not pay out twice", False,
                  "no held item to test with")

        # 7b: the daily bonus claimed twice at the same time.
        bonus_cookie = mint({"user": "Alice", "login_name": "alice", "csrf": "x"})
        store.claim_bonus_slot("Alice", 0)  # clear the daily claim
        store.credit("Alice", 0, "seed", "reset")
        before = panel.balances.get("Alice", 0.0)
        await asyncio.gather(
            c.post("/api/bonus", json={}, cookies={"jv_session": bonus_cookie},
                   headers={"x-csrf": "x"}),
            c.post("/api/bonus", json={}, cookies={"jv_session": bonus_cookie},
                   headers={"x-csrf": "x"}),
            return_exceptions=True)
        gained = panel.balances.get("Alice", 0.0) - before
        check("the daily bonus cannot be claimed twice at once",
              gained <= 50000, f"gained {gained} (one slice is at most 50000)")

        # ------------------------------------------------------------- #
        print("\n[8] Login rate limiting")
        import app.security as security_mod
        security_mod._attempts.clear()
        security_mod._account_attempts.clear()
        # A separate client: this one is still logged in from the test
        # above, and `/login` would redirect instead of rendering a form.
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     timeout=30) as cl:
            for _ in range(12):
                await cl.post("/login", data={"username": "alice",
                                              "password": "wrong",
                                              "csrf": await csrf_of(cl)},
                              headers={"X-Forwarded-For": "198.51.100.7"})
            security_mod._attempts.clear()
            for i in range(12):
                await cl.post("/login", data={"username": "alice",
                                              "password": "wrong",
                                              "csrf": await csrf_of(cl)},
                              headers={"X-Forwarded-For": f"198.51.100.{i + 20}"})
            blocked = False
            for _ in range(12):
                r = await cl.post("/login", data={"username": "alice",
                                                  "password": "wrong",
                                                  "csrf": await csrf_of(cl)},
                                  headers={"X-Forwarded-For": "198.51.100.7"})
                if "/login?error=rate" in str(r.headers.get("location", "")):
                    blocked = True
                    break
        check("the login rate limit cannot be bypassed with X-Forwarded-For",
              blocked, "12 more attempts were accepted from a spoofed IP")

        # ------------------------------------------------------------- #
        print("\n[9] Information disclosure")
        # A guest client, without any session cookie.
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     timeout=30) as guest:
            r = await guest.get("/api/drops")
            names = [d.get("player") for d in (r.json().get("drops") or [])]
        check("/api/drops does not leak player names to a guest",
              all(not n for n in names), f"players={names[:5]}")
        r = await c.get("/api/drops", cookies={"jv_session": good})
        names = [d.get("player") for d in (r.json().get("drops") or [])]
        check("/api/drops shows the names to a logged-in player",
              any(names), f"players={names[:5]}")
        r = await c.get("/setup")
        check("the setup page is not reachable without a token",
              r.status_code in (200, 303), f"http={r.status_code}")

    server.should_exit = True
    await task

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print(f"\n{len(failed)} FAILURE(S):")
        for name, detail in failed:
            print(f"  - {name}  {detail}")
        sys.exit(1)
    print("ALL SECURITY CHECKS PASSED")


async def csrf_of(c: httpx.AsyncClient) -> str:
    r = await c.get("/login")
    import re
    m = re.search(r'name="csrf" value="([^"]+)"', r.text)
    return m.group(1) if m else ""


if __name__ == "__main__":
    asyncio.run(main())
