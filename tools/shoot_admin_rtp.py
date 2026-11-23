"""Screenshot the admin case editor, to check the RTP warning.

The RTP of a case over 100 means the house loses money, so the admin
console flags it. This checks the flag is there and says the right thing.

Run:  python tools/shoot_admin_rtp.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8082")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
os.makedirs(OUT, exist_ok=True)

ADMIN = os.getenv("ADMIN_USER", "hhh21")
PASSWORD = os.getenv("ADMIN_PASSWORD", "")


def main() -> None:
    if not PASSWORD:
        print("ADMIN_PASSWORD is not set, skipping.")
        return
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        page.goto(f"{BASE}/admin/login", wait_until="networkidle")
        page.fill("input[name='username']", ADMIN)
        page.fill("input[name='password']", PASSWORD)
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1200)
        page.goto(f"{BASE}/admin?tab=cases", wait_until="networkidle")
        page.wait_for_timeout(1800)
        page.screenshot(path=f"{OUT}/admin-rtp.png", full_page=True)
        flags = page.eval_on_selector_all(
            ".case-rtp.case-rtp-over",
            "els => els.map(e => e.textContent.trim())",
        )
        print(f"  screenshot -> {OUT}/admin-rtp.png")
        print("  flagged cases:", flags or "none")
        browser.close()


main()
