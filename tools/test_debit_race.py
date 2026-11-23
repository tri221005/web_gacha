"""A race check on the wallet debit.

Two requests that open a case at the same time must not both take the
Coin. The debit is guarded in the UPDATE itself, so only one of them
gets the drop.

Run:  python tools/test_debit_race.py
"""
from __future__ import annotations

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import store  # noqa: E402

PLAYER = "debitrace"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def reset(balance: int) -> None:
    store.run(lambda con: con.cursor().execute(
        "DELETE FROM gacha_wallets WHERE player = ?", PLAYER))
    store.run(lambda con: con.cursor().execute(
        "DELETE FROM gacha_tx WHERE player = ?", PLAYER))
    store.credit(PLAYER, balance, "seed", "test")


def main() -> None:
    store.init()

    print("== Two debits at the same time ==")
    # 100 Coin in the wallet, each thread wants 80. Only one can win.
    reset(100)
    errors: list[str] = []
    barrier = threading.Barrier(2)

    def take() -> None:
        barrier.wait()
        try:
            store.debit(PLAYER, 80, "open", "race")
        except ValueError as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=take) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    balance = store.get_balance(PLAYER)
    check("only one of the two debits went through", len(errors) == 1,
          f"{len(errors)} were refused")
    check("the balance is not negative", balance >= 0, f"balance={balance}")
    check("the balance is 20, not -60", balance == 20, f"balance={balance}")

    print("\n== Eight debits at the same time ==")
    reset(100)
    errors.clear()
    barrier = threading.Barrier(8)

    def take8() -> None:
        barrier.wait()
        try:
            store.debit(PLAYER, 80, "open", "race")
        except ValueError:
            errors.append("refused")

    threads = [threading.Thread(target=take8) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    balance = store.get_balance(PLAYER)
    check("only one of the eight debits went through", len(errors) == 7,
          f"{len(errors)} were refused")
    check("the balance is 20", balance == 20, f"balance={balance}")

    print("\n== A debit that is exactly the balance ==")
    reset(50)
    store.debit(PLAYER, 50, "open", "exact")
    check("the wallet can be emptied", store.get_balance(PLAYER) == 0)
    try:
        store.debit(PLAYER, 1, "open", "over")
        check("a debit over the balance is refused", False, "it went through")
    except ValueError:
        check("a debit over the balance is refused", True)

    print("\n== A debit from a wallet that does not exist ==")
    store.run(lambda con: con.cursor().execute(
        "DELETE FROM gacha_wallets WHERE player = ?", PLAYER))
    try:
        store.debit(PLAYER, 10, "open", "missing")
        check("a missing wallet is refused", False, "it went through")
    except ValueError:
        check("a missing wallet is refused", True)

    # Clean up.
    store.run(lambda con: con.cursor().execute(
        "DELETE FROM gacha_wallets WHERE player = ?", PLAYER))
    store.run(lambda con: con.cursor().execute(
        "DELETE FROM gacha_tx WHERE player = ?", PLAYER))

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name in failed:
            print(f"  - {name}")


main()
