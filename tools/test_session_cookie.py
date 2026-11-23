"""The session cookie has to work on HTTP and on HTTPS.

The old build decided once, at startup, whether the session cookie got
the `Secure` flag. With it on, the browser refuses to send the cookie
back over plain HTTP, so every page after the login looked logged out
and every CSRF check failed. That broke local development and every
test run. The cookie now follows the request instead.

These checks cover the three cases: plain HTTP, plain HTTPS and a
request that came through a TLS-terminating proxy.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.session import AdaptiveSessionMiddleware, request_is_https  # noqa: E402

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, extra: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  OK   {label}")
    else:
        FAILED += 1
        print(f"  FAIL {label} {extra}")


def build(https_only: bool | None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        AdaptiveSessionMiddleware,
        secret_key="secret-for-the-session-test-only",
        session_cookie="jv_session",
        same_site="lax",
        https_only=https_only,
        max_age=3600,
    )

    @app.get("/set")
    def set_session(request: Request):
        request.session["user"] = "Tester"
        request.session["csrf"] = "tok"
        return {"ok": True}

    @app.get("/get")
    def get_session(request: Request):
        return {"user": request.session.get("user"),
                "csrf": request.session.get("csrf")}

    return app


def cookie_is_secure(client: TestClient, response=None) -> bool:
    """True when the session cookie carries the `Secure` flag.

    The raw header is read from the response, because the HTTP client
    itself drops a `Secure` cookie when the address is plain HTTP.
    """
    if response is not None:
        header = response.headers.get("set-cookie", "")
        if "jv_session=" not in header:
            return False
        return "; secure" in header.lower()
    for cookie in client.cookies.jar:
        if cookie.name == "jv_session":
            return "secure" in cookie._rest
    return False


def main() -> int:
    print("== the session survives a plain HTTP request ==")
    client = TestClient(build(None), base_url="http://testserver")
    response = client.get("/set")
    check("the cookie is not marked Secure on plain HTTP",
          not cookie_is_secure(client, response))
    got = client.get("/get").json()
    check("the session is still there on the next request",
          got["user"] == "Tester", str(got))
    check("the csrf token is still there",
          got["csrf"] == "tok", str(got))

    print("\n== the session survives an HTTPS request ==")
    client = TestClient(build(None), base_url="https://testserver")
    response = client.get("/set")
    check("the cookie is marked Secure on HTTPS",
          cookie_is_secure(client, response))
    got = client.get("/get").json()
    check("the session is still there on the next request",
          got["user"] == "Tester", str(got))

    print("\n== a proxy that terminates TLS ==")
    client = TestClient(build(None), base_url="http://testserver")
    response = client.get("/set", headers={"X-Forwarded-Proto": "https"})
    check("the cookie is marked Secure behind the proxy",
          cookie_is_secure(client, response))

    print("\n== the flag can be forced ==")
    client = TestClient(build(True), base_url="http://testserver")
    response = client.get("/set")
    check("https_only=True always marks the cookie Secure",
          cookie_is_secure(client, response))

    client = TestClient(build(False), base_url="https://testserver")
    response = client.get("/set")
    check("https_only=False never marks the cookie Secure",
          not cookie_is_secure(client, response))

    print("\n== the request helper ==")
    check("https is recognised",
          request_is_https({"scheme": "https", "headers": []}))
    check("http is recognised",
          not request_is_https({"scheme": "http", "headers": []}))
    check("the proxy header wins over the socket scheme",
          request_is_https({
              "scheme": "http",
              "headers": [(b"x-forwarded-proto", b"https")],
          }))
    check("a list of proxy schemes uses the first one",
          request_is_https({
              "scheme": "http",
              "headers": [(b"x-forwarded-proto", b"https, http")],
          }))

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
