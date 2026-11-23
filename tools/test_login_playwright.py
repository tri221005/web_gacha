"""Playwright end-to-end test of the login flow.

Covers: the login form, CSRF protection, wrong password, unknown user,
successful login, session persistence, protected pages, logout, and the
rate limiter.
"""
from __future__ import annotations

import base64
import json
import os
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ.get("LOGIN_TEST_BASE", "http://127.0.0.1:8123")
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
# A real player on the live server: the login flow reads AuthMe for it.
USER = os.environ.get("LOGIN_TEST_USER", "Trez1724")
PASSWORD = os.getenv("LOGIN_TEST_PASSWORD", "matkhau123")

os.makedirs(SHOTS, exist_ok=True)


def decode_session(cookie_value: str) -> dict:
    """Read the session payload out of a signed starlette cookie."""
    import itsdangerous

    from app.config import SESSION_SECRET

    signer = itsdangerous.TimestampSigner(str(SESSION_SECRET))
    data = signer.unsign(cookie_value.encode("utf-8"))
    return json.loads(base64.b64decode(data))


results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))


def error_banner(page) -> str:
    """Return the text of the visible alert on the login page."""
    banner = page.locator(".alert")
    if banner.count() == 0:
        return ""
    return banner.first.inner_text().strip()


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    console_errors: list[str] = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

    # ---------------------------------------------------------------- form
    page.goto(f"{BASE}/login", wait_until="networkidle")
    check("login page loads", "Đăng nhập" in page.title(), page.title())
    check("username field present", page.locator('input[name="username"]').count() == 1)
    check("password field present", page.locator('input[name="password"]').count() == 1)
    check("password field is masked",
          page.get_attribute('input[name="password"]', "type") == "password")
    check("csrf token present",
          bool(page.get_attribute('input[name="csrf"]', "value")))
    check("submit button enabled",
          page.locator('button[type="submit"]').is_enabled())
    page.screenshot(path=f"{SHOTS}/login-01-form.png", full_page=True)

    # ------------------------------------------------- empty fields blocked
    page.locator('button[type="submit"]').click()
    page.wait_for_timeout(400)
    check("empty form blocked by required attr",
          page.url.endswith("/login") or "/login" in page.url, page.url)

    # ------------------------------------------------- wrong password
    page.fill('input[name="username"]', USER)
    page.fill('input[name="password"]', "wrongpassword")
    page.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")
    check("wrong password rejected", "/login?error=sai" in page.url, page.url)
    check("wrong password shows error",
          "không đúng" in error_banner(page), error_banner(page))
    page.screenshot(path=f"{SHOTS}/login-02-wrong-password.png", full_page=True)

    # ------------------------------------------------- unknown user
    page.fill('input[name="username"]', "NoSuchPlayer")
    page.fill('input[name="password"]', PASSWORD)
    page.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")
    check("unknown user rejected", "/login?error=sai" in page.url, page.url)

    # ------------------------------------------------- non-sha256 hash
    page.fill('input[name="username"]', "NoHash")
    page.fill('input[name="password"]', PASSWORD)
    page.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")
    check("non-sha256 stored hash rejected", "/login?error=sai" in page.url, page.url)

    # ------------------------------------------------- successful login
    page.fill('input[name="username"]', USER)
    page.fill('input[name="password"]', PASSWORD)
    page.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")
    check("valid login redirects to /gacha", "/gacha" in page.url, page.url)
    check("session cookie set",
          any(c["name"] == "jv_session" for c in ctx.cookies()),
          str([c["name"] for c in ctx.cookies()]))
    check("logout control visible", page.locator('form[action="/logout"]').count() == 1
          or "logout" in page.content().lower())
    page.screenshot(path=f"{SHOTS}/login-03-success.png", full_page=True)

    # ------------------------------------------------- session persists
    page.goto(f"{BASE}/gacha", wait_until="networkidle")
    check("session survives reload", "/gacha" in page.url and
          not page.locator('input[name="password"]').count(), page.url)

    # ------------------------------------------------- protected pages
    for path in ("/inventory", "/upgrade", "/vi", "/admin",
                 "/bonus", "/battles"):
        r = page.goto(f"{BASE}{path}", wait_until="networkidle")
        check(f"GET {path} while logged in", r.status == 200, str(r.status))

    # ------------------------------------------------- API auth works
    r = page.goto(f"{BASE}/api/drops", wait_until="networkidle")
    check("GET /api/drops while logged in", r.status == 200, str(r.status))

    # ------------------------------------------------- CSRF still required
    csrf = page.evaluate(
        "() => document.querySelector('input[name=csrf]')?.value || ''"
    )
    api = page.evaluate(
        """async (csrf) => {
            const r = await fetch('/api/case/jelly-starter/open', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({count: 1})
            });
            return r.status;
        }""", csrf
    )
    check("open case without CSRF header rejected", api == 403, str(api))

    # ------------------------------------------------- logout
    page.goto(f"{BASE}/gacha", wait_until="networkidle")
    page.locator('form[action="/logout"] button, form[action="/logout"]').first.click()
    page.wait_for_load_state("networkidle")
    check("logout returns to /gacha", "/gacha" in page.url, page.url)
    # Starlette keeps the cookie alive because the page writes a fresh csrf
    # token; what matters is that the session no longer carries the user.
    cookie = next((c for c in ctx.cookies() if c["name"] == "jv_session"), None)
    check("session cookie no longer carries the user",
          cookie is None or "user" not in decode_session(cookie["value"]),
          str(cookie))
    check("logout shows login button again",
          page.locator('a[href="/login"]').count() >= 1)
    check("logout removes the signout button",
          page.locator("form[action='/logout']").count() == 0)

    # ------------------------------------------------- protected page now blocked
    r = page.goto(f"{BASE}/inventory", wait_until="networkidle")
    check("protected page blocked after logout",
          "/login" in page.url or "text=/gacha" in page.content(), page.url)

    # ------------------------------------------------- rate limiter
    page.goto(f"{BASE}/login", wait_until="networkidle")
    codes = []
    for i in range(10):
        page.fill('input[name="username"]', USER)
        page.fill('input[name="password"]', f"bad{i}")
        page.locator('button[type="submit"]').click()
        page.wait_for_load_state("networkidle")
        codes.append(page.url)
    rate_limited = any("error=rate" in u for u in codes)
    check("rate limiter kicks in after repeated failures", rate_limited,
          str(codes[-3:]))
    page.screenshot(path=f"{SHOTS}/login-04-rate-limit.png", full_page=True)

    real_errors = [e for e in console_errors
                   if "favicon" not in e.lower()
                   and "403" not in e]  # the CSRF check above is meant to 403
    check("no unexpected console errors", not real_errors,
          "; ".join(real_errors[:3]))

    browser.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
if failed:
    print("FAILED:")
    for name, _, detail in failed:
        print(f"  - {name} {detail}")
sys.exit(1 if failed else 0)
