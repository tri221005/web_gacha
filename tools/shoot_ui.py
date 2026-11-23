"""Capture full-page screenshots at several widths for a visual review."""
from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8080")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots", "ui")
os.makedirs(OUT, exist_ok=True)

PAGES = [
    ("/gacha", "catalogue"),
    ("/case/jelly-starter", "case"),
    ("/battles", "battles"),
    ("/bonus", "bonus"),
    ("/login", "login"),
]

WIDTHS = [("phone", 390, 844), ("small", 320, 700), ("tablet", 768, 1024), ("desktop", 1440, 900)]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for label, w, h in WIDTHS:
        ctx = browser.new_context(viewport={"width": w, "height": h})
        page = ctx.new_page()
        for path, name in PAGES:
            page.goto(f"{BASE}{path}", wait_until="networkidle")
            page.screenshot(path=f"{OUT}/{label}-{name}.png", full_page=True)
            over = page.evaluate(
                "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            wide = page.evaluate(
                """() => {
                    const cw = document.documentElement.clientWidth;
                    const bad = [];
                    for (const el of document.querySelectorAll('*')) {
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) continue;
                        if (r.right > cw + 1) {
                            bad.push(`${el.tagName}.${el.className || ''}`.slice(0, 70)
                                     + ` right=${Math.round(r.right)} w=${Math.round(r.width)}`);
                        }
                    }
                    return bad.slice(0, 8);
                }"""
            )
            print(f"{label:8} {name:10} overflow={over:4}  wide={wide}")
        ctx.close()
    browser.close()
