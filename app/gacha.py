from __future__ import annotations

import json
import logging
import random
import re
import shutil
from dataclasses import dataclass, field

from .config import GACHA_FILE, STATIC_DIR, dry_run

IMAGE_EXTS = (".png", ".webp", ".jpg", ".jpeg", ".svg")

RARITY_COLORS = {
    "consumer": "#b0c3d9",
    "industrial": "#5e98d9",
    "milspec": "#4b69ff",
    "restricted": "#8847ff",
    "classified": "#d32ce6",
    "covert": "#eb4b4b",
    "extraordinary": "#e4ae39",
    "common": "#b0c3d9",
    "uncommon": "#4b69ff",
    "rare": "#8847ff",
    "epic": "#d32ce6",
    "legendary": "#e4ae39",
}


def rarity_color(rarity: str) -> str:
    return RARITY_COLORS.get(rarity, "#b0c3d9")


def resolve_image(folder: str, item_id: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    for ext in IMAGE_EXTS:
        path = STATIC_DIR / folder / f"{item_id}{ext}"
        if path.exists():
            return f"/static/{folder}/{item_id}{ext}"
    return f"/static/{folder}/_placeholder.svg"


@dataclass
class Item:
    id: str
    name: str
    rarity: str
    weight: float
    coin: int
    image: str = ""
    color: str = ""

    def as_public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "rarity": self.rarity,
            "weight": self.weight,
            "coin": self.coin,
            "image": self.image,
            "color": self.color or rarity_color(self.rarity),
        }


@dataclass
class Case:
    id: str
    name: str
    description: str
    pull_cost: int
    image: str
    items: list[Item] = field(default_factory=list)
    glow: str = "#e4ae39"


def load_config() -> dict:
    """Read the shop config.

    The file is read on every request so an admin edit takes effect
    straight away. The parsed result is cached against the file's mtime,
    so a request that does not change the file does not re-parse it.

    A missing or broken file gives an empty shop instead of a crash. The
    site has to come up even when the config file was never copied or
    was cut short by a bad write.
    """
    global _config_cache
    try:
        stamp = GACHA_FILE.stat().st_mtime
    except OSError:
        stamp = 0.0
    if _config_cache is not None and _config_cache[0] == stamp:
        return _config_cache[1]
    try:
        data = json.loads(GACHA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logging.getLogger(__name__).warning(
            "Doc file cau hinh shop that bai (%s).", GACHA_FILE
        )
        data = {"cases": []}
    if not isinstance(data, dict):
        data = {"cases": []}
    _config_cache = (stamp, data)
    return data


_config_cache: tuple[float, dict] | None = None


def save_config(data: dict) -> None:
    """Write `gacha.json` atomically.

    The file is rewritten through a temporary file and then moved into
    place, so a crash halfway through cannot leave the shop with no cases
    at all. A timestamped backup of the previous file is kept.
    """
    backup = GACHA_FILE.with_suffix(".json.bak")
    if GACHA_FILE.exists():
        shutil.copy2(GACHA_FILE, backup)
    # The file can live on a mounted volume whose folder does not exist
    # yet on the first run.
    GACHA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = GACHA_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(GACHA_FILE)
    global _config_cache
    _config_cache = None


def case_rtp(case: Case) -> float:
    """Expected payout per pull, as a share of the pull cost.

    This is the theoretical RTP of the loot table, not what the server
    actually paid out; the admin console shows both side by side.
    """
    cost = case.pull_cost
    if cost <= 0:
        return 0.0
    weights = [max(0, item.weight) for item in case.items]
    total = sum(weights)
    if total <= 0:
        return 0.0
    expected = sum(item.coin * w
                   for item, w in zip(case.items, weights, strict=True)) / total
    return expected / cost


def case_view_full(case: Case) -> dict:
    """Everything the admin needs to edit a case."""
    total = sum(max(0, item.weight) for item in case.items) or 1
    rtp = round(case_rtp(case) * 100, 2)
    return {
        "id": case.id,
        "name": case.name,
        "description": case.description,
        "pull_cost": case.pull_cost,
        "image": case.image,
        "rtp": rtp,
        # An RTP over 100 means the case pays out more than it costs, so
        # the house loses money on every pull. The admin console flags it.
        "rtp_over": rtp > 100,
        "items": [
            {
                **item.as_public(),
                "percent": round(100 * max(0, item.weight) / total, 3),
                "coin_fmt": f"{item.coin:,}".replace(",", "."),
            }
            for item in case.items
        ],
    }


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")


def _clean_case(raw: dict) -> dict:
    """Normalise one case for storage, refusing unusable values.

    A case with no items, a zero cost or a bad id would break the shop for
    every player, so the edit is rejected instead of saved.
    """
    case_id = str(raw.get("id", "")).strip()
    if not SLUG_RE.fullmatch(case_id):
        raise ValueError("ID rương phải là chữ thường, số và dấu gạch ngang.")
    cost = int(raw.get("pull_cost", 0))
    if cost <= 0:
        raise ValueError("Giá mở rương phải lớn hơn 0.")
    items = []
    for entry in raw.get("items") or []:
        item_id = str(entry.get("id", "")).strip()
        name = str(entry.get("name", "")).strip()
        if not item_id or not name:
            raise ValueError("Mỗi món cần có ID và tên.")
        weight = float(entry.get("weight", 0))
        if weight < 0:
            raise ValueError("Trọng số không được âm.")
        coin = int(entry.get("coin", 0))
        if coin < 0:
            raise ValueError("Giá trị món không được âm.")
        item = {
            "id": item_id,
            "name": name,
            "rarity": str(entry.get("rarity", "consumer")),
            "weight": weight,
            "coin": coin,
        }
        if entry.get("image"):
            item["image"] = str(entry["image"])
        items.append(item)
    if not items:
        raise ValueError("Rương phải có ít nhất một món.")
    if sum(item["weight"] for item in items) <= 0:
        raise ValueError("Tổng trọng số phải lớn hơn 0.")
    clean = {
        "id": case_id,
        "name": str(raw.get("name", case_id)).strip() or case_id,
        "description": str(raw.get("description", "")),
        "pull_cost": cost,
        "items": items,
    }
    # An RTP over 100 means the case pays out more than it costs, so the
    # house loses money on every pull. The admin is allowed to do it on
    # purpose, but it has to be a deliberate choice.
    if _case_rtp_of(clean) > 1.0:
        clean["rtp_over"] = True
    return clean


def _case_rtp_of(case: dict) -> float:
    """The RTP of a plain case dict, the shape the config file stores."""
    cost = int(case.get("pull_cost", 0) or 0)
    if cost <= 0:
        return 0.0
    items = case.get("items") or []
    weights = [max(0, float(i.get("weight", 0) or 0)) for i in items]
    total = sum(weights)
    if total <= 0:
        return 0.0
    expected = sum(int(i.get("coin", 0) or 0) * w
                   for i, w in zip(items, weights, strict=True)) / total
    return expected / cost


def upsert_case(data: dict, case: dict) -> dict:
    """Insert or replace a case in the shop config and save it."""
    clean = _clean_case(case)
    cases = list(data.get("cases") or [])
    for index, existing in enumerate(cases):
        if existing.get("id") == clean["id"]:
            cases[index] = clean
            break
    else:
        cases.append(clean)
    data["cases"] = cases
    save_config(data)
    return clean


def delete_case(data: dict, case_id: str) -> None:
    cases = [c for c in (data.get("cases") or []) if c.get("id") != case_id]
    data["cases"] = cases
    save_config(data)


def _parse_item(raw: dict) -> Item:
    item_id = raw["id"]
    rarity = raw.get("rarity", "consumer")
    return Item(
        id=item_id,
        name=raw["name"],
        rarity=rarity,
        weight=float(raw.get("weight", 1)),
        coin=int(raw.get("coin", 0)),
        image=resolve_image("items", item_id, raw.get("image")),
        color=rarity_color(rarity),
    )


def load_cases() -> list[Case]:
    cases = []
    for raw in load_config().get("cases", []):
        items = [_parse_item(item) for item in raw.get("items", [])]
        glow = rarity_color(items[-1].rarity) if items else "#e4ae39"
        case_id = raw["id"]
        cases.append(
            Case(
                id=case_id,
                name=raw["name"],
                description=raw.get("description", ""),
                pull_cost=int(raw.get("pull_cost", 0)),
                image=resolve_image("cases", case_id, raw.get("image")),
                items=items,
                glow=glow,
            )
        )
    return cases


def get_case(case_id: str) -> Case | None:
    for item in load_cases():
        if item.id == case_id:
            return item
    return None


def roll(case: Case) -> Item:
    weights = [max(0, item.weight) for item in case.items]
    if not case.items:
        raise ValueError("empty case")
    if sum(weights) <= 0:
        return case.items[0]
    return random.choices(case.items, weights=weights, k=1)[0]


def pull_cost() -> int:
    cases = load_cases()
    return cases[0].pull_cost if cases else 0


CONSOLE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


def console_safe(player: str) -> bool:
    """True when the name can be put into a console command safely.

    The console splits commands on spaces and `;`, so a name with either
    would turn into extra commands. `eco take Alice; op Bob 100` would run
    `op Bob` as a second command.
    """
    return bool(CONSOLE_NAME_RE.fullmatch(player))


def take_command(player: str, amount: int) -> str:
    if not console_safe(player):
        raise ValueError(f"Ten nguoi choi khong hop le: {player!r}")
    template = load_config().get("take_command", "eco take {player} {amount}")
    return template.format(player=player, amount=amount)


def give_command(player: str, amount: int) -> str:
    if not console_safe(player):
        raise ValueError(f"Ten nguoi choi khong hop le: {player!r}")
    template = load_config().get("give_command", "eco give {player} {amount}")
    return template.format(player=player, amount=amount)


def is_dry_run() -> bool:
    return dry_run()


def market_listings() -> list[Item]:
    seen: set[tuple[str, int]] = set()
    listings: list[Item] = []
    for case in load_cases():
        for item in case.items:
            key = (item.id, item.coin)
            if key in seen:
                continue
            seen.add(key)
            listings.append(item)
    listings.sort(key=lambda item: item.coin)
    return listings
