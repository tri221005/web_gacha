"""Screenshot the admin crew tab on desktop and mobile."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

from mint_cookie import mint  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app.config import ADMIN_USERS  # noqa: E402

ADMIN = next(iter(ADMIN_USERS))
BASE = os.getenv("BASE_URL", "http://127.0.0.1:8081")
COOKIE = mint({"user": ADMIN, "login_name": ADMIN, "csrf": "shot-csrf"})
OUT = os.path.join(ROOT, "tools", "_shots")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for label, width, height in (("desktop", 1440, 950),
                                  ("mobile", 390, 844)):
        ctx = browser.new_context(viewport={"width": width, "height": height})
        ctx.add_cookies([{"name": "jv_session", "value": COOKIE,
                          "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e, errs=errors: errs.append(str(e)))
        page.goto(f"{BASE}/admin?tab=admins", wait_until="networkidle")
        page.wait_for_timeout(6000)
        rows = page.locator("#admins-body tr").count()
        overflow = page.evaluate(
            "() => ({doc: document.documentElement.scrollWidth,"
            " win: window.innerWidth})")
        print(f"{label}: rows={rows} overflow={overflow} errors={errors}")
        page.screenshot(path=os.path.join(OUT, f"admins_{label}.png"),
                        full_page=True)
        ctx.close()
    browser.close()
