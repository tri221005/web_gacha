"""Screenshot the admin login page and the console with the log tab."""
from __future__ import annotations

import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8080")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from mint_cookie import mint  # noqa: E402

from app.config import ADMIN_USERS  # noqa: E402

ADMIN = next(iter(ADMIN_USERS))
COOKIE = mint({"user": ADMIN, "login_name": ADMIN, "csrf": "x"})
OUT = os.path.join(ROOT, "tools", "_shots")
os.makedirs(OUT, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    # Trang đăng nhập admin (không cookie)
    for label, w, h in (("desktop", 1440, 950), ("mobile", 390, 844)):
        ctx = browser.new_context(viewport={"width": w, "height": h})
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e, errs=errors: errs.append(str(e)))
        page.goto(f"{BASE}/admin/login", wait_until="networkidle")
        page.wait_for_timeout(500)
        path = os.path.join(OUT, f"adminlogin_{label}.png")
        page.screenshot(path=path, full_page=True)
        print("saved", path)
        over = page.evaluate("() => ({doc: document.documentElement.scrollWidth,"
                             " win: window.innerWidth})")
        print(label, "overflow:", over)
        if errors:
            print(label, "ERRORS:", errors[:3])
        ctx.close()

    # Console với tab nhật ký
    ctx = browser.new_context(viewport={"width": 1440, "height": 950})
    ctx.add_cookies([{"name": "jv_session", "value": COOKIE, "url": BASE}])
    page = ctx.new_page()
    page.goto(f"{BASE}/admin?tab=log", wait_until="networkidle")
    page.wait_for_timeout(1200)
    path = os.path.join(OUT, "admin_desktop_log.png")
    page.screenshot(path=path, full_page=True)
    print("saved", path)
    print("log rows:", page.locator("#log-body tr").count())
    ctx.close()
    browser.close()
