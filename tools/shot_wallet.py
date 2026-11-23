"""Screenshot the wallet page with a live PikaMC session."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright  # noqa: E402

from tools.mint_cookie import mint  # noqa: E402

BASE = "http://127.0.0.1:8099"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shots")


async def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    cookie = mint({"user": "Trez1724", "login_name": "trez1724", "csrf": "x"})
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_cookies([{
            "name": "jv_session", "value": cookie, "domain": "127.0.0.1",
            "path": "/",
        }])
        page = await ctx.new_page()
        for path, name in (("/vi", "wallet"), ("/gacha", "catalogue")):
            await page.goto(f"{BASE}{path}", wait_until="networkidle")
            await page.screenshot(path=os.path.join(OUT, f"{name}.png"))
            print(f"saved {name}.png")
        await browser.close()


asyncio.run(main())
