"""Click through the admin console the way an admin would.

Every write is done on a copy of gacha.json and restored afterwards.
"""
from __future__ import annotations

import os
import shutil
import sys

from playwright.sync_api import sync_playwright

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8080")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from mint_cookie import mint  # noqa: E402

from app.config import ADMIN_USERS  # noqa: E402
from app.gacha import GACHA_FILE  # noqa: E402

ADMIN = next(iter(ADMIN_USERS))
COOKIE = mint({"user": ADMIN, "login_name": ADMIN, "csrf": "test-csrf-token"})
BACKUP = GACHA_FILE.with_suffix(".json.uibak")
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


shutil.copy2(GACHA_FILE, BACKUP)
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 950})
        ctx.add_cookies([{"name": "jv_session", "value": COOKIE, "url": BASE}])
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # ---- Tab switching ----
        page.goto(f"{BASE}/admin", wait_until="networkidle")
        page.click(".admin-tab[data-tab='players']")
        page.wait_for_timeout(900)
        check("players tab loads rows", page.locator("#players-body tr").count() > 0)
        check("url updated", "tab=players" in page.url, page.url)

        # ---- Search ----
        page.fill("#players-search", "Trez")
        page.wait_for_timeout(700)
        rows = page.locator("#players-body tr").count()
        check("search narrows the list", 0 < rows <= 5, f"rows={rows}")

        # ---- Tx tab ----
        page.click(".admin-tab[data-tab='tx']")
        page.wait_for_timeout(900)
        check("tx tab loads rows", page.locator("#tx-body tr").count() > 0)
        page.select_option("#tx-kind", "open")
        page.wait_for_timeout(800)
        kinds = page.locator("#tx-body tr td:nth-child(3)").all_inner_texts()
        check("kind filter works", all(k == "Mở rương" for k in kinds), str(kinds[:3]))

        # ---- Cases tab: edit a name ----
        page.click(".admin-tab[data-tab='cases']")
        page.wait_for_timeout(1100)
        cards = page.locator(".case-admin-card").count()
        check("case cards render", cards > 0, f"cards={cards}")
        first = page.locator(".case-admin-card").first
        before = first.locator(".case-name").input_value()
        first.locator(".case-name").fill(before + " EDIT")
        first.locator("[data-save-case]").click()
        page.wait_for_timeout(1400)
        after = page.locator(".case-admin-card").first.locator(".case-name").input_value()
        check("case name saved", after.endswith(" EDIT"), f"{before!r} -> {after!r}")

        # ---- Add an item ----
        first = page.locator(".case-admin-card").first
        n_before = first.locator(".case-items tbody tr").count()
        first.locator(".new-item-id").fill("zzz_test_item")
        first.locator(".new-item-name").fill("Món thử")
        first.locator(".new-item-coin").fill("1234")
        first.locator(".new-item-weight").fill("2")
        first.locator("[data-add-item]").click()
        page.wait_for_timeout(1400)
        first = page.locator(".case-admin-card").first
        n_after = first.locator(".case-items tbody tr").count()
        check("item added", n_after == n_before + 1, f"{n_before} -> {n_after}")
        check("new item id kept",
              "zzz_test_item" in first.locator(".case-items tbody").inner_html())

        # ---- Remove it again ----
        first.locator("[data-remove-item='zzz_test_item']").click()
        page.wait_for_timeout(1400)
        n_final = page.locator(".case-admin-card").first.locator(".case-items tbody tr").count()
        check("item removed", n_final == n_before, f"{n_after} -> {n_final}")

        # ---- Battle tab ----
        page.click(".admin-tab[data-tab='battles']")
        page.wait_for_timeout(1100)
        check("battles render", page.locator(".battle-admin-card").count() > 0)

        # ---- Player page ----
        page.goto(f"{BASE}/admin/player/{ADMIN}", wait_until="networkidle")
        check("player page shows coin form", page.locator("#coin-amount").count() == 1)
        check("player page shows ban form", page.locator("#ban-set") is not None)

        check("no JS errors", not errors, str(errors[:3]))
        browser.close()
finally:
    shutil.copy2(BACKUP, GACHA_FILE)
    BACKUP.unlink(missing_ok=True)

print(f"\n{PASSED} passed, {FAILED} failed")
raise SystemExit(1 if FAILED else 0)
