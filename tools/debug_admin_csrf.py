"""Debug why the admin login CSRF check fails in the test client."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from app import main as main_module

BASE = "http://testserver"


def show(client, label):
    r = client.get("/admin/login", follow_redirects=False)
    print(f"[{label}] GET /admin/login -> {r.status_code} loc={r.headers.get('location','')}")
    if r.status_code == 200:
        marker = 'name="csrf" value="'
        if marker in r.text:
            print(f"[{label}] csrf in page: {r.text.split(marker)[1].split(chr(34))[0][:20]}")
        else:
            print(f"[{label}] NO csrf in page")
    return r


client = TestClient(main_module.app)
client.cookies.clear()

r = show(client, "fresh")
csrf = r.text.split('name="csrf" value="')[1].split('"')[0] if 'name="csrf" value="' in r.text else ""

print("session csrf:", client.cookies.get("jv_session"))

r = client.post("/admin/login", data={"username": "NotAnAdmin", "password": "x", "csrf": csrf},
                follow_redirects=False)
print("POST unknown admin ->", r.status_code, r.headers.get("location"))
print("cookies after:", client.cookies.get("jv_session"))

# Now check what the session holds
print("\n--- checking session csrf after failed post ---")
r2 = client.get("/admin/login", follow_redirects=False)
print("GET again ->", r2.status_code, r2.headers.get("location", ""))
if r2.status_code == 200 and 'name="csrf" value="' in r2.text:
    csrf2 = r2.text.split('name="csrf" value="')[1].split('"')[0]
    print("csrf2:", csrf2[:20])
    r3 = client.post("/admin/login", data={"username": "NotAnAdmin", "password": "x", "csrf": csrf2},
                     follow_redirects=False)
    print("POST again with fresh csrf ->", r3.status_code, r3.headers.get("location"))
