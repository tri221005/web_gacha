"""Test server: same app, but the password check accepts one known password.

Only `verify_authme_sha256` is patched. Everything else — reading AuthMe
from the live PikaMC API, building the session, fetching the live
ExcellentEconomy balance — runs unchanged, so the test exercises the real
login flow for every player.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_PASSWORD = os.getenv("LOGIN_TEST_PASSWORD", "matkhau123")

from app import main as main_mod  # noqa: E402
from app.security import verify_authme_sha256 as _real_verify  # noqa: E402


def _patched(password: str, stored: str) -> bool:
    """Accept the test password for any real AuthMe hash."""
    if password == TEST_PASSWORD and stored and stored.startswith("$SHA$"):
        return True
    return _real_verify(password, stored)


main_mod.verify_authme_sha256 = _patched

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main_mod.app, host="127.0.0.1",
                port=int(os.getenv("PORT", "8123")), log_level="warning")
