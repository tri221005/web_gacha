"""List every route in the app and show which guards it uses."""
import pathlib
import re

src = pathlib.Path(__file__).resolve().parent.parent / "app" / "main.py"
lines = src.read_text(encoding="utf-8").splitlines()
routes = []
for i, line in enumerate(lines):
    m = re.match(r'@app\.(get|post|put|delete|patch)\("([^"]+)"', line)
    if not m:
        continue
    body = []
    j = i + 1
    while j < len(lines) and not lines[j].startswith("@app."):
        body.append(lines[j])
        j += 1
    body = "\n".join(body)
    mn = re.search(r"async def (\w+)", body)
    name = mn.group(1) if mn else ""
    routes.append((m.group(1).upper(), m.group(2), name, i + 1, body))

print("total routes", len(routes))
bad = []
for meth, path, name, ln, body in routes:
    guards = []
    if "api_auth" in body or "require_admin" in body or "admin_auth" in body:
        guards.append("api/admin")
    if "require_login" in body:
        guards.append("login")
    if "require_csrf" in body:
        guards.append("csrf")
    if "csrf=True" in body:
        guards.append("csrf=True")
    if not guards:
        bad.append((meth, path, name, ln))
    flag = "  OK " if guards else "!!!!"
    print(f"{flag} L{ln:5d} {meth:6s} {path:45s} {name:32s} {guards}")

print("\n--- routes with no guard ---")
for meth, path, name, ln in bad:
    print(f"L{ln} {meth} {path} ({name})")
