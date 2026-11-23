"""Check how many failed sign-ins it takes to trip the rate limiter."""
import re
import sys

sys.path.insert(0, ".")
import httpx

with httpx.Client(base_url="http://127.0.0.1:8099", timeout=30) as c:
    r = c.get("/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
    for i in range(10):
        rr = c.post("/login", data={"username": "Trez1724",
                                     "password": "wrong", "csrf": csrf},
                    follow_redirects=False)
        print(i + 1, rr.headers.get("location"))
