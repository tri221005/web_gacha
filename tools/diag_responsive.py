"""Chẩn đoán responsive: chụp ảnh và tìm phần tràn ngang ở nhiều khung."""
from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8080")
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
os.makedirs(SHOTS, exist_ok=True)

VIEWPORTS = [
    ("320", 320, 720),
    ("390", 390, 844),
    ("768", 768, 1024),
    ("1280", 1280, 800),
    ("1600", 1600, 900),
]
PAGES = [
    ("/gacha", "catalogue"),
    ("/case/jelly-starter", "case"),
    ("/battles", "battles"),
    ("/login", "login"),
]

PROBE = """
() => {
  const vw = document.documentElement.clientWidth;
  const overflow = document.documentElement.scrollWidth - vw;
  const bad = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.right <= vw + 2) continue;
    const s = getComputedStyle(el);
    if (s.position === 'fixed') continue;
    // Ignore anything an ancestor clips — that is a deliberate scroll rail.
    let clipped = false, p = el.parentElement;
    while (p) {
      const ps = getComputedStyle(p);
      if (['hidden','clip','auto','scroll'].includes(ps.overflowX)) { clipped = true; break; }
      p = p.parentElement;
    }
    if (clipped) continue;
    bad.push(`${el.tagName}.${(el.className||'').toString().split(' ')[0]} right=${Math.round(r.right)}`);
  }
  const small = [];
  for (const el of document.querySelectorAll('a, button, input, select')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.height < 32) {
      const s = getComputedStyle(el);
      if (s.visibility === 'hidden' || s.display === 'none') continue;
      // A checkbox is small by nature; its label is the real tap target.
      const label = el.closest('label');
      if (el.tagName === 'INPUT' && el.type === 'checkbox' && label
          && label.getBoundingClientRect().height >= 32) continue;
      small.push(`${el.tagName}.${(el.className||'').toString().split(' ')[0]} ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
  }
  return { overflow, bad: [...new Set(bad)].slice(0, 8), small: [...new Set(small)].slice(0, 8) };
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for vname, w, h in VIEWPORTS:
        ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2)
        page = ctx.new_page()
        print(f"\n=== {vname}px ===")
        for path, name in PAGES:
            page.goto(f"{BASE}{path}", wait_until="networkidle")
            r = page.evaluate(PROBE)
            flag = "OK " if r["overflow"] <= 2 and not r["bad"] and not r["small"] else "BAD"
            print(f"  [{flag}] {name}: overflow={r['overflow']}")
            if r["bad"]:
                print(f"        tràn: {r['bad']}")
            if r["small"]:
                print(f"        nhỏ: {r['small']}")
            if vname in ("320", "390", "1600"):
                page.screenshot(path=f"{SHOTS}/rw-{vname}-{name}.png", full_page=True)
        ctx.close()
    browser.close()
print("\nshot dir:", SHOTS)
