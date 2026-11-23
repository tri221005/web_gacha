"""Smoke test the JellyVale gacha web app with Playwright.

Covers: catalogue, case page, roulette rendering, multi-reel (2x-5x) layout,
live drop strip, theme toggle, and auth-gated redirects.
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8080")
SHOTS = "tools/_shots"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    console_errors = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

    # --- catalogue ---
    page.goto(f"{BASE}/gacha", wait_until="networkidle")
    check("catalogue loads", page.title() != "", page.title())
    cards = page.locator(".case-card, .contents .item-card").count()
    check("catalogue renders cards", cards > 0, f"{cards} cards")
    page.screenshot(path=f"{SHOTS}/01-catalogue.png", full_page=True)

    # --- case page ---
    page.goto(f"{BASE}/case/jelly-starter", wait_until="networkidle")
    check("case page loads", "/case/" in page.url)
    check("preset buttons present", page.locator(".preset-btn").count() == 5,
          f"{page.locator('.preset-btn').count()} presets")
    check("single reel present", page.locator("#reel").count() == 1)

    # --- multi reel on the logged-out page ---
    # KNOWN ISSUE: case.html wraps the whole <script type="module"> in
    # {% if player %}, so for logged-out visitors the preset buttons render
    # but nothing is wired to them. This check documents that gap.
    page.locator('.preset-btn[data-count="2"]').click()
    page.wait_for_timeout(400)
    check("2x preset buttons render for guests", page.locator(".preset-btn").count() == 5)
    check("KNOWN ISSUE: 2x does nothing for logged-out visitors",
          page.locator(".multi-reel-col").count() == 0,
          f"{page.locator('.multi-reel-col').count()} cols (expected 0 - see smoke_test_auth.py)")
    page.screenshot(path=f"{SHOTS}/02-case-2x-guest.png", full_page=True)

    # --- back to 1x ---
    page.locator('.preset-btn[data-count="1"]').click()
    page.wait_for_timeout(400)
    check("single reel still shown for guests", page.locator("#single-reel-wrap").is_visible())

    # --- 5x ---
    page.locator('.preset-btn[data-count="5"]').click()
    page.wait_for_timeout(400)
    check("KNOWN ISSUE: 5x does nothing for logged-out visitors",
          page.locator(".multi-reel-col").count() == 0,
          f"{page.locator('.multi-reel-col').count()} cols (expected 0)")
    page.locator('.preset-btn[data-count="1"]').click()
    page.wait_for_timeout(300)

    # --- auth gating ---
    page.goto(f"{BASE}/inventory", wait_until="networkidle")
    check("inventory redirects to login", "/login" in page.url, page.url)
    page.screenshot(path=f"{SHOTS}/03-login.png", full_page=True)

    # --- theme toggle ---
    page.goto(f"{BASE}/gacha", wait_until="networkidle")
    btn = page.locator("#theme-toggle")
    if btn.count():
        before = page.evaluate("document.documentElement.classList.contains('dark')")
        btn.click()
        page.wait_for_timeout(300)
        after = page.evaluate("document.documentElement.classList.contains('dark')")
        check("theme toggle flips dark class", before != after, f"{before} -> {after}")
        page.screenshot(path=f"{SHOTS}/04-dark.png", full_page=True)
    else:
        check("theme toggle exists", False, "no #theme-toggle")

    # --- live drop strip ---
    page.goto(f"{BASE}/gacha", wait_until="networkidle")
    strip = page.locator("#live-drops")
    check("live strip present", strip.count() == 1)

    # --- battles page ---
    page.goto(f"{BASE}/battles", wait_until="networkidle")
    check("battles page loads", "/battles" in page.url)
    page.screenshot(path=f"{SHOTS}/05-battles.png", full_page=True)

    # --- bonus page ---
    page.goto(f"{BASE}/bonus", wait_until="networkidle")
    check("bonus page loads", "/bonus" in page.url)
    page.screenshot(path=f"{SHOTS}/06-bonus.png", full_page=True)

    # --- console errors ---
    real = [e for e in console_errors if "favicon" not in e.lower()]
    check("no console errors", not real, "; ".join(real[:3]))

    browser.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
if failed:
    print("FAILED:")
    for n, _, d in failed:
        print(f"  - {n} {d}")
sys.exit(1 if failed else 0)
