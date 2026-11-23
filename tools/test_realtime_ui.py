"""Check that the live updates actually happen.

The page has to update itself without a reload: the Coin balance in the
header, the battle lobby and the bag. This opens the page, changes the
data behind its back and checks the page noticed.

Run:  python tools/test_realtime_ui.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright  # noqa: E402

from app import game, store  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8080")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
os.makedirs(OUT, exist_ok=True)

PLAYER = "hhh21"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> None:
    store.init()
    cookie = mint({"user": PLAYER, "login_name": PLAYER, "csrf": "x"})

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{
            "name": "jv_session", "value": cookie, "domain": "127.0.0.1", "path": "/",
        }])
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        print("\n== The Coin balance in the header ==")
        page.goto(f"{BASE}/gacha", wait_until="networkidle")
        page.wait_for_timeout(1500)
        chip = page.locator(".coin-chip span").first
        before = chip.text_content().strip()
        check("the header shows a balance", bool(before) and "Coin" in before, before)

        # Change the balance behind the page's back.
        store.credit(PLAYER, 4321, "admin", "realtime test")
        page.wait_for_timeout(11000)
        after = chip.text_content().strip()
        check("the header balance follows the server", after != before,
              f"{before} -> {after}")

        print("\n== The battle lobby ==")
        page.goto(f"{BASE}/battles", wait_until="networkidle")
        page.wait_for_timeout(1500)
        before_cards = page.locator("#lobby-open .battle-card").count()

        bot = store.BOT_NAMES[0]
        game.seed_wallet(bot, is_bot=True)
        game.create_battle(bot, "jelly-starter", slots=2, rounds=1,
                           mode="STANDARD", is_bot=True)
        page.wait_for_timeout(7000)
        after_cards = page.locator("#lobby-open .battle-card").count()
        check("a new room shows up on its own", after_cards > before_cards,
              f"{before_cards} -> {after_cards} cards")
        page.screenshot(path=f"{OUT}/realtime-lobby.png", full_page=True)

        print("\n== The bag ==")
        page.goto(f"{BASE}/inventory", wait_until="networkidle")
        page.wait_for_timeout(1500)
        before_items = page.locator("#bag .item-card").count()

        # Put an item into the bag behind the page's back.
        from app.gacha import get_case
        case = get_case("jelly-starter")
        store.add_inventory(PLAYER, case.items[0], "case", "jelly-starter")
        page.wait_for_timeout(9000)
        after_items = page.locator("#bag .item-card").count()
        check("a new item shows up on its own", after_items > before_items,
              f"{before_items} -> {after_items} items")
        page.screenshot(path=f"{OUT}/realtime-bag.png", full_page=True)

        print("\n== The console ==")
        real_errors = [e for e in errors if "favicon" not in e.lower()]
        check("no console errors", not real_errors, "; ".join(real_errors[:3]))

        browser.close()

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name in failed:
            print(f"  - {name}")


main()
