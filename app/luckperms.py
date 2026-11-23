"""Keep the web admin list and the Minecraft admin list in step.

The web console and the LuckPerms group on the PikaMC server each keep
their own list of admins. This module reads the server list and pushes
changes back, so the two never drift apart.

Reading the server list
    LuckPerms stores its data in H2, not SQLite, so the panel's
    sqlite-query endpoint cannot open it. The way out is LuckPerms' own
    export: `lp export` writes a gzipped JSON file into the plugin folder,
    which the panel can then download. That is what this module does.

Writing the server list
    The reverse direction uses the console: `lp user <name> parent add
    admin` and `lp user <name> parent remove admin`. The console output is
    read back to find out whether the command worked, because the panel
    API answers 200 even when the command was rejected.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import re
import time
from typing import Any

import httpx
from fastapi import HTTPException

from .config import (
    ADMIN_GROUP,
    ADMIN_SYNC_SECONDS,
    PIKA_API_KEY,
    PIKA_BASE_URL,
    PIKA_SERVER_UUID,
)
from .pika import send_command

# The file LuckPerms writes when it is told to export. The plugin appends
# ".json.gz" to whatever name it is given, and refuses to overwrite an
# existing file, so the name has to change every time.
EXPORT_STEM = "gacha_admin_sync"
EXPORT_REMOTE_DIR = "/plugins/LuckPerms"


def _export_stem() -> str:
    """The name to hand to `lp export`, without the extension."""
    return f"{EXPORT_STEM}_{int(time.time() * 1000)}"


def _export_remote_path() -> str:
    """The path the export file will have on the server."""
    return f"{EXPORT_REMOTE_DIR}/{_export_stem()}.json.gz"


async def cleanup_exports() -> int:
    """Remove the export files this module left on the server.

    An export file that is never deleted fills the plugin folder with one
    file per sync, so the old ones are cleared out.
    """
    url = f"{PIKA_BASE_URL}/api/client/servers/{_server()}/files/list"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=_headers(),
                                        params={"directory": EXPORT_REMOTE_DIR,
                                                "per_page": 100})
        if response.status_code >= 400:
            return 0
        entries = (response.json().get("entries") or {}).get("data") or []
    except Exception:
        return 0
    stale = [f"{EXPORT_REMOTE_DIR}/{e.get('name')}" for e in entries
             if str(e.get("name") or "").startswith(EXPORT_STEM)]
    if not stale:
        return 0
    delete_url = f"{PIKA_BASE_URL}/api/client/servers/{_server()}/files/delete"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.post(delete_url, headers=_headers(),
                              json={"files": stale})
    except Exception:
        return 0
    return len(stale)

# Minecraft names are short, letters and digits plus a few marks. The rule
# keeps a name from turning into a console command of its own.
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")

# The console prints each member on its own line like "> .kttykem".
_LISTMEMBER_RE = re.compile(r"^\[.*?INFO\]:\s*>\s*(\S+)\s*$", re.M)

# The panel wraps the console output in Minecraft colour codes. They have
# to go before anything is compared.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m|§[0-9a-fk-or]")

# The last good server list and when it was fetched.
_cache: dict[str, Any] = {"at": 0.0, "admins": None, "error": None}


def _headers() -> dict[str, str]:
    if not PIKA_API_KEY:
        raise HTTPException(status_code=503, detail="Chua cau hinh PIKA_API_KEY")
    return {
        "Authorization": f"Bearer {PIKA_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _server() -> str:
    if not PIKA_SERVER_UUID:
        raise HTTPException(status_code=503, detail="Chua cau hinh PIKA_SERVER_UUID")
    return PIKA_SERVER_UUID


def safe_name(name: str) -> str | None:
    """The name when it is safe to put in a console command, else None."""
    trimmed = (name or "").strip()
    if not NAME_RE.fullmatch(trimmed):
        return None
    return trimmed


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


async def _console(command: str) -> None:
    """Run one console command on the server.

    The call goes through `pika.send_command`, so the "the key has no
    console permission" state is kept in one place and the admin console
    shows the truth about it.
    """
    await send_command(command)


async def _logs(lines: int = 400) -> str:
    """The recent console output, without the colour codes."""
    url = f"{PIKA_BASE_URL}/api/client/servers/{_server()}/logs"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=_headers(),
                                        params={"lines": lines})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503,
                            detail=f"Khong doc duoc log server: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=503,
                            detail=f"PikaMC logs HTTP {response.status_code}")
    return _strip_ansi(response.text)


async def _delete_remote(path: str) -> None:
    """Delete one file on the server. A failure here is not important."""
    url = f"{PIKA_BASE_URL}/api/client/servers/{_server()}/files/delete"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.post(url, headers=_headers(),
                              json={"files": [path]})
    except Exception:
        pass


async def _download(path: str) -> bytes:
    """Download one file from the server through a signed link."""
    url = f"{PIKA_BASE_URL}/api/client/servers/{_server()}/files/download"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_headers(),
                                        params={"files": path})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503,
                            detail=f"Khong ket noi duoc server: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=503,
                            detail=f"PikaMC download HTTP {response.status_code}")
    signed = response.json().get("url")
    if not signed:
        raise HTTPException(status_code=503, detail="PikaMC khong tra ve link tai file")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(signed, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503,
                            detail=f"Khong tai duoc file: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=503,
                            detail=f"PikaMC file HTTP {response.status_code}")
    return response.content


async def _export_users() -> dict[str, dict[str, Any]]:
    """The LuckPerms user table, straight from the server.

    This asks LuckPerms to write an export file and downloads it. It takes
    a few seconds, which is why the result is cached.
    """
    # LuckPerms refuses to overwrite an export file, so every call uses a
    # name of its own.
    stem = _export_stem()
    remote_path = f"{EXPORT_REMOTE_DIR}/{stem}.json.gz"
    await _console(f"lp export {stem}")
    # LuckPerms writes the file after a moment. Give it a couple of tries
    # before giving up: a slow disk should not look like a broken server.
    last_error = ""
    for attempt in range(4):
        await asyncio.sleep(1.2 + attempt * 0.8)
        try:
            blob = await _download(remote_path)
        except HTTPException as exc:
            last_error = str(exc.detail)
            continue
        try:
            data = json.loads(gzip.decompress(blob).decode("utf-8"))
        except (OSError, ValueError) as exc:
            last_error = f"Doc file export that bai: {exc}"
            continue
        users = data.get("users") or {}
        out: dict[str, dict[str, Any]] = {}
        for entry in users.values():
            name = (entry or {}).get("username")
            if not name:
                continue
            out[name.lower()] = entry
        # The export file has served its purpose; leaving it behind would
        # fill the plugin folder with one file per sync.
        await _delete_remote(remote_path)
        return out
    raise HTTPException(status_code=503,
                        detail=f"Khong doc duoc danh sach admin tren server: {last_error}")


def _is_admin(entry: dict[str, Any]) -> bool:
    """True when the user inherits the admin group.

    LuckPerms records the inherited groups as `group.<name>` nodes. A user
    whose primary group is `admin` also counts, so that the check works
    even when the inheritance node is missing.
    """
    if (entry.get("primaryGroup") or "").lower() == ADMIN_GROUP.lower():
        return True
    for node in entry.get("nodes") or []:
        if node.get("type") != "inheritance":
            continue
        key = str(node.get("key") or "")
        if key.lower() == f"group.{ADMIN_GROUP.lower()}":
            return True
    return False


def cached_admins() -> list[str]:
    """The last server admin list, without asking the server again.

    Returns an empty list when the list was never fetched. The callers
    that need the real thing call `fetch_server_admins`.
    """
    return list(_cache["admins"] or [])


def cache_is_fresh() -> bool:
    """True when the cached server list is still good."""
    if _cache["admins"] is None:
        return False
    return (time.time() - _cache["at"]) < ADMIN_SYNC_SECONDS


def cache_time() -> float:
    """When the cached server list was fetched, or 0 when there is none."""
    return _cache["at"] if _cache["admins"] is not None else 0.0


async def fetch_server_admins(force: bool = False) -> list[str]:
    """The accounts that hold the admin group on the server.

    The result is cached for a short while: the export takes seconds and
    the list only changes when somebody is promoted.
    """
    if not force and cache_is_fresh():
        return cached_admins()
    try:
        users = await _export_users()
    except HTTPException as exc:
        _cache["error"] = str(exc.detail)
        if _cache["admins"] is not None:
            # A failed refresh keeps the last good list rather than
            # locking every admin out of the console.
            return cached_admins()
        raise
    except Exception as exc:
        _cache["error"] = str(exc)
        if _cache["admins"] is not None:
            return cached_admins()
        raise HTTPException(status_code=503,
                            detail=f"Khong doc duoc danh sach admin tren server: {exc}") from exc
    admins = sorted(name for name, entry in users.items() if _is_admin(entry))
    _cache["at"] = time.time()
    _cache["admins"] = admins
    _cache["error"] = None
    return admins


async def grant_admin(name: str) -> dict[str, Any]:
    """Give one account the admin group on the server."""
    safe = safe_name(name)
    if not safe:
        raise HTTPException(status_code=400,
                            detail="Ten khong hop le cho lenh console.")
    await _console(f"lp user {safe} parent add {ADMIN_GROUP}")
    await asyncio.sleep(1.2)
    text = (await _logs(200)).lower()
    if ("now inherits" not in text and "already inherits" not in text
            and ("does not have a uuid" in text
                 or ("uuid" in text and "not" in text))):
        raise HTTPException(status_code=404,
                            detail=f"Khong tim thay nguoi choi {safe} tren server.")
    _cache["at"] = 0.0
    return {"name": safe, "group": ADMIN_GROUP, "granted": True}


async def revoke_admin(name: str) -> dict[str, Any]:
    """Take the admin group away from one account on the server."""
    safe = safe_name(name)
    if not safe:
        raise HTTPException(status_code=400,
                            detail="Ten khong hop le cho lenh console.")
    await _console(f"lp user {safe} parent remove {ADMIN_GROUP}")
    await asyncio.sleep(1.2)
    _cache["at"] = 0.0
    return {"name": safe, "group": ADMIN_GROUP, "revoked": True}

async def list_group_members(group: str = ADMIN_GROUP) -> list[str]:
    """The accounts in a LuckPerms group, read from the console output.

    The console is the only way to ask LuckPerms for this list, so the
    answer is parsed out of the log. `lp group <g> listmembers` prints one
    member per line.
    """
    safe = safe_name(group) or ADMIN_GROUP
    await _console(f"lp group {safe} listmembers")
    await asyncio.sleep(1.5)
    text = await _logs(300)
    members: list[str] = []
    for line in text.splitlines():
        match = _LISTMEMBER_RE.match(line.strip())
        if match:
            name = match.group(1)
            if name.lower() not in {"page", "none"}:
                members.append(name)
    return members
