"""The session middleware with a `Secure` flag that follows the request.

Starlette's own `SessionMiddleware` decides once, at startup, whether the
session cookie gets the `Secure` flag. That is wrong for a site that is
served over HTTPS in production and over plain HTTP on a developer
machine: with `Secure` on, the browser refuses to send the cookie back
over HTTP, so every page after the login looks logged out and every CSRF
check fails. With it off, the cookie would travel over plain HTTP in
production.

This middleware looks at the request instead. The cookie is marked
`Secure` when the request arrived over HTTPS, and left alone when it
arrived over plain HTTP. The proxy header is honoured, so a site behind a
TLS-terminating proxy still gets a secure cookie.
"""
from __future__ import annotations

import json
from base64 import b64decode, b64encode
from http.cookies import CookieError, SimpleCookie

import itsdangerous
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def request_is_https(scope: Scope) -> bool:
    """True when the request that is being answered arrived over HTTPS.

    A reverse proxy terminates TLS and talks plain HTTP to the app, so
    the header it sets is the only hint about the real scheme.
    """
    for key, value in scope.get("headers") or []:
        if key == b"x-forwarded-proto":
            proto = value.decode("latin-1").split(",")[0].strip().lower()
            if proto:
                return proto == "https"
    return scope.get("scheme") == "https"


class AdaptiveSessionMiddleware:
    """Signed cookie session whose `Secure` flag follows the request.

    `https_only=True` forces the flag on and `https_only=False` forces
    it off, exactly like Starlette's own middleware. `https_only=None`
    follows the request that is being answered.
    """

    def __init__(self, app: ASGIApp, secret_key: str, *,
                 session_cookie: str = "session", max_age: int | None = 86400,
                 path: str = "/", same_site: str = "lax",
                 https_only: bool | None = False,
                 domain: str | None = None) -> None:
        self.app = app
        self.signer = itsdangerous.TimestampSigner(secret_key)
        self.session_cookie = session_cookie
        self.max_age = max_age
        self.path = path
        self.same_site = same_site
        self.https_only = https_only
        self.domain = domain

    def _flags(self, secure: bool) -> str:
        flags = f"httponly; samesite={self.same_site}"
        if secure:
            flags += "; secure"
        if self.domain is not None:
            flags += f"; domain={self.domain}"
        return flags

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        cookie = self._read_cookie(scope)
        scope["session"] = cookie[0]
        had_cookie = cookie[1]

        secure = self.https_only
        if secure is None:
            secure = request_is_https(scope)
        flags = self._flags(secure)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if scope["session"]:
                    data = b64encode(json.dumps(scope["session"]).encode("utf-8"))
                    data = self.signer.sign(data)
                    header = (
                        f"{self.session_cookie}={data.decode('utf-8')}; "
                        f"path={self.path}; "
                        + (f"Max-Age={self.max_age}; " if self.max_age else "")
                        + flags
                    )
                    headers.append("Set-Cookie", header)
                elif had_cookie:
                    header = (
                        f"{self.session_cookie}=null; path={self.path}; "
                        "expires=Thu, 01 Jan 1970 00:00:00 GMT; " + flags
                    )
                    headers.append("Set-Cookie", header)
            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _read_cookie(self, scope: Scope) -> tuple[dict, bool]:
        """Find and verify the session cookie.

        A request can carry the cookie twice: once from the client's own
        jar and once from a per-request override. The parser keeps the
        last one, the same way Starlette's own middleware does, so the
        behaviour does not change.
        """
        for key, value in scope.get("headers") or []:
            if key != b"cookie":
                continue
            jar = SimpleCookie()
            try:
                jar.load(value.decode("latin-1"))
            except CookieError:
                return {}, False
            morsel = jar.get(self.session_cookie)
            if morsel is None:
                return {}, False
            try:
                data = self.signer.unsign(
                    morsel.value.encode("utf-8"), max_age=self.max_age
                )
                return json.loads(b64decode(data)), True
            except (itsdangerous.BadSignature, ValueError, TypeError):
                return {}, True
        return {}, False


__all__ = ["AdaptiveSessionMiddleware", "request_is_https"]
