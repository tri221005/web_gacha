"""Kiểm tra tap target trên thiết bị cảm ứng thật (hasTouch + is_mobile)."""
from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8080")
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
os.makedirs(SHOTS, exist_ok=True)

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
  const small = [];
  for (const el of document.querySelectorAll('a, button, input, select')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
      if (r.height < 40) {
        const s = getComputedStyle(el);
        if (s.visibility === 'hidden' || s.display === 'none') continue;
        // A checkbox is small by nature; its label is the real tap target.
        const label = el.closest('label');
        if (el.tagName === 'INPUT' && el.type === 'checkbox' && label) {
          const lr = label.getBoundingClientRect();
          if (lr.height >= 40) continue;
        }
        small.push(`${el.tagName}.${(el.className||'').toString().split(' ')[0] || el.id} ${Math.round(r.width)}x${Math.round(r.height)}`);
      }
  }
  // Elements that reach past the viewport without a clipping ancestor.
  const spill = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.right <= vw + 1) continue;
    const s = getComputedStyle(el);
    if (s.position === 'fixed') continue;
    let clipped = false, p = el.parentElement;
    while (p) {
      const ps = getComputedStyle(p);
      if (['hidden','clip','auto','scroll'].includes(ps.overflowX)) { clipped = true; break; }
      p = p.parentElement;
    }
    if (!clipped) spill.push(`${el.tagName}.${(el.className||'').toString().split(' ')[0]}`);
  }
  return { overflow, small: [...new Set(small)], spill: [...new Set(spill)] };
}
"""

fails = 0
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for label, w, h in (("iphone-se", 375, 667), ("small-320", 320, 720), ("tablet", 768, 1024)):
        ctx = browser.new_context(
            viewport={"width": w, "height": h},
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
        )
        page = ctx.new_page()
        print(f"\n=== {label} ({w}x{h}, touch) ===")
        for path, name in PAGES:
            page.goto(f"{BASE}{path}", wait_until="networkidle")
            r = page.evaluate(PROBE)
            ok = r["overflow"] <= 2 and not r["small"] and not r["spill"]
            if not ok:
                fails += 1
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}: overflow={r['overflow']}")
            if r["small"]:
                print(f"        nhỏ hơn 40px: {r['small']}")
            if r["spill"]:
                print(f"        tràn: {r['spill']}")
            if label in ("small-320", "iphone-se"):
                page.screenshot(path=f"{SHOTS}/touch-{label}-{name}.png", full_page=True)
        ctx.close()
    browser.close()

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILURES'}")
