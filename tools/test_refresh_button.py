"""Click the wallet refresh button and verify it pulls the live balance.

The ledger is corrupted while the page is already open, so the repair has to
come from the refresh button itself.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright  # noqa: E402

from app import store  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

BASE = "http://127.0.0.1:8099"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shots")


async def main() -> None:
    store.init()
    cookie = mint({"user": "hhh21", "login_name": "hhh21", "csrf": "x"})
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_cookies([{
            "name": "jv_session", "value": cookie, "domain": "127.0.0.1", "path": "/",
        }])
        page = await ctx.new_page()

        await page.goto(f"{BASE}/vi", wait_until="networkidle")
        shown = await page.inner_text("#balance")
        print(f"balance shown on load : {shown}")

        # Corrupt the ledger while the page stays open.
        store.set_balance("hhh21", 999, "sync", "test")
        print("ledger corrupted to 999 (page still shows the old value)")

        # Press refresh: it must pull the live balance back.
        await page.click("#sync-btn")
        await page.wait_for_timeout(2500)
        after = await page.inner_text("#balance")
        chip = await page.inner_text(".coin-chip span")
        button = await page.inner_text("#sync-btn")
        print(f"balance after refresh : {after}")
        print(f"header chip           : {chip}")
        print(f"button label          : {button}")
        await page.screenshot(path=os.path.join(OUT, "wallet-refreshed.png"))

        assert after == shown, f"refresh changed the balance wrongly: {after} != {shown}"
        assert chip.replace(" Coin", "") == after, "the header chip did not update"
        assert "Đã đồng bộ" in button or "Làm mới" in button, f"button label: {button}"

        # the stored ledger must now match the server too
        stored = store.get_balance("hhh21")
        print(f"ledger after refresh  : {stored}")
        assert stored != 999, "the ledger was not repaired"

    print("\nREFRESH BUTTON CHECK PASSED")


asyncio.run(main())
