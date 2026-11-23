"""A fake PikaMC panel used by the live-money-flow test.

Implements the two endpoints the app talks to:
  POST /api/client/servers/{uuid}/files/sqlite-query  (AuthMe / Economy)
  POST /api/client/servers/{uuid}/command              (eco take / eco give)
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

PLAYER = "StubPlayer"

SERVER_BALANCE = {PLAYER: 100000.0}
SERVER_USERS = {PLAYER: {"uuid": "stub-uuid", "name": PLAYER, "last_seen": "1795412451675"}}
AUTHME = {PLAYER.lower(): {
    "username": PLAYER.lower(), "realname": PLAYER,
    "password": "$SHA$deadbeef$" + "0" * 64,
}}


def _panel_rows(rows: list[dict]) -> dict:
    """Answer in the panel's sqlite-query envelope.

    Every cell is an object with a `type` and a `value`, the way the panel
    serialises SQLite values.
    """
    if not rows:
        return {"results": []}
    keys = list(rows[0])
    columns = [{"name": key} for key in keys]
    data = [
        [{"type": "text", "value": row.get(key)} for key in keys]
        for row in rows
    ]
    return {"results": [{"columns": columns, "rows": data}]}


def build_stub() -> FastAPI:
    app = FastAPI()

    @app.post("/api/client/servers/{uuid}/files/sqlite-query")
    async def sqlite_query(request: Request):
        body = await request.json()
        path = body.get("file", "").lower()
        query = body.get("query", "").lower()
        if "authme" in path:
            for row in AUTHME.values():
                if row["username"].lower() in query:
                    return JSONResponse(_panel_rows([dict(row)]))
            return JSONResponse({"results": []})
        if "excellenteconomy" in path:
            for row in SERVER_USERS.values():
                if row["name"].lower() in query:
                    return JSONResponse(_panel_rows([{
                        **row,
                        "money": SERVER_BALANCE[row["name"]],
                        "coins": "0", "shards": "0",
                    }]))
            return JSONResponse({"results": []})
        return JSONResponse({"results": []})

    @app.post("/api/client/servers/{uuid}/command")
    async def command(request: Request):
        body = await request.json()
        parts = body.get("command", "").split()
        if len(parts) == 4 and parts[0] == "eco" and parts[1] in ("take", "give"):
            action, name, amount = parts[1], parts[2], float(parts[3])
            if name in SERVER_BALANCE:
                SERVER_BALANCE[name] = max(
                    0.0, SERVER_BALANCE[name] + (-amount if action == "take" else amount)
                )
        return JSONResponse({"ok": True})

    return app
