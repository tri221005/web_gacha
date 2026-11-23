"""Find what actually pushes the document wider than the viewport.

Walks every element and reports the ones whose right edge crosses the
viewport, ignoring anything clipped by an ancestor with overflow hidden
(those do not widen the page).
"""
from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8080")
PAGES = ["/gacha", "/case/jelly-starter", "/battles", "/bonus", "/login", "/admin"]
WIDTHS = [320, 360, 390, 768, 1024, 1440]

FIND = """
() => {
  const cw = document.documentElement.clientWidth;
  const clipped = (el) => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (s.overflowX !== 'visible') return true;
    }
    return false;
  };
  const bad = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.right <= cw + 1) continue;
    if (clipped(el)) continue;
    bad.push({
      sel: `${el.tagName}${el.id ? '#' + el.id : ''}${el.className ? '.' + String(el.className).split(' ').filter(Boolean).join('.') : ''}`.slice(0, 80),
      right: Math.round(r.right),
      width: Math.round(r.width),
      depth: (() => { let d = 0, n = el; while ((n = n.parentElement)) d++; return d; })(),
    });
  }
  bad.sort((a, b) => b.depth - a.depth || b.right - a.right);
  return bad.slice(0, 10);
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for w in WIDTHS:
        ctx = browser.new_context(viewport={"width": w, "height": 800})
        page = ctx.new_page()
        for path in PAGES:
            page.goto(f"{BASE}{path}", wait_until="networkidle")
            over = page.evaluate(
                "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            bad = page.evaluate(FIND)
            if over > 1 or bad:
                print(f"\n[{w}px] {path}  overflow={over}")
                for b in bad:
                    print(f"    {b['sel']}  right={b['right']} w={b['width']}")
        ctx.close()
    browser.close()
print("\ndone")
