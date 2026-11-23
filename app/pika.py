from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import HTTPException

from .config import (
    PIKA_API_KEY,
    PIKA_AUTHME_DB,
    PIKA_BASE_URL,
    PIKA_ECONOMY_DB,
    PIKA_SERVER_UUID,
)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
_cached_server: str | None = None


def _headers() -> dict[str, str]:
    if not PIKA_API_KEY:
        raise HTTPException(status_code=503, detail="Chua cau hinh PIKA_API_KEY")
    return {
        "Authorization": f"Bearer {PIKA_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _safe_username(username: str) -> str | None:
    name = username.strip()
    if not USERNAME_RE.fullmatch(name):
        return None
    return name


def _cell(value: dict[str, Any] | None) -> Any:
    if value is None:
        return None
    if value.get("type") == "null":
        return None
    return value.get("value")


def _rows_as_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results") or []
    if not results:
        return []
    first = results[0]
    columns = [col.get("name") for col in first.get("columns") or []]
    out: list[dict[str, Any]] = []
    for row in first.get("rows") or []:
        # `strict=False` keeps a short row from breaking the whole answer.
        out.append({name: _cell(cell) for name, cell in zip(columns, row, strict=False)})
    return out


async def list_servers() -> list[dict[str, str]]:
    url = f"{PIKA_BASE_URL}/api/client/servers"
    params = {
        "page": 1,
        "per_page": 25,
        "other": "false",
        "scope": "owned",
        "sort": "created",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url, headers=_headers(), params=params)
    if response.status_code == 401:
        raise HTTPException(status_code=503, detail="API key PikaMC khong hop le")
    if response.status_code >= 400:
        raise HTTPException(status_code=503, detail=f"PikaMC servers HTTP {response.status_code}")
    data = response.json().get("servers", {}).get("data", [])
    return [
        {
            "uuid": item.get("uuid", ""),
            "name": item.get("name", ""),
            "short": item.get("uuid_short", ""),
        }
        for item in data
        if item.get("uuid")
    ]


async def get_server(server_id: str) -> dict[str, str]:
    url = f"{PIKA_BASE_URL}/api/client/servers/{server_id}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url, headers=_headers())
    if response.status_code == 401:
        raise HTTPException(status_code=503, detail="API key PikaMC khong hop le")
    if response.status_code == 403:
        raise HTTPException(
            status_code=503,
            detail="API key thieu quyen xem server. Can files.query-raw; neu test danh sach can them servers.read",
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=503, detail=f"PikaMC server HTTP {response.status_code}")
    item = response.json().get("server") or response.json()
    return {
        "uuid": item.get("uuid") or server_id,
        "name": item.get("name") or "",
        "short": item.get("uuid_short") or server_id,
    }


async def resolve_server_uuid() -> str:
    global _cached_server
    if _cached_server:
        return _cached_server
    if PIKA_SERVER_UUID:
        _cached_server = PIKA_SERVER_UUID
        return _cached_server
    servers = await list_servers()
    if not servers:
        raise HTTPException(status_code=503, detail="Tai khoan PikaMC khong co server")
    _cached_server = servers[0]["uuid"]
    return _cached_server


async def sqlite_query(file_path: str, query: str, rows: int = 5) -> list[dict[str, Any]]:
    server = await resolve_server_uuid()
    url = f"{PIKA_BASE_URL}/api/client/servers/{server}/files/sqlite-query"
    body = {
        "file": file_path,
        "query": query,
        "rows": rows,
        "read_only": True,
    }
    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.post(url, headers=_headers(), json=body)
    if response.status_code == 404:
        raise HTTPException(status_code=503, detail=f"Khong tim thay file tren PikaMC: {file_path}")
    if response.status_code == 401:
        raise HTTPException(status_code=503, detail="API key PikaMC khong hop le")
    if response.status_code >= 400:
        raise HTTPException(
            status_code=503,
            detail=f"PikaMC sqlite-query HTTP {response.status_code}",
        )
    return _rows_as_dicts(response.json())


async def find_authme_user(username: str) -> dict[str, Any] | None:
    name = _safe_username(username)
    if not name:
        return None
    query = (
        "SELECT username, realname, password FROM authme "
        f"WHERE LOWER(username) = LOWER('{name}') LIMIT 1"
    )
    rows = await sqlite_query(PIKA_AUTHME_DB, query, rows=1)
    return rows[0] if rows else None


async def send_command(command: str) -> None:
    global _console_ok
    server = await resolve_server_uuid()
    url = f"{PIKA_BASE_URL}/api/client/servers/{server}/command"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, headers=_headers(), json={"command": command})
    if response.status_code == 403:
        _console_ok = False
        raise HTTPException(
            status_code=503,
            detail="API key thieu quyen control.console. Bat quyen nay tren hub.pikamc.vn roi tao lai key.",
        )
    if response.status_code == 401:
        raise HTTPException(status_code=503, detail="API key PikaMC khong hop le")
    if response.status_code >= 400:
        raise HTTPException(status_code=503, detail=f"PikaMC command HTTP {response.status_code}")
    # The command went through, so the key has the console permission. The
    # flag is cleared here so a key that was fixed in the panel starts
    # working again without a restart.
    _console_ok = True


_console_ok = True


def console_available() -> bool:
    """False once the API key was seen lacking the control.console scope."""
    return _console_ok


def coin_amount(eco: dict[str, Any] | None) -> float:
    if not eco:
        return 0.0
    try:
        return float(eco.get("money") or 0)
    except (TypeError, ValueError):
        return 0.0


async def find_economy_user(username: str) -> dict[str, Any] | None:
    name = _safe_username(username)
    if not name:
        return None
    # A player can have more than one economy account with the same name.
    # The one seen most recently is the live one, so order by that and take
    # the first row. Without the order the server may return the stale one.
    query = (
        "SELECT uuid, name, last_seen, money, coins, shards "
        "FROM excellenteconomy_users "
        f"WHERE LOWER(name) = LOWER('{name}') "
        "ORDER BY CAST(last_seen AS BIGINT) DESC LIMIT 1"
    )
    rows = await sqlite_query(PIKA_ECONOMY_DB, query, rows=1)
    return rows[0] if rows else None


async def economy_balance(username: str) -> float | None:
    """Live ExcellentEconomy balance for a player, or None when unknown."""
    row = await find_economy_user(username)
    if row is None:
        return None
    try:
        return float(row.get("money") or 0)
    except (TypeError, ValueError):
        return None
