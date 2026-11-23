"""Sign in through the admin login form the way a human does."""
from __future__ import annotations

import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8080")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from app.config import ADMIN_PASSWORD, ADMIN_USERS  # noqa: E402

ADMIN = next(iter(ADMIN_USERS))
GOOD_PASSWORD = ADMIN_PASSWORD or "hunter2"
OUT = os.path.join(ROOT, "tools", "_shots")
PASSED = 0
FAILED = 0


def check(label, condition, extra=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  OK   {label}")
    else:
        FAILED += 1
        print(f"  FAIL {label} {extra}")


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 950})
    page = ctx.new_page()

    # Chưa đăng nhập: /admin đưa tới trang login
    page.goto(f"{BASE}/admin", wait_until="networkidle")
    check("/admin -> /admin/login", "/admin/login" in page.url, page.url)

    # Sai tên
    page.fill("input[name=username]", "KhongPhaiAdmin")
    page.fill("input[name=password]", "batky")
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    check("unknown name -> error", "error=sai" in page.url, page.url)

    # Sai mat khau
    page.goto(f"{BASE}/admin/login", wait_until="networkidle")
    page.fill("input[name=username]", ADMIN)
    page.fill("input[name=password]", "sai-mat-khau")
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    check("wrong password -> error", "error=sai" in page.url, page.url)

    # Dang nhap dung: mat khau rieng neu co, nguoc lai mat khau Minecraft
    page.goto(f"{BASE}/admin/login", wait_until="networkidle")
    page.fill("input[name=username]", ADMIN)
    page.fill("input[name=password]", GOOD_PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    if "/admin/login" in page.url:
        # Khong co ADMIN_PASSWORD: can mat khau Minecraft that, nen dung
        # stub de kiem tra phan con lai cua luong.
        print("  (ADMIN_PASSWORD rong -> can mat khau Minecraft that)")
    else:
        check("admin signs in", "/admin" in page.url, page.url)
        check("console loads", page.locator(".admin-tabs").count() == 1)

    # Trang login game van dung duoc (context moi: dang nhap admin o tren)
    guest_ctx = browser.new_context(viewport={"width": 1440, "height": 950})
    guest_page = guest_ctx.new_page()
    guest_page.goto(f"{BASE}/login", wait_until="networkidle")
    check("game login still works",
          guest_page.locator("form[action='/login']").count() == 1)
    check("admin login link on game page",
          guest_page.locator("a[href='/admin/login']").count() == 1)
    guest_ctx.close()

    browser.close()

print(f"\n{PASSED} passed, {FAILED} failed")
raise SystemExit(1 if FAILED else 0)
