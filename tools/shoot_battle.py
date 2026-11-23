"""Screenshot the battle page as a logged-in player.

The battle page shows the price a player has to pay to sit down. In a
room a bot hosts, that price includes the bot seat, so the screenshot is
how that gets checked.

Run:  python tools/shoot_battle.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright  # noqa: E402

from app import game, store  # noqa: E402
from tools.mint_cookie import mint  # noqa: E402

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8082")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
os.makedirs(OUT, exist_ok=True)

PLAYER = "hhh21"


def make_room(host: str) -> int:
    bot = store.BOT_NAMES[0]
    game.seed_wallet(bot, is_bot=True)
    battle = game.create_battle(bot, "jelly-starter", slots=3, rounds=1,
                                 mode="STANDARD", is_bot=True)
    return battle["id"]


def main() -> None:
    store.init()
    bot_room = make_room("bot")
    real_room = game.create_battle(PLAYER, "jelly-starter", slots=3, rounds=1,
                                   mode="STANDARD")["id"]
    cookie = mint({"user": PLAYER, "login_name": PLAYER, "csrf": "x"})

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_cookies([{
            "name": "jv_session", "value": cookie, "domain": "127.0.0.1",
            "path": "/",
        }])
        page = ctx.new_page()
        for battle_id, label in ((bot_room, "bot-room"),
                                  (real_room, "real-room")):
            page.goto(f"{BASE}/battles/{battle_id}", wait_until="networkidle")
            page.wait_for_timeout(600)
            page.screenshot(path=f"{OUT}/battle-{label}.png", full_page=True)
            print(f"  {label} -> {OUT}/battle-{label}.png")
        browser.close()


main()
