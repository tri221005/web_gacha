"""Summarise the login test per player: identity, live balance, protected pages."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright  # noqa: E402

from app.pika import find_economy_user, sqlite_query  # noqa: E402

BASE = os.environ.get("LOGIN_TEST_BASE", "http://127.0.0.1:8123")
PASSWORD = os.environ.get("LOGIN_TEST_PASSWORD", "matkhau123")


async def main() -> None:
    rows = await sqlite_query(
        "/plugins/AuthMe/authme.db",
        "SELECT username, realname FROM authme ORDER BY realname",
        rows=500,
    )

    print(f"{'player':<20} {'login name':<20} {'live balance':>14}  {'web':>14}  ok")
    print("-" * 88)

    failures = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        for index, row in enumerate(rows, start=1):
            username = str(row.get("username") or "")
            realname = str(row.get("realname") or "")
            eco = await find_economy_user(username)
            live = float(eco["money"]) if eco else 0.0
            expected = f"{int(live):,}".replace(",", ".")

            ctx = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"X-Forwarded-For": f"198.51.100.{index}"},
            )
            page = await ctx.new_page()
            ok = False
            shown = "-"
            try:
                await page.goto(f"{BASE}/login", wait_until="networkidle")
                await page.fill("input[name=username]", username)
                await page.fill("input[name=password]", PASSWORD)
                await page.click("button[type=submit]")
                await page.wait_for_load_state("networkidle")
                if "/login" not in page.url:
                    chip = await page.locator(".coin-chip span").first.inner_text()
                    shown = chip.replace(" Coin", "").strip()
                    ok = shown == expected
            except Exception as exc:
                shown = f"error: {str(exc)[:30]}"
            await ctx.close()

            if not ok:
                failures += 1
            print(f"{realname:<20} {username:<20} {expected:>14}  {shown:>14}  "
                  f"{'OK' if ok else 'FAIL'}")

        await browser.close()

    print("-" * 88)
    print(f"{len(rows) - failures}/{len(rows)} players logged in with the live balance")
    if failures:
        sys.exit(1)


asyncio.run(main())
