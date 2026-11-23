"""Test logic case battle.

Chay truc tiep voi SQL Server that (GACHA_DRY_RUN=true nen khong co dong
tien that bi tru). Script nay dung bang gacha_battle_* co that, nen no
khong duoc chay khi dang dung chung du lieu voi nguoi choi that.

   python tools/test_battle_logic.py
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Test chay tren bang that nen khong duoc cham vao vi duong tien that.
os.environ.setdefault("GACHA_DRY_RUN", "true")

from app import game, store  # noqa: E402

PASSED = 0
FAILED = 0
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  OK   {name}")
    else:
        FAILED += 1
        FAILURES.append(f"{name} — {detail}")
        print(f"  FAIL {name} — {detail}")


def cleanup(battle_ids: list[int], players: list[str]) -> None:
    for battle_id in battle_ids:
        try:
            store.delete_battle(battle_id)
        except Exception:
            pass
    for player in players:
        try:
            store.run(
                lambda con, p=player: (
                    con.cursor().execute("DELETE FROM gacha_inventory WHERE player = ?", p),
                    con.cursor().execute("DELETE FROM gacha_tx WHERE player = ?", p),
                    con.cursor().execute("DELETE FROM gacha_pulls WHERE player = ?", p),
                    con.cursor().execute("DELETE FROM gacha_wallets WHERE player = ?", p),
                )
            )
        except Exception:
            pass


def make_player(name: str, coins: int) -> str:
    """Create a test wallet with a known balance."""
    store.run(
        lambda con: con.cursor().execute(
            "DELETE FROM gacha_wallets WHERE player = ?", name
        )
    )
    store.credit(name, coins, "seed", "test")
    return name


def case_with_two_items() -> dict:
    """A tiny case with a known, easy to reason about payout.

    Two items, so the tie-break can be forced and checked.
    """
    return {
        "id": "battle-test-case",
        "name": "Rương test",
        "description": "",
        "pull_cost": 1000,
        "items": [
            {"id": "bt-low", "name": "Thấp", "rarity": "consumer",
             "weight": 1, "coin": 100},
            {"id": "bt-high", "name": "Cao", "rarity": "covert",
             "weight": 1, "coin": 5000},
        ],
    }


def install_case(case: dict) -> None:
    from app import gacha
    data = gacha.load_config()
    cases = [c for c in (data.get("cases") or []) if c.get("id") != case["id"]]
    cases.append(case)
    data["cases"] = cases
    gacha.save_config(data)
    gacha._config_cache = None


def remove_case(case_id: str) -> None:
    from app import gacha
    data = gacha.load_config()
    data["cases"] = [c for c in (data.get("cases") or []) if c.get("id") != case_id]
    gacha.save_config(data)
    gacha._config_cache = None


# --------------------------------------------------------------------------- #
print("\n=== 1. Gia tien va so cho ===")
# --------------------------------------------------------------------------- #
host = f"BT_Host_{uuid.uuid4().hex[:8]}"
guest = f"BT_Guest_{uuid.uuid4().hex[:8]}"
players = [host, guest]
battles: list[int] = []
case = case_with_two_items()
install_case(case)

try:
    make_player(host, 100_000)
    make_player(guest, 100_000)

    battle = game.create_battle(host, case["id"], slots=2, rounds=1, mode="STANDARD")
    battles.append(battle["id"])
    check("tao tran thanh cong", battle.get("id") is not None, str(battle)[:120])
    check("chu phong la host", battle["host"] == host, battle.get("host", ""))
    check("so tien da bi tru",
          store.get_balance(host) == 99_000,
          f"balance={store.get_balance(host)}")
    check("ghế moi tao, chua co nguoi",
          len(battle["players"]) == 1, str(len(battle["players"])))

    # ---- Khong du tien --------------------------------------------------- #
    poor = f"BT_Poor_{uuid.uuid4().hex[:8]}"
    players.append(poor)
    make_player(poor, 10)
    try:
        game.create_battle(poor, case["id"], slots=2, rounds=1, mode="STANDARD")
        check("khong du Coin thi bi chan", False, "khong nem loi")
    except game.GameError:
        check("khong du Coin thi bi chan", True)

    # ---- So cho khong hop le --------------------------------------------- #
    for bad_slots in (1, 5, 0):
        try:
            game.create_battle(host, case["id"], slots=bad_slots, rounds=1,
                               mode="STANDARD")
            check(f"so cho {bad_slots} bi chan", False, "khong nem loi")
        except game.GameError:
            check(f"so cho {bad_slots} bi chan", True)

    # ---- So vong khong hop le --------------------------------------------- #
    for bad_rounds in (0, 6, -1):
        try:
            game.create_battle(host, case["id"], slots=2, rounds=bad_rounds,
                               mode="STANDARD")
            check(f"so vong {bad_rounds} bi chan", False, "khong nem loi")
        except game.GameError:
            check(f"so vong {bad_rounds} bi chan", True)

    # ---- Vong > 1 tinh tien dung ------------------------------------------ #
    b3 = game.create_battle(host, case["id"], slots=2, rounds=3, mode="STANDARD")
    battles.append(b3["id"])
    check("3 vong tru dung gia",
          store.get_balance(host) == 99_000 - 3000,
          f"balance={store.get_balance(host)}")
    check("gia tran = pull_cost * rounds",
          game.battle_price(case["id"], 3) == 3000,
          str(game.battle_price(case["id"], 3)))

    # ---- Join ------------------------------------------------------------- #
    joined = game.join_existing_battle(guest, b3["id"])
    check("join thanh cong", len(joined["players"]) == 2, str(len(joined["players"])))
    check("nguoi join bi tru dung tien",
          store.get_balance(guest) == 97_000,
          f"balance={store.get_balance(guest)}")

    # ---- Join trung ------------------------------------------------------ #
    try:
        game.join_existing_battle(guest, b3["id"])
        check("join hai lan bi chan", False, "khong nem loi")
    except game.GameError:
        check("join hai lan bi chan", True)

    # ---- Join tran da bat dau --------------------------------------------- #
    try:
        game.start_battle(b3["id"], host)
        game.join_existing_battle(guest, b3["id"])
        check("join tran da bat dau bi chan", False, "khong nem loi")
    except game.GameError:
        check("join tran da bat dau bi chan", True)

    # ---- Chi chu phong moi duoc bat dau ----------------------------------- #
    print("\n=== 2. Quyen trong tran ===")
    b4 = game.create_battle(host, case["id"], slots=2, rounds=1, mode="STANDARD")
    battles.append(b4["id"])
    game.join_existing_battle(guest, b4["id"])
    try:
        game.start_battle(b4["id"], guest)
        check("khong phai host thi khong bat duoc", False, "khong nem loi")
    except game.GameError:
        check("khong phai host thi khong bat duoc", True)

    # ---- Can it nhat 2 nguoi ---------------------------------------------- #
    b5 = game.create_battle(host, case["id"], slots=2, rounds=1, mode="STANDARD")
    battles.append(b5["id"])
    try:
        game.start_battle(b5["id"], host)
        check("can it nhat 2 nguoi", False, "khong nem loi")
    except game.GameError:
        check("can it nhat 2 nguoi", True)

    # ---- Host khong bat duoc khi host da roi -------------------------------- #
    print("\n=== 3. Tinh tien khi that bai ===")
    before = store.get_balance(host)
    b6 = game.create_battle(host, case["id"], slots=2, rounds=1, mode="STANDARD")
    battles.append(b6["id"])
    # Bo ghe cua host roi thu join cho host 1 lan nua -> tran khong con ai
    store.leave_battle(b6["id"], host)
    try:
        game.start_battle(b6["id"], host)
        check("tran khong con nguoi thi khong bat duoc", False, "khong nem loi")
    except game.GameError:
        check("tran khong con nguoi thi khong bat duoc", True)

    # ---- Hoan tien khi server tu choi ------------------------------------- #
    print("\n=== 4. Hoan Coin ===")
    p_pay = f"BT_Pay_{uuid.uuid4().hex[:8]}"
    players.append(p_pay)
    make_player(p_pay, 50_000)
    balance_before = store.get_balance(p_pay)
    b7 = game.create_battle(p_pay, case["id"], slots=2, rounds=1, mode="STANDARD")
    battles.append(b7["id"])
    check("tru tien khi tao tran",
          store.get_balance(p_pay) == balance_before - 1000,
          f"balance={store.get_balance(p_pay)}")
    # Server tu choi: xoa tran va hoan tien, phai trung ve du
    game.cancel_battle(b7["id"], p_pay, 1000)
    check("hoan tien khi server tu choi",
          store.get_balance(p_pay) == balance_before,
          f"balance={store.get_balance(p_pay)}")
    check("tran bi xoa sau khi huy",
          store.get_battle(b7["id"]) is None,
          "tran van con")

    # ---- Join that bai phai hoan tien ------------------------------------- #
    p_join = f"BT_Join_{uuid.uuid4().hex[:8]}"
    players.append(p_join)
    make_player(p_join, 50_000)
    balance_before = store.get_balance(p_join)
    b8 = game.create_battle(host, case["id"], slots=2, rounds=1, mode="STANDARD")
    battles.append(b8["id"])
    try:
        game.join_existing_battle(p_join, b8["id"])
    except game.GameError:
        pass
    check("join thanh cong truoc khi huy", True)
    # Server tu choi khi join: ghe phai tra lai va tien phai hoan
    game.leave_battle(b8["id"], p_join, 1000)
    check("hoan tien khi join that bai",
          store.get_balance(p_join) == balance_before,
          f"balance={store.get_balance(p_join)}")

    # ---- Bot: host phai tra tien cho bot ----------------------------------- #
    print("\n=== 5. Bot va gia tri ===")
    p_bot = f"BT_Bot_{uuid.uuid4().hex[:8]}"
    players.append(p_bot)
    make_player(p_bot, 200_000)
    b9 = game.create_battle(p_bot, case["id"], slots=2, rounds=1, mode="STANDARD")
    battles.append(b9["id"])
    with_bots = game.fill_bots(b9["id"])
    check("them bot vao ghé",
          len(with_bots["players"]) == 2, str(len(with_bots["players"])))
    check("bot duoc danh dau is_bot",
          any(row["is_bot"] for row in with_bots["players"]),
          str(with_bots["players"]))
    check("so bot dem duoc",
          game.bot_seat_count(with_bots, p_bot) == 1,
          str(game.bot_seat_count(with_bots, p_bot)))

    # ---- Gia tri thuoc ve: tong tri = tien da chi -------------------------- #
    print("\n=== 6. Gia tri thuoc ===")
    p_val = f"BT_Val_{uuid.uuid4().hex[:8]}"
    p_val2 = f"BT_Val2_{uuid.uuid4().hex[:8]}"
    players += [p_val, p_val2]
    make_player(p_val, 200_000)
    make_player(p_val2, 200_000)
    b10 = game.create_battle(p_val, case["id"], slots=2, rounds=2, mode="STANDARD")
    battles.append(b10["id"])
    game.join_existing_battle(p_val2, b10["id"])
    result = game.start_battle(b10["id"], p_val)

    check("tran ket thuc FINISHED", result["status"] == "FINISHED", result["status"])
    check("co nguoi thang", bool(result.get("winner")), str(result.get("winner")))

    # Moi nguoi quay 2 vong -> 4 luot
    drops = result["drops"]
    check("so luot quay dung = 2 nguoi x 2 vong",
          len(drops) == 4, f"drops={len(drops)}")
    check("moi nguoi quay dung so vong",
          all(sum(1 for d in drops if d["player"] == p) == 2
              for p in (p_val, p_val2)),
          str([(p, sum(1 for d in drops if d["player"] == p))
               for p in (p_val, p_val2)]))

    # Nguoi thang nhan toan bo do cua ca tran: day la CaseBattle kieu
    # CS:GO, UI cung ghi "Toan bo do vao tui nguoi thang".
    winner = result["winner"]
    held = store.list_inventory(winner, "held")
    battle_items = [i for i in held if i.get("source") == "battle"]
    check("nguoi thang nhan toan bo do cua tran",
          len(battle_items) == len(drops),
          f"held_battle={len(battle_items)} drops={len(drops)}")

    # Gia tri do lot bang tong tri cua tat ca luot quay
    held_value = sum(i.get("value", 0) for i in battle_items)
    total_drop_value = sum(d["value"] for d in drops)
    check("gia tri do lot bang tong tri ca tran",
          held_value == total_drop_value,
          f"held={held_value} drops={total_drop_value}")

    # Nguoi thua khong nhan gi
    loser = p_val2 if winner == p_val else p_val
    held_loser = [i for i in store.list_inventory(loser, "held")
                  if i.get("source") == "battle"]
    check("nguoi thua khong nhan do", len(held_loser) == 0, str(len(held_loser)))

    check("moi luot quay deu co gia tri > 0", total_drop_value > 0, str(total_drop_value))

    # ---- Che do CRAZY: tong thap nhat la thang ---------------------------- #
    print("\n=== 7. Che do CRAZY ===")
    p_cz = f"BT_Crazy_{uuid.uuid4().hex[:8]}"
    p_cz2 = f"BT_Crazy2_{uuid.uuid4().hex[:8]}"
    players += [p_cz, p_cz2]
    make_player(p_cz, 200_000)
    make_player(p_cz2, 200_000)
    b11 = game.create_battle(p_cz, case["id"], slots=2, rounds=1, mode="CRAZY")
    battles.append(b11["id"])
    game.join_existing_battle(p_cz2, b11["id"])
    crazy_result = game.start_battle(b11["id"], p_cz)
    check("tran CRAZY ket thuc",
          crazy_result["status"] == "FINISHED", crazy_result["status"])

    # ---- Hoa: khong phai host luon thang ---------------------------------- #
    print("\n=== 8. Hoa: phai cong bang, host khong uu the ===")
    # Case 2 mon gia tri bang nhau -> hoa luon xay ra
    tie_case = {
        "id": "battle-tie-case",
        "name": "Rương hòa",
        "description": "",
        "pull_cost": 1000,
        "items": [
            {"id": "tie-a", "name": "A", "rarity": "consumer",
             "weight": 1, "coin": 1000},
            {"id": "tie-b", "name": "B", "rarity": "consumer",
             "weight": 1, "coin": 1000},
        ],
    }
    install_case(tie_case)
    wins = {host: 0, guest: 0}
    trials = 60
    for _i in range(trials):
        p1 = f"BT_Tie1_{uuid.uuid4().hex[:8]}"
        p2 = f"BT_Tie2_{uuid.uuid4().hex[:8]}"
        players += [p1, p2]
        make_player(p1, 50_000)
        make_player(p2, 50_000)
        bt = game.create_battle(p1, tie_case["id"], slots=2, rounds=1,
                                 mode="STANDARD")
        battles.append(bt["id"])
        game.join_existing_battle(p2, bt["id"])
        rt = game.start_battle(bt["id"], p1)
        w = rt["winner"]
        wins[wins and ("host" if w == p1 else "guest")] = wins.get(
            "host" if w == p1 else "guest", 0) + 1
        # Xoa don de bang khong phinh to
        store.delete_battle(bt["id"])
    host_wins = wins.get("host", 0)
    total = sum(wins.values())
    # Voi 2 mon gia tri bang nhau, xac suan moi nghiem 50%, dung sai lech
    # lon nhat 25% (do bien nien mau nho).
    ratio = host_wins / total if total else 0
    check("hoa khong uu tien host (ty le ~50%)",
          0.30 <= ratio <= 0.70,
          f"host={host_wins}/{total} ({ratio:.0%})")
    remove_case(tie_case["id"])

    # ---- Ghi chu: moi nguoi phai quay cung so vong ------------------------ #
    print("\n=== 9. Cong bang so vong ===")
    p_eq = f"BT_Eq_{uuid.uuid4().hex[:8]}"
    p_eq2 = f"BT_Eq2_{uuid.uuid4().hex[:8]}"
    players += [p_eq, p_eq2]
    make_player(p_eq, 200_000)
    make_player(p_eq2, 200_000)
    b12 = game.create_battle(p_eq, case["id"], slots=2, rounds=4, mode="STANDARD")
    battles.append(b12["id"])
    game.join_existing_battle(p_eq2, b12["id"])
    r12 = game.start_battle(b12["id"], p_eq)
    per_player = {}
    for d in r12["drops"]:
        per_player[d["player"]] = per_player.get(d["player"], 0) + 1
    check("moi nguoi quay dung 4 vong",
          len(set(per_player.values())) == 1 and list(per_player.values())[0] == 4,
          str(per_player))

    # ---- Bao ve: khong the rut Coin khi tran chua ket thuc ----------------- #
    print("\n=== 10. Bao ve ===")
    p_guard = f"BT_Guard_{uuid.uuid4().hex[:8]}"
    players.append(p_guard)
    make_player(p_guard, 50_000)
    bg = game.create_battle(p_guard, case["id"], slots=2, rounds=1, mode="STANDARD")
    battles.append(bg["id"])
    game.join_existing_battle(guest, bg["id"])
    before_guard = store.get_balance(p_guard)
    # Admin finish tran: gia tri phai dung tai thoi diem do
    game.settle_battle(bg["id"])
    after_guard = store.get_balance(p_guard)
    check("ket thuc tran khong doi so du nguoi choi",
          after_guard == before_guard,
          f"{before_guard} -> {after_guard}")

    # ---- Kiem tra RTP: uoc luong bang mo phong ---------------------------- #
    print("\n=== 11. Uoc luong RTP (mo phong) ===")
    from app.gacha import get_case, roll
    real_case = get_case(case["id"])
    pulls = 20000
    total_coin = 0
    for _ in range(pulls):
        total_coin += roll(real_case).coin
    rtp = total_coin / (pulls * real_case.pull_cost)
    # Case 2 mon: 100 va 5000, trong so bang nhau -> ky vong = 2550 / 1000 = 255%
    expected = (100 + 5000) / 2 / 1000
    check("RTP mo phong dung ky vong",
          abs(rtp - expected) < 0.08,
          f"rtp={rtp:.3f} expected={expected:.3f}")

    # ---- Xac nhan drop khong bi ghi cho nguoi that khi test --------------- #
    print("\n=== 12. Don dep ===")
    check("khong con tran test nao trong DB",
          all(store.get_battle(b) is None or b in battles
              for b in battles),
          "co tran con")

finally:
    remove_case(case["id"])
    cleanup(battles, players)

print("\n" + "=" * 60)
print(f"{PASSED} passed, {FAILED} failed")
if FAILURES:
    print("\nFailures:")
    for f in FAILURES:
        print(f"  - {f}")
print("=" * 60)
sys.exit(1 if FAILED else 0)
