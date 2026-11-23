from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from fastapi import Request

_MAX_ATTEMPTS = 8
_WINDOW_SECONDS = 10 * 60
# A second bucket per account, so one attacker cannot try many passwords
# against one account from many addresses.
_MAX_ATTEMPTS_PER_ACCOUNT = 12
# Buckets are dropped once they are empty, so the dicts cannot grow without
# bound when many different addresses are tried.
_MAX_BUCKETS = 4096
_attempts: dict[str, deque[float]] = defaultdict(deque)
_account_attempts: dict[str, deque[float]] = defaultdict(deque)


def verify_authme_sha256(password: str, stored: str) -> bool:
    if not stored or not stored.startswith("$SHA$"):
        return False
    parts = stored.split("$")
    if len(parts) < 4:
        return False
    salt, expected = parts[2], parts[3]
    inner = hashlib.sha256(password.encode("utf-8")).hexdigest()
    actual = hashlib.sha256((inner + salt).encode("utf-8")).hexdigest()
    return hmac.compare_digest(actual.lower(), expected.lower())


def client_ip(request: Request) -> str:
    """The address of the client, for rate limiting.

    `X-Forwarded-For` is set by the client and can be forged, so it is not
    trusted on its own. `CF-Connecting-IP` is written by Cloudflare and
    cannot be forged by the browser, so it wins when present. The plain
    socket address is the fallback.
    """
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Only the left-most entry is the original client, but it can be
        # forged, so the socket address is used as the bucket key instead.
        # Cloudflare deployments are handled by the branch above.
        return request.client.host if request.client else forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def login_allowed(ip: str, username: str = "") -> bool:
    now = time.time()
    bucket = _attempts[ip]
    while bucket and now - bucket[0] > _WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _MAX_ATTEMPTS:
        return False
    if username:
        account = _account_attempts[username.lower()]
        while account and now - account[0] > _WINDOW_SECONDS:
            account.popleft()
        if len(account) >= _MAX_ATTEMPTS_PER_ACCOUNT:
            return False
    return True


def record_failed_login(ip: str, username: str = "") -> None:
    _attempts[ip].append(time.time())
    if username:
        _account_attempts[username.lower()].append(time.time())
    _drop_empty_buckets()


def _drop_empty_buckets() -> None:
    """Forget buckets that are past the window.

    Without this the dicts keep one entry per address ever tried, which
    grows without limit under a spray attack.
    """
    now = time.time()
    for buckets in (_attempts, _account_attempts):
        for key in [k for k, v in buckets.items() if not v or now - v[0] > _WINDOW_SECONDS]:
            del buckets[key]
    if len(_attempts) > _MAX_BUCKETS or len(_account_attempts) > _MAX_BUCKETS:
        for buckets in (_attempts, _account_attempts):
            for key in list(buckets.keys())[:_MAX_BUCKETS]:
                buckets.pop(key, None)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
