"""Check that the login accepts the name in any casing.

AuthMe stores the username lowercased while ExcellentEconomy keeps the
capitalised realname. A player typing "Trez1724" must still log in and
must land on the same wallet as "trez1724".
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright  # noqa: E402

from app.pika import sqlite_query  # noqa: E402

BASE = os.environ.get("LOGIN_TEST_BASE", "http://127.0.0.1:8123")
PASSWORD = os.environ.get("LOGIN_TEST_PASSWORD", "matkhau123")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))


async def main() -> None:
    rows = await sqlite_query(
        "/plugins/AuthMe/authme.db",
        "SELECT username, realname FROM authme "
        "WHERE realname <> username ORDER BY realname LIMIT 8",
        rows=20,
    )
    print(f"testing {len(rows)} accounts whose stored name has capitals\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        for index, row in enumerate(rows, start=1):
            username = str(row["username"])
            realname = str(row["realname"])
            variants = [realname, realname.upper(), username]

            for variant in variants:
                ctx = await browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    extra_http_headers={"X-Forwarded-For": f"192.0.2.{index}"},
                )
                page = await ctx.new_page()
                await page.goto(f"{BASE}/login", wait_until="networkidle")
                await page.fill("input[name=username]", variant)
                await page.fill("input[name=password]", PASSWORD)
                await page.click("button[type=submit]")
                await page.wait_for_load_state("networkidle")

                logged_in = "/login" not in page.url
                name = ""
                if logged_in:
                    name = await page.locator(".avatar-link .hide-sm").inner_text() \
                        if await page.locator(".avatar-link .hide-sm").count() else ""

                check(f"[{realname}] typed '{variant}' logs in", logged_in,
                      f"url={page.url}")
                check(f"[{realname}] typed '{variant}' shows the real name",
                      name.strip() == realname, f"shown={name.strip()!r}")
                await ctx.close()

        await browser.close()

    passed = sum(1 for _, ok, _ in results if ok)
    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{passed}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"  - {name}  {detail}")
        sys.exit(1)
    print("CASING IS HANDLED CORRECTLY")


asyncio.run(main())
