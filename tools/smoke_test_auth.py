"""Test the authenticated case page (multi-reel 2x-5x) by injecting a session cookie.

The real login needs a live PikaMC API key, so we mint a session cookie
signed with the app's SESSION_SECRET to render the `player` branch of case.html.
"""
import base64
import json
import os
import sys

import itsdangerous
from playwright.sync_api import sync_playwright

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8080")
SHOTS = "tools/_shots"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import SESSION_SECRET  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))


def mint(session: dict) -> str:
    """Mint a cookie exactly like starlette's SessionMiddleware does."""
    signer = itsdangerous.TimestampSigner(str(SESSION_SECRET))
    data = base64.b64encode(json.dumps(session).encode("utf-8"))
    return signer.sign(data).decode("utf-8")


cookie_value = mint({"user": "Tester", "login_name": "Tester", "csrf": "test-csrf-token"})

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_cookies([{
        "name": "jv_session", "value": cookie_value,
        "domain": "127.0.0.1", "path": "/",
    }])
    page = ctx.new_page()

    console_errors = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

    page.goto(f"{BASE}/case/jelly-starter", wait_until="domcontentloaded")
    page.wait_for_selector("#open-btn", timeout=15000)
    check("case page renders logged-in", page.locator("#open-btn").count() == 1,
          f"open-btn count={page.locator('#open-btn').count()}")

    for n in (2, 3, 4, 5):
        page.locator(f'.preset-btn[data-count="{n}"]').click()
        page.wait_for_timeout(400)
        cols = page.locator(".multi-reel-col").count()
        check(f"{n}x creates {n} columns", cols == n, f"{cols} cols")
        check(f"{n}x hides single reel", not page.locator("#single-reel-wrap").is_visible())

    page.locator('.preset-btn[data-count="1"]').click()
    page.wait_for_timeout(400)
    check("1x restores single reel", page.locator("#single-reel-wrap").is_visible())
    check("1x hides multi reel", not page.locator("#multi-reels-wrap").is_visible())

    page.screenshot(path=f"{SHOTS}/07-case-auth-1x.png", full_page=True)
    page.locator('.preset-btn[data-count="3"]').click()
    page.wait_for_timeout(400)
    page.screenshot(path=f"{SHOTS}/08-case-auth-3x.png", full_page=True)

    # open button label reflects the chosen count
    label = page.locator("#open-btn").inner_text()
    check("open button shows x3 cost", "×3" in label or "x3" in label, label)

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
