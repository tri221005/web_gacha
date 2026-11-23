"""Run the whole test suite in one go.

Every script in this folder that starts with `test_` is a check of its
own. This runs them one after another and prints a summary, so a broken
change is easy to spot.

Some of the checks need a web server on port 8099. This script starts
one, waits for it to answer, runs the checks and stops it again.

Run:  python tools/run_all_tests.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
PORT = int(os.getenv("TEST_PORT", "8099"))
BASE = f"http://127.0.0.1:{PORT}"

# The checks that do not need a browser or a running server.
UNIT_TESTS = [
    "test_session_cookie.py",
    "test_admin.py",
    "test_battle_logic.py",
    "test_debit_race.py",
    "test_audit_logic.py",
    "test_audit_concurrency.py",
    "test_security.py",
    "test_security_all.py",
    "test_admin_login_sync.py",
    "test_admin_sync_offline.py",
    "test_battle_money.py",
    "test_battle_economy_all_cases.py",
    "test_battle_bot_economy.py",
    "test_live_money_flow.py",
    "selftest_store.py",
]

# The checks that drive a browser against a running server.
BROWSER_TESTS = [
    "test_realtime_ui.py",
    "test_realtime_sync.py",
    "test_auto_sync.py",
    "test_refresh_button.py",
    "test_admin_ui.py",
    "test_login_playwright.py",
    "test_login_all_players.py",
    "test_login_casing.py",
    "test_login_identity.py",
    "test_ui_responsive.py",
    "smoke_http.py",
    "smoke_test.py",
    "smoke_test_auth.py",
]


def python() -> str:
    """The interpreter of the virtual environment, if there is one."""
    for name in (".venv/Scripts/python.exe", "venv/Scripts/python.exe"):
        candidate = ROOT / name
        if candidate.exists():
            return str(candidate)
    return sys.executable


def wait_for_server(proc: subprocess.Popen, timeout: float = 45.0) -> bool:
    """Wait until the server answers on its health check."""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=5) as res:
                if res.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    return False


def run(name: str) -> bool:
    """Run one test script and report whether it passed."""
    path = TOOLS / name
    if not path.exists():
        print(f"SKIP  {name} (not found)")
        return True
    started = time.time()
    env = dict(os.environ)
    env["BASE_URL"] = BASE
    env["LOGIN_TEST_BASE"] = BASE
    proc = subprocess.run(
        [python(), str(path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    took = time.time() - started
    if proc.returncode == 0:
        print(f"PASS  {name}  ({took:.1f}s)")
        return True
    print(f"FAIL  {name}  ({took:.1f}s)")
    tail = (proc.stdout or "") + (proc.stderr or "")
    for line in tail.strip().splitlines()[-15:]:
        print(f"        {line}")
    return False


def main() -> int:
    results: list[tuple[str, bool]] = []

    print("=" * 60)
    print("UNIT CHECKS")
    print("=" * 60)
    for name in UNIT_TESTS:
        results.append((name, run(name)))

    print()
    print("=" * 60)
    print("BROWSER CHECKS")
    print("=" * 60)

    env = dict(os.environ)
    env["PORT"] = str(PORT)
    server = subprocess.Popen(
        [python(), str(TOOLS / "login_test_server.py")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_for_server(server):
            print("the test server did not start, the browser checks are skipped")
            for name in BROWSER_TESTS:
                results.append((name, False))
        else:
            print(f"the test server is up on {BASE}")
            print()
            for name in BROWSER_TESTS:
                results.append((name, run(name)))
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    failed = [name for name, ok in results if not ok]
    print()
    print("=" * 60)
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("failed:")
        for name in failed:
            print(f"  - {name}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
