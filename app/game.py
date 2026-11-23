from __future__ import annotations

import random
from dataclasses import dataclass

from . import store
from .gacha import (
    get_case,
    is_dry_run,
    load_cases,
    market_listings,
    roll,
)

UPGRADE_RTP = 0.9
UPGRADE_MIN_CHANCE = 0.005
UPGRADE_MAX_CHANCE = 0.85
UPGRADE_MIN_MULTIPLIER = 1.05
DRY_SEED = 250_000
BONUS_SLICES = (
    (500, 28),
    (1500, 24),
    (3000, 18),
    (5000, 14),
    (10000, 10),
    (25000, 5),
    (50000, 1),
)


class GameError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class OpenResult:
    winner: dict
    pool: list[dict]
    inventory_id: int
    balance: int
    dry_run: bool


@dataclass
class OpenBatchResult:
    openings: list[dict]
    pool: list[dict]
    total_cost: int
    balance: int
    dry_run: bool


def seed_wallet(player: str, pika_coin: float = 0, is_bot: bool = False) -> int:
    """Create the wallet if it is missing.

    In dry-run the wallet gets a fixed float so the game can be tested
    without touching the server. In live mode a real player is seeded with
    their actual PikaMC balance so the web wallet starts in sync.
    """
    if is_bot:
        seed = max(DRY_SEED, 1_000_000)
    elif is_dry_run():
        seed = DRY_SEED
    else:
        seed = max(0, int(pika_coin))
    return store.ensure_wallet(player, seed=seed, is_bot=is_bot)


def sync_wallet(player: str, pika_coin: float, kind: str = "sync") -> int:
    """Force the local wallet to the live PikaMC balance.

    The transaction kind names what caused the change, so the wallet history
    reads "Mở rương" or "Bán đồ" instead of a generic sync entry.
    """
    note = "đồng bộ PikaMC" if kind == "sync" else "PikaMC"
    return store.set_balance(player, int(pika_coin), kind, note)


def balance(player: str) -> int:
    return store.get_balance(player)


def open_case_batch(player: str, slug: str, count: int = 1,
                    is_bot: bool = False, charge: bool = True) -> OpenBatchResult:
    if count not in (1, 2, 3, 4, 5):
        raise GameError("Số lượng mở không hợp lệ (1-5).")
    case = get_case(slug)
    if not case:
        raise GameError("Không có rương này.", 404)
    total_cost = case.pull_cost * count
    pool = [item.as_public() for item in case.items]
    # The prizes are rolled first, then the charge and the payout happen
    # in one transaction. Rolling first is safe: nothing is written until
    # the transaction runs, and the rollback undoes the whole thing if
    # the player cannot pay.
    rolled = [roll(case) for _ in range(count)]
    if charge:
        try:
            inv_ids = store.open_case_atomic(
                player, total_cost, [prize.as_public() for prize in rolled],
                case.id, pull_cost=case.pull_cost, is_bot=is_bot,
                dry=is_dry_run(),
            )
        except ValueError as exc:
            raise GameError(f"Không đủ Coin. Cần {total_cost:,} Coin.") from exc
    else:
        # The server already took the Coin, so only the items are written.
        inv_ids = []
        for prize in rolled:
            inv_id = store.add_inventory(player, prize, "case", case.id)
            store.record_drop(player, prize, case.id, is_bot=is_bot)
            store.record_pull(player, case.pull_cost, prize, case_id=case.id,
                              dry=is_dry_run())
            inv_ids.append(inv_id)
    openings = []
    for prize, inv_id in zip(rolled, inv_ids, strict=True):
        openings.append({
            "winner": prize.as_public(),
            "inventory_id": inv_id,
            "winner_coin": prize.coin,
        })
    return OpenBatchResult(
        openings=openings,
        pool=pool,
        total_cost=total_cost,
        balance=store.get_balance(player),
        dry_run=is_dry_run(),
    )


def open_case(player: str, slug: str, is_bot: bool = False) -> OpenResult:
    res = open_case_batch(player, slug, count=1, is_bot=is_bot)
    first = res.openings[0]
    return OpenResult(
        winner=first["winner"],
        pool=res.pool,
        inventory_id=first["inventory_id"],
        balance=res.balance,
        dry_run=res.dry_run,
    )


def sell_items(player: str, item_pks: list[int], commit: bool = True) -> dict:
    """Sell items into Coin.

    With `commit=False` the items are only marked as pending and no Coin is
    credited yet. That lets the caller pay out on the Minecraft server first
    and only commit locally once the server accepted it.

    Only items that are still `held` can be sold. The claim happens in one
    transaction, so two requests selling the same item at the same time
    cannot both succeed.
    """
    if not item_pks:
        raise GameError("Chưa chọn món nào.")
    for pk in item_pks:
        row = store.get_inventory_item(pk)
        if not row or row["player"] != player:
            raise GameError("Không phải đồ của bạn.")
        if row["status"] != "held":
            raise GameError(f"{row['name']} không còn trong túi.")
    if commit:
        # The claim, the sold mark and the payout move together, so the
        # player can never lose the items without getting the Coin.
        result = store.sell_items_atomic(player, item_pks)
        if result is None:
            raise GameError("Món đã được bán, hãy tải lại trang.")
        return result
    try:
        claimed = store.claim_inventory(item_pks, player)
    except ValueError as exc:
        raise GameError("Món đã được bán, hãy tải lại trang.") from exc
    if len(claimed) != len(item_pks):
        raise GameError("Món đã được bán, hãy tải lại trang.")
    total = sum(int(row["value"]) for row in claimed)
    return {
        "sold": len(item_pks),
        "amount": total,
        "balance": store.get_balance(player),
        "items": claimed,
    }


def commit_sale(player: str, item_pks: list[int], amount: int) -> int:
    """Finalise a pending sale: the items become sold.

    The Coin was already paid out on the Minecraft server and the wallet
    balance already mirrors the server, so nothing is credited here.
    """
    store.set_inventory_status(item_pks, "sold")
    return store.get_balance(player)


def revert_sale(item_pks: list[int]) -> None:
    """Undo a pending sale when the server refused the payout.

    Only items still in `selling` go back to `held`; an item that was
    already finalised stays `sold`.
    """
    store.set_inventory_status(item_pks, "held", only_from="selling")


def sell_all(player: str, commit: bool = True) -> dict:
    held = store.list_inventory(player, "held")
    return sell_items(player, [row["id"] for row in held], commit=commit)


def upgrade_odds(source: int, target: int) -> dict:
    if source <= 0 or target <= 0:
        return {"ok": False, "reason": "Giá không hợp lệ."}
    multiplier = target / source
    if multiplier < UPGRADE_MIN_MULTIPLIER:
        return {"ok": False, "reason": "Món đích phải đắt hơn ít nhất 5%."}
    raw = (source / target) * UPGRADE_RTP
    if raw < UPGRADE_MIN_CHANCE:
        return {"ok": False, "reason": "Khoảng giá quá xa, tỉ lệ dưới 0.5%."}
    chance = min(UPGRADE_MAX_CHANCE, raw)
    return {"ok": True, "chance": chance, "multiplier": multiplier}


def upgrade_targets(stake_value: int) -> list[dict]:
    low = int(stake_value * UPGRADE_MIN_MULTIPLIER)
    high = int((stake_value * UPGRADE_RTP) / UPGRADE_MIN_CHANCE)
    out = []
    for item in market_listings():
        if low <= item.coin <= high:
            odds = upgrade_odds(stake_value, item.coin)
            if odds["ok"]:
                public = item.as_public()
                public["chance"] = round(odds["chance"] * 100, 2)
                public["multiplier"] = round(odds["multiplier"], 2)
                out.append(public)
    return out


def do_upgrade(player: str, inventory_id: int, target_id: str, target_coin: int) -> dict:
    # The stake is claimed first, with a conditional UPDATE, so two
    # requests cannot upgrade the same item at the same time.
    try:
        stake = store.claim_upgrade_stake(inventory_id, player)
    except ValueError as exc:
        raise GameError("Món này không còn trong túi.") from exc
    if not stake:
        raise GameError("Không dùng được món này.")
    try:
        target = None
        for item in market_listings():
            if item.id == target_id and item.coin == target_coin:
                target = item
                break
        if not target:
            raise GameError("Không có món đích này.")
        odds = upgrade_odds(int(stake["value"]), target.coin)
        if not odds["ok"]:
            raise GameError(odds["reason"])
        roll_v = random.random()
        won = roll_v < odds["chance"]
        reward_id = None
        if won:
            reward_id = store.add_inventory(player, target, "upgrade")
            store.record_drop(player, target, "upgrade", is_bot=False)
        store.set_inventory_status([inventory_id], "upgraded")
        store.record_upgrade(player, {"name": stake["name"], "coin": stake["value"]}, target.as_public(), odds["chance"], roll_v, won)
    except Exception:
        # The upgrade did not happen, so the stake must go back into the
        # bag instead of vanishing.
        store.release_upgrade_stake(inventory_id)
        raise
    return {
        "won": won,
        "chance": round(odds["chance"] * 100, 2),
        "roll": round(roll_v * 100, 2),
        "stake": stake,
        "target": target.as_public(),
        "reward_id": reward_id,
        "balance": store.get_balance(player),
    }


def battle_price(slug: str, rounds: int) -> int:
    case = get_case(slug)
    if not case:
        raise GameError("Không có rương này.", 404)
    if rounds < 1 or rounds > 5:
        raise GameError("Số vòng 1–5.")
    return case.pull_cost * rounds


def create_battle(player: str, slug: str, slots: int, rounds: int, mode: str, is_bot: bool = False) -> dict:
    if slots not in (2, 3, 4):
        raise GameError("Số chỗ 2, 3 hoặc 4.")
    mode = mode if mode in ("STANDARD", "CRAZY") else "STANDARD"
    paid = battle_price(slug, rounds)
    if store.get_balance(player) < paid:
        raise GameError("Không đủ Coin.")
    store.debit(player, paid, "battle_pay", slug)
    battle_id = store.create_battle(player, slug, rounds, slots, mode, paid, is_bot)
    return store.get_battle(battle_id)


def cancel_battle(battle_id: int, player: str, paid: int,
                  refunded: int | None = None) -> None:
    """Undo a battle the server never charged for.

    The seat is removed and the Coin is returned to the local ledger, so a
    failed payment does not leave a phantom battle or a phantom debit.

    `refunded` is how much was actually taken from the local ledger. It
    defaults to `paid`, but the two are not always the same: the host
    pays the server for its own seat *and* for every bot it calls, while
    the ledger only ever holds the host's own seat. Refunding `paid`
    would hand the host the price of the bots for free, so the caller
    passes what the ledger really lost.
    """
    battle = store.get_battle(battle_id)
    if not battle:
        return
    store.delete_battle(battle_id)
    amount = paid if refunded is None else refunded
    if amount > 0:
        store.credit(player, amount, "refund", "battle chưa thanh toán")


def leave_battle(battle_id: int, player: str, paid: int) -> None:
    """Give a battle seat back when the server refused the payment."""
    if store.leave_battle(battle_id, player) and paid > 0:
        store.credit(player, paid, "refund", "join thất bại")


def join_existing_battle(player: str, battle_id: int, is_bot: bool = False) -> dict:
    battle = store.get_battle(battle_id)
    if not battle:
        raise GameError("Không có trận này.", 404)
    if battle["status"] != "WAITING":
        raise GameError("Trận đã bắt đầu.")
    paid = battle_price(battle["case_id"], int(battle["rounds"]))
    if store.get_balance(player) < paid:
        raise GameError("Không đủ Coin.")
    store.debit(player, paid, "battle_pay", battle["case_id"])
    try:
        store.join_battle(battle_id, player, is_bot, paid)
    except ValueError as exc:
        store.credit(player, paid, "refund", "join thất bại")
        raise GameError(str(exc)) from exc
    return store.get_battle(battle_id)


def fill_bots(battle_id: int) -> dict:
    battle = store.get_battle(battle_id)
    if not battle:
        raise GameError("Không có trận này.", 404)
    if battle["status"] != "WAITING":
        return battle
    seated = {row["player"] for row in battle["players"]}
    paid = battle_price(battle["case_id"], int(battle["rounds"]))
    for name in store.BOT_NAMES:
        if len(seated) >= battle["slots"]:
            break
        if name in seated:
            continue
        seed_wallet(name, is_bot=True)
        if store.get_balance(name) < paid:
            store.credit(name, paid * 4, "seed", "bot nạp")
        store.debit(name, paid, "battle_pay", battle["case_id"])
        try:
            store.join_battle(battle_id, name, True, paid)
        except ValueError:
            store.credit(name, paid, "refund", "ghế đầy")
            break
        seated.add(name)
    return store.get_battle(battle_id)


def bot_seat_count(battle: dict, host: str) -> int:
    """How many bot seats were added to a battle.

    A bot seat costs the server nothing, but it can still win items that
    the host sells for real money. The host therefore pays for the bots it
    calls, and this is how many extra seats have to be charged.
    """
    players = battle.get("players") or []
    return sum(1 for row in players
               if row["player"] != host and row.get("is_bot"))


def unpaid_bot_seats(battle: dict, winner: str) -> int:
    """What the winner still owes for the bot seats in this battle.

    A bot seat is paid for by the host who called the bot, and the host
    pays the server for it on top of their own seat. When the *bot* is
    the host, nobody paid for the bot seat: the bot paid from its own
    fake local wallet, which the Minecraft server never saw.

    So when a real player wins a room that a bot hosts, the bot seat's
    price was never really paid. The winner takes the bot's drops as
    well, so the winner pays for that seat now. Without this, joining a
    bot's room is free money whenever the case pays out more than it
    costs.
    """
    players = battle.get("players") or []
    owed = 0
    for row in players:
        if row["player"] == winner:
            continue
        if not row.get("is_bot"):
            continue
        # A real host paid the server for the bot seat already.
        if battle["host"] != row["player"]:
            continue
        owed += int(row.get("paid") or 0)
    return owed


def remove_bots(battle_id: int, count: int) -> None:
    """Take bot seats back out of a battle.

    Used when the server refused the payment for the bots: the seats must
    not stay in the lobby for free.
    """
    battle = store.get_battle(battle_id)
    if not battle or count <= 0:
        return
    bots = [row["player"] for row in (battle.get("players") or [])
            if row["player"] != battle["host"] and row.get("is_bot")]
    for name in bots[-count:]:
        store.leave_battle(battle_id, name)


def start_battle(battle_id: int, player: str | None = None) -> dict:
    battle = store.get_battle(battle_id)
    if not battle:
        raise GameError("Không có trận này.", 404)
    if battle["status"] not in ("WAITING", "RUNNING"):
        raise GameError("Trận đã bắt đầu hoặc đã xong.")
    if len(battle["players"]) < 2:
        raise GameError("Cần ít nhất 2 người mới bắt đầu.")
    if player is not None and battle["host"] != player:
        raise GameError("Chỉ chủ phòng mới bấm Bắt đầu.")
    return settle_battle(battle_id)


def settle_battle(battle_id: int) -> dict:
    battle = store.get_battle(battle_id)
    if not battle:
        raise GameError("Trận này không tồn tại.", 404)
    # A battle that is already RUNNING was left behind by a crash: the
    # status was written before the result was. It can be settled again,
    # because the whole result is written in one transaction now.
    if battle["status"] not in ("WAITING", "RUNNING"):
        return battle
    if len(battle["players"]) < 2:
        raise GameError("Cần ít nhất 2 người.")
    case = get_case(battle["case_id"])
    if not case:
        raise GameError("Rương trận không còn.")
    store.set_battle_status(battle_id, "RUNNING", started_at=store.now())
    drops = []
    drops_log: list[dict] = []
    totals: dict[str, int] = {}
    best: dict[str, int] = {}
    worst: dict[str, int] = {}
    for player_row in battle["players"]:
        player = player_row["player"]
        totals[player] = 0
        best[player] = 0
        worst[player] = 10**12
        for round_i in range(1, int(battle["rounds"]) + 1):
            prize = roll(case)
            public = prize.as_public()
            totals[player] += prize.coin
            best[player] = max(best[player], prize.coin)
            worst[player] = min(worst[player], prize.coin)
            drops.append(
                {
                    "player": player,
                    "round": round_i,
                    "id": public["id"],
                    "name": public["name"],
                    "rarity": public["rarity"],
                    "value": public["coin"],
                    "image": public["image"],
                    "color": public["color"],
                }
            )
            drops_log.append({
                "player": player,
                "is_bot": bool(player_row["is_bot"]),
                "id": public["id"],
                "name": public["name"],
                "rarity": public["rarity"],
                "coin": public["coin"],
                "image": public["image"],
                "color": public["color"],
                "case_id": case.id,
            })
    crazy = battle["mode"] == "CRAZY"
    ranked = sorted(
        battle["players"],
        key=lambda row: (
            totals[row["player"]] if crazy else -totals[row["player"]],
            worst[row["player"]] if crazy else -best[row["player"]],
        ),
    )
    # A tie must go to a random seat. Sorting by the slot number would
    # hand every tie to seat 0, which is always the host: with a 25%
    # chance of a tie in a single round that gave the host a 62% win
    # rate instead of a fair 50%.
    def same_rank(row: dict) -> bool:
        head = ranked[0]
        return (totals[row["player"]] == totals[head["player"]]
                and (worst if crazy else best)[row["player"]]
                == (worst if crazy else best)[head["player"]])

    top = [row for row in ranked if same_rank(row)]
    winner = random.choice(top)["player"] if top else ranked[0]["player"]
    # The result and the items go into the ledger in one transaction: if
    # the write fails, the battle stays open instead of being marked
    # finished with items that never reached the winner's bag.
    items = [
        {
            "id": drop["id"], "name": drop["name"], "rarity": drop["rarity"],
            "coin": drop["value"], "image": drop["image"], "color": drop["color"],
            "case_id": battle["case_id"],
        }
        for drop in drops
    ]
    store.finish_battle(battle_id, totals, drops, winner, items, drops_log)
    return store.get_battle(battle_id)


def claim_bonus(player: str) -> dict:
    last = store.last_bonus(player)
    elapsed = store.now() - last
    if last and elapsed < 24 * 3600:
        remain = 24 * 3600 - elapsed
        raise GameError(f"Bonus còn {remain // 3600} giờ {(remain % 3600) // 60} phút.")
    slices, weights = zip(*BONUS_SLICES, strict=True)
    prize = int(random.choices(list(slices), weights=list(weights), k=1)[0])
    # The slot is taken with a conditional UPDATE, so two requests at the
    # same time cannot both claim the bonus. The slot and the prize move
    # in one transaction, so a failed payout cannot eat the day.
    if not store.claim_bonus_and_credit(player, prize, store.now() - 24 * 3600):
        raise GameError("Bạn đã nhận bonus hôm nay.")
    return {"amount": prize, "balance": store.get_balance(player), "slices": list(slices)}


def site_stats_bar() -> dict:
    cases = load_cases()
    items = market_listings()
    data = store.stats()
    return {
        "cases": len(cases),
        "item_count": len(items),
        "pulls": data["pulls"],
        "battles": data["battles"],
        "upgrades": data.get("upgrades", 0),
        "users": data.get("users", 0),
        "online": len(store.BOT_NAMES),
        "online_bots": len(store.BOT_NAMES),
    }
