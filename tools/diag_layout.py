"""Đo layout bằng số liệu: số cột lưới, kích thước, khoảng cách."""
from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8080")

PROBE = """
() => {
  const cols = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const t = getComputedStyle(el).gridTemplateColumns;
    return t ? t.split(' ').length : null;
  };
  const box = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height) };
  };
  const nav = document.querySelector('.site-header nav');
  const navStyle = nav ? getComputedStyle(nav) : null;
  return {
    vw: document.documentElement.clientWidth,
    page: box('.page'),
    heroInner: box('.hero-inner'),
    heroStats: box('.hero-stats'),
    cols: {
      caseGrid: cols('.case-grid'),
      statsBar: cols('.stats-bar'),
      promoRow: cols('.promo-row'),
      contents: cols('.contents'),
    },
    nav: nav ? {
      scrollW: nav.scrollWidth, clientW: nav.clientWidth,
      scrollable: nav.scrollWidth > nav.clientWidth + 1,
      overflowX: navStyle.overflowX,
      links: nav.querySelectorAll('.nav-link').length,
      linkH: Math.round(nav.querySelector('.nav-link').getBoundingClientRect().height),
    } : null,
    caseCard: box('.case-card'),
    reel: box('.reel'),
    tile: box('.tile'),
    gap: (() => {
      const g = document.querySelector('.case-grid');
      return g ? getComputedStyle(g).gap : null;
    })(),
    pagePad: (() => {
      const p = document.querySelector('.page');
      return p ? getComputedStyle(p).paddingLeft : null;
    })(),
  };
}
"""

PAGES = [("/gacha", "catalogue"), ("/case/jelly-starter", "case"), ("/battles", "battles")]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for w in (320, 390, 768, 1280, 1600):
        ctx = browser.new_context(viewport={"width": w, "height": 800},
                                  is_mobile=(w < 700), has_touch=(w < 700))
        page = ctx.new_page()
        print(f"\n=== {w}px ===")
        for path, name in PAGES:
            page.goto(f"{BASE}{path}", wait_until="networkidle")
            r = page.evaluate(PROBE)
            print(f"  {name}: vw={r['vw']} page={r['page']} pad={r['pagePad']} gap={r['gap']}")
            print(f"    cols: case={r['cols']['caseGrid']} stats={r['cols']['statsBar']} "
                  f"promo={r['cols']['promoRow']} contents={r['cols']['contents']}")
            if r["nav"]:
                n = r["nav"]
                print(f"    nav: {n['links']} links, h={n['linkH']}px, "
                      f"scrollable={n['scrollable']} ({n['scrollW']}>{n['clientW']})")
            if r["caseCard"]:
                print(f"    caseCard={r['caseCard']} reel={r['reel']}")
        ctx.close()
    browser.close()
