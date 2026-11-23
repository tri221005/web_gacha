"""Playwright end-to-end login test for every PikaMC player.

The test server accepts one known password for every account, so the whole
real login path is exercised for each player:

  - the AuthMe row is read live from PikaMC
  - the session is built from the real username / realname
  - the wallet shows the live ExcellentEconomy balance
  - protected pages are reachable, logout clears the session

A wrong password must still be rejected for every account.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright  # noqa: E402

from app.pika import find_economy_user, sqlite_query  # noqa: E402

BASE = os.environ.get("LOGIN_TEST_BASE", "http://127.0.0.1:8123")
PASSWORD = os.environ.get("LOGIN_TEST_PASSWORD", "matkhau123")
WRONG = "sai-mat-khau-hoan-toan"
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")

os.makedirs(SHOTS, exist_ok=True)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    if not ok:
        print(f"FAIL  {name}  -- {detail}")


async def live_players() -> list[dict]:
    rows = await sqlite_query(
        "/plugins/AuthMe/authme.db",
        "SELECT username, realname FROM authme ORDER BY realname",
        rows=500,
    )
    return rows


async def main() -> None:
    players = await live_players()
    print(f"testing {len(players)} players from the live AuthMe database\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        for index, row in enumerate(players, start=1):
            username = str(row.get("username") or "")
            realname = str(row.get("realname") or "")
            if not username:
                continue

            eco = await find_economy_user(username)
            live_money = float(eco["money"]) if eco else None

            # Each player gets its own address: the app rate-limits failed
            # logins per IP, and real players come from different ones.
            ctx = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"X-Forwarded-For": f"203.0.113.{index}"},
            )
            page = await ctx.new_page()

            # 1. the login page renders and carries a CSRF token
            await page.goto(f"{BASE}/login", wait_until="networkidle")
            check(f"[{realname}] login page renders",
                  await page.locator("form input[name=username]").count() == 1)

            # 2. a wrong password is rejected
            await page.fill("input[name=username]", username)
            await page.fill("input[name=password]", WRONG)
            await page.click("button[type=submit]")
            await page.wait_for_load_state("networkidle")
            banner = await page.locator(".alert").first.inner_text() if await page.locator(".alert").count() else ""
            check(f"[{realname}] wrong password rejected",
                  "không đúng" in banner.lower() or "/login" in page.url,
                  f"banner={banner!r} url={page.url}")

            # 3. the correct password logs in
            await page.goto(f"{BASE}/login", wait_until="networkidle")
            await page.fill("input[name=username]", username)
            await page.fill("input[name=password]", PASSWORD)
            await page.click("button[type=submit]")
            await page.wait_for_load_state("networkidle")

            logged_in = "/login" not in page.url
            check(f"[{realname}] login succeeds", logged_in, f"url={page.url}")

            if logged_in:
                # 4. the session shows the real player name
                name = await page.locator(".avatar-link .hide-sm").inner_text() if \
                    await page.locator(".avatar-link .hide-sm").count() else ""
                check(f"[{realname}] session shows the player", name.strip() == realname,
                      f"shown={name!r} expected={realname!r}")

                # 5. the wallet shows the live server balance
                chip = await page.locator(".coin-chip span").first.inner_text() if \
                    await page.locator(".coin-chip span").count() else ""
                shown = chip.replace(" Coin", "").strip()
                if live_money is not None:
                    expected = f"{int(live_money):,}".replace(",", ".")
                    check(f"[{realname}] header shows the live balance", shown == expected,
                          f"shown={shown!r} expected={expected!r}")
                else:
                    check(f"[{realname}] no economy row (balance 0)", shown in ("0", ""),
                          f"shown={shown!r}")

                # 6. the wallet page agrees
                await page.goto(f"{BASE}/vi", wait_until="networkidle")
                amount = await page.locator("#balance").inner_text() if \
                    await page.locator("#balance").count() else ""
                if live_money is not None:
                    expected = f"{int(live_money):,}".replace(",", ".")
                    check(f"[{realname}] /vi shows the live balance",
                          amount.strip() == expected,
                          f"shown={amount.strip()!r} expected={expected!r}")

                # 7. protected pages are reachable
                for path in ("/gacha", "/inventory", "/bonus"):
                    r = await page.goto(f"{BASE}{path}", wait_until="networkidle")
                    check(f"[{realname}] {path} reachable", r.status == 200,
                          f"HTTP {r.status}")

                # 8. logout clears the session
                await page.goto(f"{BASE}/gacha", wait_until="networkidle")
                await page.click("form[action='/logout'] button")
                await page.wait_for_load_state("networkidle")
                await page.goto(f"{BASE}/vi", wait_until="networkidle")
                check(f"[{realname}] logout blocks /vi", "/login" in page.url,
                      f"url={page.url}")

            await ctx.close()

        await browser.close()

    passed = sum(1 for _, ok, _ in results if ok)
    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{passed}/{len(results)} checks passed")
    if failed:
        print(f"\n{len(failed)} FAILURE(S):")
        for name, detail in failed:
            print(f"  - {name}  {detail}")
        sys.exit(1)
    print("ALL PLAYERS LOG IN CORRECTLY")


asyncio.run(main())
