"""Round-trip test of every store write path against SQL Server."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store  # noqa: E402
from app.gacha import load_cases  # noqa: E402

store.init()
case = load_cases()[0]
item = case.items[0]
player = "__selftest__"

print("wallet seed:", store.ensure_wallet(player, seed=1000))
print("balance:", store.get_balance(player))
print("credit:", store.credit(player, 500, "seed", "selftest"))
print("debit:", store.debit(player, 200, "open", "selftest"))

inv_id = store.add_inventory(player, item, "case", case.id)
print("inventory id:", inv_id, "->", store.get_inventory_item(inv_id)["name"])
print("list:", len(store.list_inventory(player, "held")))

store.record_drop(player, item, case.id)
print("drops:", len(store.recent_drops(30)))

store.record_pull(player, case.pull_cost, item, case_id=case.id, dry=True)
store.record_upgrade(player, {"name": item.name, "coin": item.coin},
                     item.as_public(), 0.5, 0.1, True)
print("bonus before:", store.last_bonus(player))
print("bonus after:", store.claim_bonus_slot(player, 0), store.last_bonus(player))

battle_id = store.create_battle(player, case.id, 1, 2, "STANDARD", 100, False)
print("battle:", battle_id, store.get_battle(battle_id)["status"])
store.join_battle(battle_id, "SelftestBot2", True, 100)
print("players:", len(store.get_battle(battle_id)["players"]))
store.set_battle_status(battle_id, "RUNNING", started_at=store.now())
drop = {"player": player, "round": 1, "id": item.id, "name": item.name,
        "rarity": item.rarity, "value": item.coin, "image": item.image,
        "color": item.color}
store.finish_battle(
    battle_id, {player: 100}, [drop], player,
    [{"id": item.id, "name": item.name, "rarity": item.rarity,
      "coin": item.coin, "image": item.image, "color": item.color,
      "case_id": case.id}],
)
print("battle final:", store.get_battle(battle_id)["status"],
      store.get_battle(battle_id)["winner"])
print("lobby finished:", len(store.list_battles()["finished"]))
print("stats pulls:", store.stats()["pulls"])
print("tx:", len(store.recent_tx(player, 20)))

# cleanup the self-test rows
with store._lock:
    con = store.connect()
    cur = con.cursor()
    cur.execute("DELETE FROM gacha_battle_drops WHERE battle_id = ?", battle_id)
    cur.execute("DELETE FROM gacha_battle_players WHERE battle_id = ?", battle_id)
    cur.execute("DELETE FROM gacha_battles WHERE id = ?", battle_id)
    cur.execute("DELETE FROM gacha_pulls WHERE player = ?", player)
    cur.execute("DELETE FROM gacha_inventory WHERE player = ?", player)
    cur.execute("DELETE FROM gacha_drops WHERE player = ?", player)
    cur.execute("DELETE FROM gacha_upgrades WHERE player = ?", player)
    cur.execute("DELETE FROM gacha_bonus WHERE player = ?", player)
    cur.execute("DELETE FROM gacha_tx WHERE player = ?", player)
    cur.execute("DELETE FROM gacha_wallets WHERE player = ?", player)
    con.commit()
print("\ncleanup done -- all write paths OK")
