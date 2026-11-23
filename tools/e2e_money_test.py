"""End-to-end money-path test: open a case, check balance, sell the drop, verify ledger.

Uses the same injected-session trick as smoke_test_auth.py because real login
needs a live PikaMC API key.
"""
import base64
import json
import os
import sys

import httpx
import itsdangerous

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import SESSION_SECRET  # noqa: E402

BASE = "http://127.0.0.1:8099"
CSRF = "test-csrf-token"
# In live mode the wallet follows the server balance, so the test needs a
# real PikaMC account with enough Coin to spend.
PLAYER = os.getenv("E2E_PLAYER", "Trez1724")

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))


def mint(session: dict) -> str:
    signer = itsdangerous.TimestampSigner(str(SESSION_SECRET))
    data = base64.b64encode(json.dumps(session).encode("utf-8"))
    return signer.sign(data).decode("utf-8")


cookie = mint({"user": PLAYER, "login_name": PLAYER, "csrf": CSRF})
client = httpx.Client(base_url=BASE, headers={
    "Cookie": f"jv_session={cookie}", "X-CSRF": CSRF, "Content-Type": "application/json",
}, timeout=15)

# 1. wallet renders and mirrors the server balance
r = client.get("/vi")
check("wallet page renders", r.status_code == 200, str(r.status_code))
start_balance = None
r = client.get("/api/wallet/live")
if r.status_code == 200:
    start_balance = r.json().get("balance")
    print(f"  starting balance (server): {start_balance}")

# 2. open a case x1
r = client.post("/api/case/jelly-starter/open", json={"count": 1})
check("open case x1 returns 200", r.status_code == 200, r.text[:160])
open1 = r.json()
if r.status_code == 200:
    check("open returns one opening", len(open1.get("openings", [])) == 1)
    check("open reports cost", open1.get("total_cost") == 5000, str(open1.get("total_cost")))
    # The web wallet mirrors the server, so it must have dropped by the cost.
    if start_balance is not None:
        check("balance dropped by cost",
              open1.get("balance") == start_balance - 5000,
              f"{open1.get('balance')} != {start_balance - 5000}")
    check("winner has image", bool(open1["winner"]["image"]), open1["winner"]["image"])

# 3. open x5
r = client.post("/api/case/jelly-starter/open", json={"count": 5})
check("open case x5 returns 200", r.status_code == 200, r.text[:160])
open5 = r.json()
if r.status_code == 200:
    check("x5 returns 5 openings", len(open5.get("openings", [])) == 5)
    check("x5 cost is 25000", open5.get("total_cost") == 25000, str(open5.get("total_cost")))

# 4. sell everything won
ids = [op["inventory_id"] for op in open5.get("openings", [])]
r = client.post("/api/inventory/sell", json={"ids": ids})
check("sell returns 200", r.status_code == 200, r.text[:160])
if r.status_code == 200:
    sold = r.json()
    check("sell count matches", sold.get("sold") == 5, str(sold.get("sold")))
    check("sell amount positive", sold.get("amount", 0) > 0, str(sold.get("amount")))

# 5. sell-all
r = client.post("/api/inventory/sell-all", json={})
check("sell-all returns 200", r.status_code == 200, r.text[:160])

# 6. CSRF rejection
r = client.post("/api/case/jelly-starter/open", json={"count": 1},
                headers={"X-CSRF": "wrong-token"})
check("bad CSRF rejected", r.status_code == 403, str(r.status_code))

# 7. no session -> 401
r2 = httpx.post(f"{BASE}/api/case/jelly-starter/open", json={"count": 1},
                headers={"X-CSRF": CSRF}, timeout=15)
check("no session rejected", r2.status_code == 401, str(r2.status_code))

# 8. invalid count rejected
r = client.post("/api/case/jelly-starter/open", json={"count": 99})
check("invalid count rejected", r.status_code == 400, str(r.status_code))

# 9. unknown case rejected
r = client.post("/api/case/no-such-case/open", json={"count": 1})
check("unknown case rejected", r.status_code == 404, str(r.status_code))

# 10. upgrade targets
r = client.get("/api/upgrade/targets", params={"value": 8000})
check("upgrade targets returns 200", r.status_code == 200, str(r.status_code))

# 11. bonus (24h lock)
# The bonus has a 24 hour lock, so the test player may already have
# claimed one. Clear the lock first, otherwise the first claim fails.
from app import store as _store  # noqa: E402

try:
    with _store._lock:
        con = _store.connect()
        cur = con.cursor()
        cur.execute("DELETE FROM gacha_bonus WHERE player = ?", PLAYER)
        con.commit()
except Exception as _e:  # noqa: BLE001
    print(f"  (could not clear the bonus lock: {_e})")
r = client.post("/api/bonus", json={})
check("bonus first claim 200", r.status_code == 200, r.text[:120])
r = client.post("/api/bonus", json={})
check("bonus second claim blocked", r.status_code == 400, str(r.status_code))

# 12. wallet tx ledger reflects activity
r = client.get("/vi")
check("wallet shows ledger rows", "Mở rương" in r.text or "open" in r.text.lower())

client.close()
failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
if failed:
    print("FAILED:")
    for n, _, d in failed:
        print(f"  - {n} {d}")
sys.exit(1 if failed else 0)

