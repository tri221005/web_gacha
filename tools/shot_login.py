"""Screenshot the login page and a logged-in wallet for the report."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright  # noqa: E402

BASE = os.environ.get("LOGIN_TEST_BASE", "http://127.0.0.1:8123")
PASSWORD = os.environ.get("LOGIN_TEST_PASSWORD", "matkhau123")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shots")

os.makedirs(OUT, exist_ok=True)


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()

        await page.goto(f"{BASE}/login", wait_until="networkidle")
        await page.screenshot(path=os.path.join(OUT, "login.png"))
        print("saved login.png")

        await page.fill("input[name=username]", "Trez1724")
        await page.fill("input[name=password]", PASSWORD)
        await page.click("button[type=submit]")
        await page.wait_for_load_state("networkidle")
        await page.goto(f"{BASE}/vi", wait_until="networkidle")
        await page.screenshot(path=os.path.join(OUT, "wallet.png"))
        print("saved wallet.png")

        await browser.close()


asyncio.run(main())
