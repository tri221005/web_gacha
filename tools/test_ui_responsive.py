"""Playwright checks that the pages hold up on a phone and for a keyboard user.

Covers: mobile layout, tap target sizes, visible focus, and the reduced
motion setting.
"""
from __future__ import annotations

import os
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8099")
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
os.makedirs(SHOTS, exist_ok=True)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


PAGES = [
    ("/gacha", "catalogue"),
    ("/case/jelly-starter", "case"),
    ("/battles", "battles"),
    ("/bonus", "bonus"),
    ("/login", "login"),
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    # --- phone ---
    phone = browser.new_context(viewport={"width": 390, "height": 844},
                                device_scale_factor=2)
    page = phone.new_page()
    for path, name in PAGES:
        page.goto(f"{BASE}{path}", wait_until="networkidle")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth"
        )
        check(f"{name} has no sideways scroll on a phone",
              overflow <= 2, f"overflow={overflow}px")
        if name == "case":
            page.screenshot(path=f"{SHOTS}/mobile-{name}.png", full_page=True)
    phone.close()

    # --- tap targets ---
    phone2 = browser.new_context(viewport={"width": 390, "height": 844})
    page = phone2.new_page()
    page.goto(f"{BASE}/gacha", wait_until="networkidle")
    small = page.evaluate(
        """() => {
            const bad = [];
            for (const el of document.querySelectorAll('a, button')) {
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                if (r.height < 32 || r.width < 32) {
                    bad.push(`${el.tagName}.${el.className} ${Math.round(r.width)}x${Math.round(r.height)}`);
                }
            }
            return bad;
        }"""
    )
    check("tap targets are at least 32px on a phone",
          len(small) <= 3, f"{len(small)} small: {small[:4]}")
    phone2.close()

    # --- keyboard focus ---
    desktop = browser.new_context(viewport={"width": 1280, "height": 800})
    page = desktop.new_page()
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    focused = page.evaluate(
        """() => {
            const el = document.activeElement;
            if (!el || el === document.body) return null;
            const s = getComputedStyle(el);
            return {tag: el.tagName, outline: s.outlineStyle,
                    width: s.outlineWidth, shadow: s.boxShadow};
        }"""
    )
    check("the keyboard focus is visible",
          focused is not None
          and (focused["outline"] != "none" or focused["shadow"] != "none"),
          str(focused))
    page.screenshot(path=f"{SHOTS}/focus-login.png")
    desktop.close()

    # --- reduced motion ---
    rm = browser.new_context(viewport={"width": 1280, "height": 800},
                             reduced_motion="reduce")
    page = rm.new_page()
    page.goto(f"{BASE}/gacha", wait_until="networkidle")
    anim = page.evaluate(
        """() => {
            let long = 0;
            for (const el of document.querySelectorAll('*')) {
                const s = getComputedStyle(el);
                for (const name of ['animationDuration', 'transitionDuration']) {
                    const v = s[name];
                    if (v && v !== '0s') {
                        const sec = parseFloat(v) * (v.endsWith('ms') ? 0.001 : 1);
                        if (sec > 0.35) long++;
                    }
                }
            }
            return long;
        }"""
    )
    check("no long animation runs under reduced motion",
          anim == 0, f"{anim} elements animate for more than 0.35s")
    rm.close()

    browser.close()

failed = [(n, d) for n, ok, d in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
if failed:
    for name, detail in failed:
        print(f"  - {name}  {detail}")
sys.exit(1 if failed else 0)
