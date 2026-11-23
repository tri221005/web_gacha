"""Probe: the rate limit tables must not grow without bound.

Every failed login creates a bucket. If the buckets are never dropped, an
attacker who sprays many addresses grows the dicts forever and the app
leaks memory.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import security  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


security._attempts.clear()
security._account_attempts.clear()

# 5000 different addresses, one attempt each.
for i in range(5000):
    security.record_failed_login(f"10.0.{i // 256}.{i % 256}", f"user{i}")

ip_buckets = len(security._attempts)
acct_buckets = len(security._account_attempts)
check("the rate limit tables stay bounded",
      ip_buckets <= security._MAX_BUCKETS + 1
      and acct_buckets <= security._MAX_BUCKETS + 1,
      f"ip buckets={ip_buckets} account buckets={acct_buckets} "
      f"(the cap is {security._MAX_BUCKETS})")

# The oldest attempts must have been forgotten, so the app can still log in.
check("an address with no recent failures is allowed again",
      security.login_allowed("10.0.0.1", "user0"),
      "the bucket was dropped, so the address is fresh")

# A real attack on one address is still blocked.
for _ in range(20):
    security.record_failed_login("10.9.9.9", "target")
check("a real attack is still blocked",
      not security.login_allowed("10.9.9.9", "target"),
      "20 failures on one address")

failed = [(n, d) for n, ok, d in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
if failed:
    for name, detail in failed:
        print(f"  - {name}  {detail}")
sys.exit(1 if failed else 0)
