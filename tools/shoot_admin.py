"""Screenshot the admin console on desktop and mobile."""
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
COOKIE = mint({"user": ADMIN, "login_name": ADMIN, "csrf": "test-csrf-token"})
OUT = os.path.join(ROOT, "tools", "_shots")
os.makedirs(OUT, exist_ok=True)

TABS = ["overview", "players", "cases", "tx", "battles"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for label, width, height in (("desktop", 1440, 950), ("mobile", 390, 844)):
        ctx = browser.new_context(viewport={"width": width, "height": height})
        ctx.add_cookies([{"name": "jv_session", "value": COOKIE, "url": BASE}])
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m, errs=errors: errs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e, errs=errors: errs.append(str(e)))

        page.goto(f"{BASE}/admin", wait_until="networkidle")
        for tab in TABS:
            page.goto(f"{BASE}/admin?tab={tab}", wait_until="networkidle")
            page.wait_for_timeout(900)
            path = os.path.join(OUT, f"admin_{label}_{tab}.png")
            page.screenshot(path=path, full_page=True)
            print("saved", path)

        # Hồ sơ người chơi
        page.goto(f"{BASE}/admin/player/{ADMIN}", wait_until="networkidle")
        page.wait_for_timeout(600)
        path = os.path.join(OUT, f"admin_{label}_player.png")
        page.screenshot(path=path, full_page=True)
        print("saved", path)

        # Tràn ngang?
        overflow = page.evaluate(
            "() => ({doc: document.documentElement.scrollWidth,"
            " win: window.innerWidth,"
            " body: document.body.scrollWidth})")
        print(label, "overflow:", overflow)
        if errors:
            print(label, "CONSOLE ERRORS:", errors[:5])
        ctx.close()
    browser.close()
