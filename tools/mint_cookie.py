"""Mint a session cookie exactly the way starlette's SessionMiddleware does.

Starlette: data = b64encode(json.dumps(session)) then signer.sign(data)
where signer = itsdangerous.TimestampSigner(secret_key)  (no salt, sha1 hmac).
"""
import base64
import json
import os
import sys

import itsdangerous

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import SESSION_SECRET  # noqa: E402


def mint(session: dict) -> str:
    signer = itsdangerous.TimestampSigner(str(SESSION_SECRET))
    data = base64.b64encode(json.dumps(session).encode("utf-8"))
    return signer.sign(data).decode("utf-8")


if __name__ == "__main__":
    sess = {"user": "Tester", "login_name": "Tester", "csrf": "test-csrf-token"}
    print(mint(sess))
