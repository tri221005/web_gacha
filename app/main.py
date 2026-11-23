from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyodbc
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import bots, game, luckperms, store
from .config import (
    ADMIN_GROUP,
    ADMIN_PASSWORD,
    ADMIN_USERS,
    PIKA_SERVER_UUID,
    SESSION_HTTPS_ONLY,
    SESSION_SECRET,
    pika_ready,
)
from .gacha import (
    case_view_full as gacha_case_view,
)
from .gacha import (
    delete_case as gacha_delete_case,
)
from .gacha import (
    get_case,
    give_command,
    is_dry_run,
    load_cases,
    pull_cost,
    take_command,
)
from .gacha import (
    load_config as gacha_load_config,
)
from .gacha import (
    upsert_case as gacha_upsert_case,
)
from .pika import (
    coin_amount,
    console_available,
    economy_balance,
    find_authme_user,
    find_economy_user,
    get_server,
    list_servers,
    send_command,
)
from .security import (
    client_ip,
    login_allowed,
    new_csrf_token,
    record_failed_login,
    verify_authme_sha256,
)
from .session import AdaptiveSessionMiddleware

VN_TZ = timezone(timedelta(hours=7))
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
KIND_LABELS = {
    "seed": "Nạp ví",
    "sync": "Đồng bộ PikaMC",
    "open": "Mở rương",
    "sell": "Bán đồ",
    "battle_pay": "Vào battle",
    "refund": "Hoàn Coin",
    "bonus": "Bonus ngày",
    "admin": "Admin điều chỉnh",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init()
    bots.start(app)
    # Clear the export files a previous run left on the server. They are
    # only ever a few kilobytes each, but they would pile up.
    try:
        await luckperms.cleanup_exports()
    except Exception:
        pass
    yield
    task = getattr(app.state, "bot_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="JellyVale Gacha", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    AdaptiveSessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="jv_session",
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY,
    max_age=60 * 60 * 12,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

if SESSION_SECRET == "dev-only-change-me":
    # A known secret means anybody can forge a session cookie and log in
    # as any player.
    logging.getLogger(__name__).warning(
        "SESSION_SECRET is still the default value. Set it in .env before "
        "putting this site online, or anybody can forge a session cookie."
    )


def format_coin(value: float | str | None) -> str:
    try:
        amount = 0.0 if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        amount = 0.0
    if amount.is_integer():
        return f"{int(amount):,}".replace(",", ".")
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_last_seen(ms: float | str | None) -> str:
    try:
        stamp = float(ms) if ms not in (None, "") else 0
    except (TypeError, ValueError):
        stamp = 0
    if stamp <= 0:
        return "Chưa có"
    if stamp > 10_000_000_000:
        stamp = stamp / 1000
    dt = datetime.fromtimestamp(stamp, tz=VN_TZ)
    return dt.strftime("%d/%m/%Y %H:%M")


def is_admin(name: str | None) -> bool:
    """True when the account may use the admin console.

    The list is the union of three sources: the accounts in `.env`, the
    accounts the admin console added by hand, and the accounts that hold
    the admin group on the Minecraft server. The server list is cached for
    a short while, so this stays cheap on the request path.
    """
    if not name:
        return False
    key = name.strip().lower()
    if not key:
        return False
    if key in ADMIN_USERS:
        return True
    return key in admin_names()


def admin_names() -> set[str]:
    """Every account that may use the admin console, lower-cased."""
    names = set(ADMIN_USERS)
    try:
        names.update(store.list_admins())
    except Exception:
        # The ledger may not be reachable yet; the .env list still works.
        pass
    names.update(_server_admin_names())
    return names


def _server_admin_names() -> set[str]:
    """The admin accounts on the Minecraft server, from the cached list."""
    return set(luckperms.cached_admins())


async def _refresh_server_admins() -> None:
    """Pull the server admin list when the cached one has gone stale.

    A failure here is not fatal: the local list keeps working, so the
    console does not lock everybody out when the server cannot be reached.
    """
    if luckperms.cache_is_fresh():
        return
    try:
        await luckperms.fetch_server_admins()
    except HTTPException:
        pass


def require_admin(request: Request) -> str | JSONResponse:
    """The admin name, or a 403 for everybody else.

    Every admin route goes through this, so a new route cannot forget the
    check. The CSRF token is required as well for the routes that change
    money or data.
    """
    user = request.session.get("user")
    if not user:
        return JSONResponse({"detail": "Chưa đăng nhập."}, status_code=401)
    if not is_admin(user):
        return JSONResponse({"detail": "Không có quyền quản trị."}, status_code=403)
    return user


def admin_auth(request: Request, csrf: bool = False) -> str | JSONResponse:
    """Admin check plus the optional CSRF check."""
    user = require_admin(request)
    if isinstance(user, JSONResponse):
        return user
    if csrf and not require_csrf(request):
        return JSONResponse({"detail": "Phiên hết hạn, tải lại trang."},
                            status_code=403)
    return user


def require_login(request: Request) -> tuple[str, str] | RedirectResponse:
    user = request.session.get("user")
    login_name = request.session.get("login_name")
    if not user or not login_name:
        return RedirectResponse("/login", status_code=303)
    return user, login_name


def render(request: Request, name: str, **context) -> HTMLResponse:
    context.setdefault("is_admin", is_admin(request.session.get("user")))
    context.setdefault("dry_run", is_dry_run())
    context.setdefault("console_broken", not console_available())
    token = request.session.get("csrf") or new_csrf_token()
    request.session["csrf"] = token
    context.setdefault("csrf", token)
    context.setdefault("player", None)
    return templates.TemplateResponse(request, name, context)


def json_error(exc: game.GameError | Exception, status: int = 400) -> JSONResponse:
    if isinstance(exc, game.GameError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)
    return JSONResponse({"detail": str(exc)}, status_code=status)


def as_int(value, default: int = 0) -> int:
    """Read an integer from a JSON body without raising.

    A request body is untrusted input: `{"ids": ["abc"]}` must not turn
    into a 500 error.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_str(value, default: str = "") -> str:
    if isinstance(value, str):
        return value
    return default


def as_id_list(value) -> list[int]:
    """Read a list of item ids from a JSON body without raising."""
    if not isinstance(value, (list, tuple)):
        return []
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


async def read_json(request: Request) -> dict:
    """Read a JSON object body, or an empty dict when it is not one."""
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def case_view(case) -> dict:
    total = sum(max(0, item.weight) for item in case.items) or 1
    return {
        "id": case.id,
        "name": case.name,
        "description": case.description,
        "image": case.image,
        "glow": case.glow,
        "pull_cost": case.pull_cost,
        "cost_fmt": format_coin(case.pull_cost),
        "loot": [
            {
                **item.as_public(),
                "weight": round(100 * item.weight / total, 2),
                "coin_fmt": format_coin(item.coin),
            }
            for item in case.items
        ],
    }


def inv_view(row: dict) -> dict:
    out = dict(row)
    out["value_fmt"] = format_coin(row["value"])
    return out


def battle_view(battle: dict) -> dict:
    case = get_case(battle["case_id"])
    price = case.pull_cost * int(battle["rounds"]) if case else 0
    seated = battle.get("seated") or len(battle.get("players") or [])
    out = dict(battle)
    out["case_name"] = case.name if case else battle["case_id"]
    out["case_image"] = case.image if case else ""
    out["price"] = price
    out["price_fmt"] = format_coin(price)
    out["seated"] = seated
    out["slots"] = int(battle["slots"])
    out["mode_label"] = "Crazy" if battle["mode"] == "CRAZY" else "Standard"
    out["full"] = seated >= int(battle["slots"])
    out["pool"] = [item.as_public() for item in case.items] if case else []
    # What a player has to pay to sit down. When a bot hosts the room,
    # the bot seat was never paid for on the Minecraft server, so the
    # player pays for it as well.
    bot_due = game.unpaid_bot_seats(battle, "") if battle else 0
    out["bot_due"] = bot_due
    out["join_price"] = price + bot_due
    out["join_price_fmt"] = format_coin(price + bot_due)
    for player in out.get("players") or []:
        player["total_fmt"] = format_coin(player.get("total") or 0)
    for drop in out.get("drops") or []:
        drop["value_fmt"] = format_coin(drop.get("value") or 0)
    return out


GUEST = {
    "player": None,
    "user": None,
    "login_name": None,
    "eco": None,
    "pika": 0,
    "pika_fmt": "0",
    "money": 0,
    "money_fmt": None,
    "held": 0,
    "last_seen": "Chưa có",
}


async def optional_ctx(request: Request) -> dict:
    if not request.session.get("user"):
        return dict(GUEST)
    ctx = await player_ctx(request)
    if isinstance(ctx, RedirectResponse):
        return dict(GUEST)
    return ctx


async def player_ctx(request: Request):
    auth = require_login(request)
    if isinstance(auth, RedirectResponse):
        return auth
    user, login_name = auth
    eco = None
    try:
        eco = await find_economy_user(login_name)
    except HTTPException:
        eco = None
    player = (eco or {}).get("name") or user
    pika = coin_amount(eco)
    # The server is the source of truth: mirror the live PikaMC balance into
    # the local ledger so the web wallet always matches the server.
    if not is_dry_run() and eco is not None:
        game.sync_wallet(player, pika)
    else:
        game.seed_wallet(player, pika_coin=pika)
    money = game.balance(player)
    return {
        "user": user,
        "login_name": login_name,
        "player": player,
        "eco": eco,
        "pika": pika,
        "pika_fmt": format_coin(pika),
        "money": money,
        "money_fmt": format_coin(money),
        "held": len(store.list_inventory(player, "held")),
        "last_seen": format_last_seen((eco or {}).get("last_seen")),
    }


def require_csrf(request: Request) -> bool:
    """Compare the header with the session token.

    Both must exist: without the check, a session that has no token yet
    would compare None with None and pass every request.
    """
    sent = request.headers.get("x-csrf")
    expected = request.session.get("csrf")
    if not sent or not expected:
        return False
    return hmac.compare_digest(str(sent), str(expected))


def api_auth(request: Request, *, csrf: bool = False) -> str | JSONResponse:
    user = request.session.get("user")
    if not user:
        return JSONResponse({"detail": "Chưa đăng nhập."}, status_code=401)
    if csrf and not require_csrf(request):
        return JSONResponse({"detail": "Phiên hết hạn, tải lại trang."}, status_code=403)
    # Every gameplay action goes through this one function, so this is the
    # only place a ban has to be checked. The ban is stored by the wallet
    # name, which can be the real name or the login name.
    if store.is_banned(user) or (
        request.session.get("login_name")
        and store.is_banned(request.session["login_name"])
    ):
        return JSONResponse({"detail": "Tài khoản của bạn đã bị admin cấm."},
                            status_code=403)
    return user


async def pika_take(player: str, amount: int, kind: str = "sync") -> int:
    """Take Coin on the server, then mirror the new balance into the ledger.

    ExcellentEconomy flushes its SQLite file asynchronously, so the balance
    read straight after the console command can still be the old value. We
    poll until the server reports the expected amount, then mirror it.

    The console answers HTTP 200 even when the command itself failed (the
    player does not exist, the balance is too low). We therefore compare the
    balance before and after: if the money did not actually leave the
    server, the payment failed and the caller must not hand out anything.

    When the balance cannot be read at all, we do not guess. The command
    may or may not have run, so we report the payment as failed and leave
    the refund to the caller. Claiming success would hand out a free item.
    """
    if amount <= 0:
        return await pika_resync(player)
    before = await pika_balance(player)
    await send_command(_console_command(take_command, player, amount))
    expected = None if before is None else max(0.0, before - amount)
    live = await pika_read_balance(player, expected)
    if live is None:
        raise HTTPException(
            status_code=503,
            detail="Khong doc duoc so du tren server. Vui long thu lai.",
        )
    if before is not None and live > before - amount + 1:
        raise HTTPException(
            status_code=503,
            detail="Server chưa trừ Coin. Giao dịch đã được hoàn tác.",
        )
    return game.sync_wallet(player, live, kind=kind)


def _console_command(builder, player: str, amount: int) -> str:
    """Build a console command, refusing names that could split it.

    A name with a space or a `;` would turn one command into two.
    """
    try:
        return builder(player, amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def pika_give(player: str, amount: int, kind: str = "sync") -> int:
    """Give Coin on the server, then mirror the new balance into the ledger."""
    if amount <= 0:
        return await pika_resync(player)
    before = await pika_balance(player)
    await send_command(_console_command(give_command, player, amount))
    expected = None if before is None else before + amount
    live = await pika_read_balance(player, expected)
    if live is None:
        raise HTTPException(
            status_code=503,
            detail="Khong doc duoc so du tren server. Vui long thu lai.",
        )
    if before is not None and live < before + amount - 1:
        raise HTTPException(
            status_code=503,
            detail="Server chưa cộng Coin. Giao dịch đã được hoàn tác.",
        )
    return game.sync_wallet(player, live, kind=kind)


async def pika_balance(player: str) -> float | None:
    """Live ExcellentEconomy balance for a player.

    Returns None when the server cannot be reached. A network failure must
    not look like a crash: the caller decides what an unknown balance means.
    """
    try:
        return await economy_balance(player)
    except HTTPException:
        return None
    except Exception:
        return None


async def refresh_balance(player: str, kind: str = "sync") -> int:
    """Pull the live server balance into the ledger before spending."""
    if is_dry_run():
        return game.balance(player)
    live = await pika_balance(player)
    if live is None:
        return game.balance(player)
    return game.sync_wallet(player, live, kind=kind)


async def pika_read_balance(player: str, expected: float | None = None,
                            tries: int = 6, delay: float = 0.7) -> float | None:
    """Read the live balance, waiting until the server agrees.

    Returns None when the balance could not be read at all. The caller must
    treat that as "unknown", not as "unchanged": a payment may still have
    gone through on the server.
    """
    live = await pika_balance(player)
    for _ in range(max(0, tries - 1)):
        if live is not None and (expected is None or abs(live - expected) <= 1.0):
            break
        await asyncio.sleep(delay)
        live = await pika_balance(player)
    return live


async def pika_resync(player: str, expected: float | None = None,
                     tries: int = 6, delay: float = 0.7,
                     kind: str = "sync") -> int:
    """Read the live balance back and store it as the wallet balance.

    When `expected` is given, keep polling until the server agrees (the
    economy plugin writes its database on a timer, not on every command).
    """
    live = await pika_read_balance(player, expected, tries=tries, delay=delay)
    if live is None:
        return game.balance(player)
    return game.sync_wallet(player, live, kind=kind)


@app.exception_handler(pyodbc.Error)
async def database_error_handler(request: Request, exc: pyodbc.Error):
    """Turn a database failure into a 503 instead of a 500.

    A 500 makes the hosting platform think the container is broken and
    restart it. A 503 says "come back later", which is what a database
    that is down really means.
    """
    logging.getLogger(__name__).error("Loi SQL Server: %s", exc)
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            {"detail": "Cơ sở dữ liệu đang bận. Vui lòng thử lại sau."},
            status_code=503,
        )
    return JSONResponse(
        {"detail": "Cơ sở dữ liệu đang bận. Vui lòng thử lại sau."},
        status_code=503,
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return RedirectResponse("/gacha", status_code=303)


@app.get("/health")
async def health():
    """Liveness probe for the hosting platform.

    It also reports whether the SQL Server ledger is reachable, because a
    web container that starts but cannot reach the database is not really
    up. The status is 200 either way so the platform does not kill a
    container during a short database outage; the body says what broke.
    """
    db_ok = True
    db_error = ""
    try:
        store.run(lambda con: con.cursor().execute("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - the probe must never crash
        db_ok = False
        db_error = str(exc)[:300]
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "database_error": db_error,
        "pika": "ready" if pika_ready() else "not_configured",
    }


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    if request.session.get("user"):
        return RedirectResponse("/gacha", status_code=303)
    token = new_csrf_token()
    request.session["csrf"] = token
    return render(request, "login.html", csrf=token, error=error, pika_ready=pika_ready())


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf: str = Form(...),
):
    if not pika_ready():
        return RedirectResponse("/login?error=setup", status_code=303)
    ip = client_ip(request)
    expected_csrf = request.session.get("csrf")
    if not csrf or not expected_csrf or not hmac.compare_digest(csrf, str(expected_csrf)):
        return RedirectResponse("/login?error=phien", status_code=303)
    username = username.strip()
    if not login_allowed(ip, username):
        return RedirectResponse("/login?error=rate", status_code=303)
    if not username or not password:
        record_failed_login(ip, username)
        return RedirectResponse("/login?error=sai", status_code=303)
    try:
        row = await find_authme_user(username)
    except HTTPException:
        return RedirectResponse("/login?error=pika", status_code=303)
    stored = (row or {}).get("password")
    if row is None or not verify_authme_sha256(password, str(stored or "")):
        record_failed_login(ip, username)
        return RedirectResponse("/login?error=sai", status_code=303)
    request.session.clear()
    request.session["user"] = row.get("realname") or row.get("username")
    request.session["login_name"] = row.get("username")
    # The token must exist right away: without it the CSRF check compares
    # None with None and lets every POST through.
    request.session["csrf"] = new_csrf_token()
    return RedirectResponse("/gacha", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/gacha", status_code=303)


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, error: str | None = None):
    """The admin sign-in page.

    The console is separate from the game login: the admin password lives
    in `.env` and never touches the Minecraft account. When
    `ADMIN_PASSWORD` is empty the page falls back to the normal game
    login, because the admin account is then only recognised by its
    name.
    """
    if is_admin(request.session.get("user")):
        return RedirectResponse("/admin", status_code=303)
    token = new_csrf_token()
    request.session["csrf"] = token
    return render(
        request,
        "admin_login.html",
        csrf=token,
        error=error,
        password_set=bool(ADMIN_PASSWORD),
    )


@app.post("/admin/login")
async def admin_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf: str = Form(...),
):
    ip = client_ip(request)
    expected_csrf = request.session.get("csrf")
    if not csrf or not expected_csrf or not hmac.compare_digest(csrf, str(expected_csrf)):
        return RedirectResponse("/admin/login?error=phien", status_code=303)
    username = username.strip()
    if not username or not password:
        record_failed_login(ip, f"admin:{username}")
        return RedirectResponse("/admin/login?error=sai", status_code=303)
    if not login_allowed(ip, f"admin:{username}"):
        return RedirectResponse("/admin/login?error=rate", status_code=303)
    # The admin list has to be current: an account that was made an admin
    # on the server has to be able to sign in here straight away.
    await _refresh_server_admins()
    if not is_admin(username):
        record_failed_login(ip, f"admin:{username}")
        return RedirectResponse("/admin/login?error=sai", status_code=303)
    if ADMIN_PASSWORD:
        # Compare in constant time so the response time cannot be used to
        # guess the password one character at a time.
        if not hmac.compare_digest(password, ADMIN_PASSWORD):
            record_failed_login(ip, f"admin:{username}")
            return RedirectResponse("/admin/login?error=sai", status_code=303)
    else:
        # No separate admin password: fall back to the Minecraft password,
        # so the name alone is never enough to get in.
        try:
            row = await find_authme_user(username)
        except HTTPException:
            return RedirectResponse("/admin/login?error=pika", status_code=303)
        stored = (row or {}).get("password")
        if row is None or not verify_authme_sha256(password, str(stored or "")):
            record_failed_login(ip, f"admin:{username}")
            return RedirectResponse("/admin/login?error=sai", status_code=303)
    request.session.clear()
    request.session["user"] = username
    request.session["login_name"] = username
    request.session["admin"] = True
    request.session["csrf"] = new_csrf_token()
    store.log_admin("login", username, "", admin=username)
    return RedirectResponse("/admin", status_code=303)


@app.get("/gacha", response_class=HTMLResponse)
async def catalogue(request: Request):
    ctx = await optional_ctx(request)
    last_bonus = store.last_bonus(ctx["player"]) if ctx["player"] else 0
    bonus_ready = bool(ctx["player"]) and ((not last_bonus) or (store.now() - last_bonus >= 24 * 3600))
    return render(
        request,
        "catalogue.html",
        **ctx,
        cases=[case_view(item) for item in load_cases()],
        site=game.site_stats_bar(),
        bonus_ready=bonus_ready,
    )


@app.get("/case/{slug}", response_class=HTMLResponse)
async def case_page(request: Request, slug: str):
    ctx = await optional_ctx(request)
    case = get_case(slug)
    if not case:
        return RedirectResponse("/gacha", status_code=303)
    view = case_view(case)
    return render(
        request,
        "case.html",
        **ctx,
        case=view,
        pool_json=json.dumps([item.as_public() for item in case.items], ensure_ascii=False),
    )


@app.post("/api/case/{slug}/open")
async def open_case(request: Request, slug: str):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    count = 1
    body = await read_json(request)
    case = get_case(slug)
    if not case:
        return JSONResponse({"detail": "Không có rương này."}, status_code=404)
    try:
        if "count" in body:
            try:
                count = int(body["count"])
            except (TypeError, ValueError) as exc:
                raise game.GameError("Số lần mở phải là số nguyên.") from exc
        # Check the count before charging: a wrong count must never touch
        # the player's Coin, even briefly.
        if count not in (1, 2, 3, 4, 5):
            raise game.GameError("Số lượng mở không hợp lệ (1-5).")
        await refresh_balance(user)
        cost = case.pull_cost * count
        if store.get_balance(user) < cost:
            raise game.GameError(f"Không đủ Coin. Cần {cost:,} Coin.")
        if is_dry_run():
            batch = game.open_case_batch(user, slug, count=count)
            balance = batch.balance
        else:
            # Charge the server first: a drop must never be handed out
            # for free when the payment was refused. `pika_take` also
            # mirrors the new server balance into the ledger, so the
            # local roll must not debit the wallet a second time.
            try:
                await pika_take(user, cost, kind="open")
            except HTTPException as exc:
                # The payment failed: nothing is handed out.
                return JSONResponse({"detail": str(exc.detail)},
                                    status_code=exc.status_code or 503)
            try:
                batch = game.open_case_batch(user, slug, count=count, charge=False)
            except game.GameError:
                # The roll could not be made: give the Coin back.
                try:
                    await pika_give(user, cost, kind="refund")
                except HTTPException:
                    pass
                raise
            balance = await pika_resync(user, kind="open")
        openings_resp = []
        for op in batch.openings:
            openings_resp.append({
                "winner": op["winner"],
                "inventory_id": op["inventory_id"],
                "winner_coin": op["winner_coin"],
                "winner_coin_fmt": format_coin(op["winner_coin"]),
            })
        first = openings_resp[0]
        return {
            "winner": first["winner"],
            "inventory_id": first["inventory_id"],
            "winner_coin_fmt": first["winner_coin_fmt"],
            "openings": openings_resp,
            "count": count,
            "total_cost": batch.total_cost,
            "total_cost_fmt": format_coin(batch.total_cost),
            "pool": batch.pool,
            "dry_run": batch.dry_run,
            "balance_fmt": format_coin(balance),
            "balance": balance,
        }
    except game.GameError as exc:
        return json_error(exc)


@app.get("/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request):
    ctx = await player_ctx(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    held = [inv_view(row) for row in store.list_inventory(ctx["player"], "held")]
    worth = sum(row["value"] for row in held)
    return render(
        request,
        "inventory.html",
        **ctx,
        items=held,
        worth_fmt=format_coin(worth),
    )


@app.get("/api/inventory")
async def inventory_live(request: Request):
    """The player's bag as JSON, so the page can refresh itself.

    Items can arrive while the page is open, for example when a battle
    the player won finishes. Polling this keeps the bag right.
    """
    user = api_auth(request)
    if isinstance(user, JSONResponse):
        return user
    held = [inv_view(row) for row in store.list_inventory(user, "held")]
    return {
        "items": held,
        "count": len(held),
        "worth": sum(row["value"] for row in held),
        "worth_fmt": format_coin(sum(row["value"] for row in held)),
    }


@app.post("/api/inventory/sell")
async def inventory_sell(request: Request):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    body = await read_json(request)
    ids = as_id_list(body.get("ids"))
    try:
        if is_dry_run():
            result = game.sell_items(user, ids)
            balance = result["balance"]
        else:
            # Pay out on the server first; only commit locally afterwards.
            pending = game.sell_items(user, ids, commit=False)
            try:
                balance = await pika_give(user, pending["amount"], kind="sell")
            except HTTPException as exc:
                game.revert_sale(ids)
                return JSONResponse({"detail": str(exc.detail)}, status_code=503)
            game.commit_sale(user, ids, pending["amount"])
            result = {**pending, "balance": balance}
        return {
            **result,
            "amount_fmt": format_coin(result["amount"]),
            "balance_fmt": format_coin(balance),
        }
    except game.GameError as exc:
        return json_error(exc)


@app.post("/api/inventory/sell-all")
async def inventory_sell_all(request: Request):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        if is_dry_run():
            result = game.sell_all(user)
            balance = result["balance"]
        else:
            ids = [row["id"] for row in store.list_inventory(user, "held")]
            pending = game.sell_all(user, commit=False)
            try:
                balance = await pika_give(user, pending["amount"])
            except HTTPException:
                game.revert_sale(ids)
                balance = pending["balance"]
            else:
                game.commit_sale(user, ids, pending["amount"])
            result = {**pending, "balance": balance}
        return {
            **result,
            "amount_fmt": format_coin(result["amount"]),
            "balance_fmt": format_coin(balance),
        }
    except game.GameError as exc:
        return json_error(exc)


@app.get("/upgrade", response_class=HTMLResponse)
async def upgrade_page(request: Request):
    ctx = await player_ctx(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    held = [inv_view(row) for row in store.list_inventory(ctx["player"], "held")]
    return render(request, "upgrade.html", **ctx, items=held)


@app.get("/api/upgrade/targets")
async def upgrade_targets(request: Request, value: int = 0):
    user = api_auth(request)
    if isinstance(user, JSONResponse):
        return user
    targets = game.upgrade_targets(value)
    for row in targets:
        row["coin_fmt"] = format_coin(row["coin"])
    return {"targets": targets}


@app.post("/api/upgrade")
async def upgrade_run(request: Request):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    body = await read_json(request)
    try:
        result = game.do_upgrade(
            user,
            as_int(body.get("inventory_id"), 0),
            as_str(body.get("target_id")),
            as_int(body.get("target_coin"), 0),
        )
        result["balance_fmt"] = format_coin(result["balance"])
        result["target"]["coin_fmt"] = format_coin(result["target"]["coin"])
        return result
    except game.GameError as exc:
        return json_error(exc)


@app.get("/battles", response_class=HTMLResponse)
async def battles_page(request: Request):
    ctx = await optional_ctx(request)
    lobby = store.list_battles()
    return render(
        request,
        "battles.html",
        **ctx,
        cases=[case_view(item) for item in load_cases()],
        open_battles=[battle_view(row) for row in lobby["open"]],
        finished=[battle_view(row) for row in lobby["finished"]],
    )


@app.get("/battles/{battle_id}", response_class=HTMLResponse)
async def battle_page(request: Request, battle_id: int):
    ctx = await optional_ctx(request)
    battle = store.get_battle(battle_id)
    if not battle:
        return RedirectResponse("/battles", status_code=303)
    return render(
        request,
        "battle.html",
        **ctx,
        battle=battle_view(battle),
        battle_json=json.dumps(battle_view(battle), ensure_ascii=False),
    )


@app.get("/api/battles/lobby")
async def battles_lobby(request: Request):
    """The battle lobby as JSON, so the page can refresh itself.

    The lobby is the one place where new rooms appear without the player
    doing anything, because the bots open rooms on their own. Polling it
    means a room shows up as soon as it is created.
    """
    lobby = store.list_battles()
    return {
        "open": [battle_view(row) for row in lobby["open"]],
        "finished": [battle_view(row) for row in lobby["finished"]],
    }


@app.post("/api/battles")
async def battles_create(request: Request):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    body = await read_json(request)
    battle = None
    try:
        await refresh_balance(user)
        balance_before = store.get_balance(user)
        battle = game.create_battle(
            user,
            as_str(body.get("case_id")),
            as_int(body.get("slots"), 2),
            as_int(body.get("rounds"), 1),
            as_str(body.get("mode"), "STANDARD"),
        )
        bots_before = 0
        if body.get("fill_bots"):
            battle = game.fill_bots(battle["id"])
            bots_before = game.bot_seat_count(battle, user)
        case = get_case(battle["case_id"])
        seat = (case.pull_cost * as_int(battle["rounds"], 1)) if case else 0
        # A bot seat costs the server nothing but can win items the host
        # sells for real money, so the host pays for every bot it calls.
        paid = seat * (1 + bots_before)
        # What the ledger really lost. It is not the same as `paid`: the
        # bots paid from their own wallets, so only the host's own seat
        # came out of the host's balance. This is the amount that has to
        # come back if the server refuses the payment.
        ledger_spent = max(0, balance_before - store.get_balance(user))
        if not is_dry_run():
            try:
                await pika_take(user, paid, kind="battle_pay")
            except HTTPException as exc:
                # The server refused the payment: the seat must not stay in
                # the lobby and the local debit must be undone. Only what
                # the ledger really lost is given back — the bot seats
                # were never charged to the host's balance.
                game.cancel_battle(battle["id"], user, paid,
                                   refunded=ledger_spent)
                return JSONResponse({"detail": str(exc.detail)},
                                    status_code=exc.status_code or 503)
        return battle_view(battle)
    except game.GameError as exc:
        return json_error(exc)


@app.post("/api/battles/{battle_id}/join")
async def battles_join(request: Request, battle_id: int):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        await refresh_balance(user)
        before = store.get_battle(battle_id)
        if not before:
            raise game.GameError("Trận này không tồn tại.", 404)
        battle = game.join_existing_battle(user, battle_id)
        if not is_dry_run():
            case = get_case(battle["case_id"])
            paid = (case.pull_cost * as_int(battle["rounds"], 1)) if case else 0
            # A bot seat in a room the bot hosts was never paid for on the
            # server: the bot paid from its own fake local wallet. The
            # player who joins that room takes the bot's drops as well
            # when they win, so they pay for the bot seat too. Without
            # this, joining a bot's room is free money whenever the case
            # pays out more than it costs.
            bot_due = game.unpaid_bot_seats(before, user)
            total = paid + bot_due
            # The seat was already taken and `paid` already left the
            # ledger, so the balance still has to cover the bot seat.
            if store.get_balance(user) < bot_due:
                game.leave_battle(battle_id, user, paid)
                raise game.GameError(
                    f"Không đủ Coin. Cần thêm {bot_due:,} Coin cho ghế bot.")
            try:
                await pika_take(user, total, kind="battle_pay")
            except HTTPException as exc:
                # Give the seat back and return the Coin.
                game.leave_battle(battle_id, user, paid)
                if bot_due:
                    store.credit(user, bot_due, "refund", "ghế bot chưa thanh toán")
                return JSONResponse({"detail": str(exc.detail)}, status_code=503)
        return battle_view(battle)
    except game.GameError as exc:
        return json_error(exc)


@app.post("/api/battles/{battle_id}/bots")
async def battles_bots(request: Request, battle_id: int):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        battle = store.get_battle(battle_id)
        if not battle:
            raise game.GameError("Không có trận này.", 404)
        # Only the host may fill its own battle with bots.
        if battle["host"] != user and not is_admin(user):
            raise game.GameError("Chỉ chủ phòng mới được gọi bot.", 403)
        bots_before = game.bot_seat_count(battle, battle["host"])
        battle = game.fill_bots(battle_id)
        bots_after = game.bot_seat_count(battle, battle["host"])
        added = bots_after - bots_before
        if added > 0 and not is_dry_run():
            # A bot seat costs the server nothing, but it can win items the
            # host sells for real money. The host pays for the bots it
            # calls, exactly like a second player would.
            case = get_case(battle["case_id"])
            seat = (case.pull_cost * as_int(battle["rounds"], 1)) if case else 0
            due = seat * added
            try:
                await pika_take(user, due, kind="battle_pay")
            except HTTPException as exc:
                # The server refused: take the bots back out.
                game.remove_bots(battle_id, added)
                return JSONResponse({"detail": str(exc.detail)},
                                    status_code=exc.status_code or 503)
        return battle_view(battle)
    except game.GameError as exc:
        return json_error(exc)


@app.post("/api/battles/{battle_id}/start")
async def battles_start(request: Request, battle_id: int):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        return battle_view(game.start_battle(battle_id, user))
    except game.GameError as exc:
        return json_error(exc)


@app.get("/api/battles/{battle_id}")
async def battles_get(request: Request, battle_id: int):
    battle = store.get_battle(battle_id)
    if not battle:
        return JSONResponse({"detail": "Không có trận này."}, status_code=404)
    return battle_view(battle)


@app.get("/api/drops")
async def api_drops(request: Request):
    """The live drop strip.

    The player names are only shown to logged-in players; a guest sees the
    items without learning who won them.
    """
    logged_in = bool(request.session.get("user"))
    drops = store.recent_drops(30)
    for row in drops:
        row["value_fmt"] = format_coin(row["value"])
        if not logged_in:
            row["player"] = ""
    best = max(drops, key=lambda row: row["value"]) if drops else None
    return {"drops": drops, "best": best}


@app.get("/bonus", response_class=HTMLResponse)
async def bonus_page(request: Request):
    ctx = await optional_ctx(request)
    last_bonus = store.last_bonus(ctx["player"]) if ctx["player"] else 0
    bonus_ready = bool(ctx["player"]) and ((not last_bonus) or (store.now() - last_bonus >= 24 * 3600))
    slices = [{"amount": amount, "weight": weight} for amount, weight in game.BONUS_SLICES]
    return render(
        request,
        "bonus.html",
        **ctx,
        bonus_ready=bonus_ready,
        slices_json=json.dumps(slices),
    )


@app.post("/api/bonus")
async def api_bonus(request: Request):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        result = game.claim_bonus(user)
        if not is_dry_run():
            try:
                balance = await pika_give(user, result["amount"], kind="bonus")
            except HTTPException:
                balance = result["balance"]
        else:
            balance = result["balance"]
        return {
            **result,
            "amount_fmt": format_coin(result["amount"]),
            "balance_fmt": format_coin(balance),
        }
    except game.GameError as exc:
        return json_error(exc)


@app.get("/api/wallet/balance")
async def wallet_balance(request: Request):
    """The balance straight from the local ledger.

    This is the cheap version of `/api/wallet/live`: it only reads the
    local database and never talks to the Minecraft server. The header
    polls it, so it has to stay cheap, because it runs on every page.
    """
    user = api_auth(request)
    if isinstance(user, JSONResponse):
        return user
    balance = game.balance(user)
    return {
        "balance": balance,
        "balance_fmt": format_coin(balance),
        "held": len(store.list_inventory(user, "held")),
    }


# The live wallet answer is kept for a short while. Reading it means
# asking the Minecraft server, and the page polls it, so without a cache
# every player would hit the server every few seconds.
_wallet_cache: dict[str, tuple[float, dict]] = {}
WALLET_CACHE_SECONDS = 10.0


@app.get("/api/wallet/live")
async def wallet_live(request: Request, refresh: bool = False):
    """Live balance straight from PikaMC, mirrored into the local ledger.

    The answer is cached for a few seconds, because the page polls it and
    every poll would otherwise ask the Minecraft server. The refresh
    button passes `refresh=1` to skip the cache, so pressing it really
    does pull the balance again.
    """
    user = api_auth(request)
    if isinstance(user, JSONResponse):
        return user
    login_name = request.session.get("login_name") or user

    cached = _wallet_cache.get(login_name)
    now_ts = time.time()
    if cached and not refresh and now_ts - cached[0] < WALLET_CACHE_SECONDS:
        return cached[1]

    try:
        eco = await find_economy_user(login_name)
    except HTTPException:
        eco = None
    player = (eco or {}).get("name") or user
    pika = coin_amount(eco)
    if not is_dry_run() and eco is not None:
        balance = game.sync_wallet(player, pika)
    else:
        balance = game.balance(player)
    answer = {
        "player": player,
        "balance": balance,
        "balance_fmt": format_coin(balance),
        "pika": pika,
        "pika_fmt": format_coin(pika),
        "last_seen": format_last_seen((eco or {}).get("last_seen")),
        # How many items the player is holding. The header shows this,
        # and the page is polled so it stays right after a sale.
        "held": len(store.list_inventory(player, "held")),
    }
    _wallet_cache[login_name] = (now_ts, answer)
    # The cache only needs to hold the players who are online. Old
    # entries are dropped so it cannot grow forever.
    if len(_wallet_cache) > 500:
        stale = [key for key, (when, _) in _wallet_cache.items()
                 if now_ts - when > WALLET_CACHE_SECONDS]
        for key in stale:
            _wallet_cache.pop(key, None)
    return answer


@app.get("/vi", response_class=HTMLResponse)
async def wallet(request: Request):
    ctx = await player_ctx(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    txs = store.recent_tx(ctx["player"], 20)
    for row in txs:
        row["when"] = datetime.fromtimestamp(row["created_at"], tz=VN_TZ).strftime("%d/%m %H:%M")
        row["amount_fmt"] = format_coin(row["amount"])
        row["kind_label"] = KIND_LABELS.get(row["kind"], row["kind"])
    return render(request, "wallet.html", **ctx, txs=txs)


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, tab: str = "overview"):
    # Not logged in at all: send the visitor to the admin sign-in page
    # instead of the game login, so the console has its own front door.
    if not request.session.get("user"):
        return RedirectResponse("/admin/login", status_code=303)
    ctx = await player_ctx(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    if not is_admin(ctx["user"]):
        return RedirectResponse("/gacha", status_code=303)
    data = store.stats()
    for row in data["recent"]:
        row["when"] = datetime.fromtimestamp(row["created_at"], tz=VN_TZ).strftime("%d/%m %H:%M")
        row["prize_fmt"] = format_coin(row["prize_coin"])
    for row in data["by_rarity"]:
        row["paid_fmt"] = format_coin(row["paid"])
    for row in data["top"]:
        row["spent_fmt"] = format_coin(row["spent"])
    tabs = ("overview", "players", "cases", "tx", "battles", "admins", "log")
    if tab not in tabs:
        tab = "overview"
    return render(
        request,
        "admin.html",
        **ctx,
        tab=tab,
        tabs=tabs,
        cost=format_coin(pull_cost()),
        stats=data,
        spent=format_coin(data["spent"]),
        paid=format_coin(data["paid"]),
        net=format_coin(data["net"]),
        cases=[gacha_case_view(case) for case in load_cases()],
        bans=store.list_bans(),
        server_group=ADMIN_GROUP,
    )


@app.get("/admin/player/{name}", response_class=HTMLResponse)
async def admin_player_page(request: Request, name: str):
    """One player in full: wallet, pulls, inventory and transactions."""
    if not request.session.get("user"):
        return RedirectResponse("/admin/login", status_code=303)
    ctx = await player_ctx(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    if not is_admin(ctx["user"]):
        return RedirectResponse("/gacha", status_code=303)
    player = name.strip()
    if not player:
        return RedirectResponse("/admin?tab=players", status_code=303)
    txs = store.recent_tx(player, 50)
    for row in txs:
        row["when"] = datetime.fromtimestamp(row["created_at"], tz=VN_TZ).strftime("%d/%m %H:%M")
        row["amount_fmt"] = format_coin(row["amount"])
        row["kind_label"] = KIND_LABELS.get(row["kind"], row["kind"])
    items = store.list_inventory(player, "held")
    for row in items:
        row["value_fmt"] = format_coin(row["value"])
    return render(
        request,
        "admin_player.html",
        **ctx,
        target=player,
        balance=format_coin(store.get_balance(player)),
        held_count=len(items),
        held_worth=format_coin(sum(row["value"] for row in items)),
        items=items,
        txs=txs,
        banned=store.is_banned(player),
    )


# --------------------------------------------------------------------------- #
# Admin API
# --------------------------------------------------------------------------- #
@app.get("/api/admin/overview")
async def admin_overview(request: Request):
    user = require_admin(request)
    if isinstance(user, JSONResponse):
        return user
    data = store.stats()
    for row in data["recent"]:
        row["when"] = datetime.fromtimestamp(row["created_at"], tz=VN_TZ).strftime("%d/%m %H:%M")
        row["prize_fmt"] = format_coin(row["prize_coin"])
    for row in data["by_rarity"]:
        row["paid_fmt"] = format_coin(row["paid"])
    for row in data["top"]:
        row["spent_fmt"] = format_coin(row["spent"])
    return {
        "stats": data,
        "spent": format_coin(data["spent"]),
        "paid": format_coin(data["paid"]),
        "net": format_coin(data["net"]),
        "cost": format_coin(pull_cost()),
    }


@app.get("/api/admin/players")
async def admin_players(request: Request, search: str = "", bots: int = 1):
    user = require_admin(request)
    if isinstance(user, JSONResponse):
        return user
    rows = store.list_wallets(search, include_bots=bool(bots))
    for row in rows:
        row["balance_fmt"] = format_coin(row["balance"])
        row["spent_fmt"] = format_coin(row["spent"])
    return {"players": rows}


@app.post("/api/admin/players/{name}/coin")
async def admin_player_coin(request: Request, name: str):
    """Give or take Coin from a player.

    The change goes to the Minecraft server first, so the wallet on the
    server and the ledger in the database cannot drift apart.
    """
    user = admin_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    player = name.strip()
    if not player:
        return JSONResponse({"detail": "Thiếu tên người chơi."}, status_code=400)
    body = await read_json(request)
    amount = as_int(body.get("amount"), 0)
    if amount <= 0:
        return JSONResponse({"detail": "Số Coin phải lớn hơn 0."},
                            status_code=400)
    if body.get("direction") == "take":
        if store.get_balance(player) < amount:
            return JSONResponse({"detail": "Ví không đủ Coin."}, status_code=400)
        try:
            balance = await pika_take(player, amount, kind="admin")
        except HTTPException as exc:
            return JSONResponse({"detail": str(exc.detail)},
                                status_code=exc.status_code or 503)
    else:
        try:
            balance = await pika_give(player, amount, kind="admin")
        except HTTPException as exc:
            return JSONResponse({"detail": str(exc.detail)},
                                status_code=exc.status_code or 503)
    direction = "take" if body.get("direction") == "take" else "give"
    store.log_admin(
        f"coin_{direction}", player,
        f"{amount} Coin, vi còn {format_coin(balance)}", admin=user,
    )
    return {
        "player": player,
        "balance": balance,
        "balance_fmt": format_coin(balance),
        "message": f"Đã {'lấy' if direction == 'take' else 'cộng'} "
                   f"{format_coin(amount)} Coin cho {player}.",
    }


@app.post("/api/admin/players/{name}/balance")
async def admin_player_balance(request: Request, name: str):
    """Set the wallet balance to an exact number.

    The difference between the target and the live server balance is sent
    to the server, so the wallet on the server ends up at the target too.
    Setting only the local ledger would be undone by the next sync.
    """
    user = admin_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    player = name.strip()
    body = await read_json(request)
    amount = as_int(body.get("balance"), -1)
    if amount < 0:
        return JSONResponse({"detail": "Số dư không hợp lệ."}, status_code=400)
    if is_dry_run():
        balance = game.sync_wallet(player, amount, kind="admin")
        return {
            "player": player,
            "balance": balance,
            "balance_fmt": format_coin(balance),
            "message": f"Đã đặt ví {player} còn {format_coin(balance)} Coin.",
        }
    live = await pika_balance(player)
    if live is None:
        return JSONResponse(
            {"detail": "Không đọc được số dư trên server. Thử lại sau."},
            status_code=503,
        )
    delta = int(amount) - int(live)
    if delta > 0:
        balance = await pika_give(player, delta, kind="admin")
    elif delta < 0:
        if int(live) < -delta:
            return JSONResponse(
                {"detail": "Số dư trên server không đủ để trừ."},
                status_code=400,
            )
        balance = await pika_take(player, -delta, kind="admin")
    else:
        balance = game.sync_wallet(player, live, kind="admin")
    store.log_admin(
        "set_balance", player,
        f"vi = {format_coin(balance)} (truoc {format_coin(live)})", admin=user,
    )
    return {
        "player": player,
        "balance": balance,
        "balance_fmt": format_coin(balance),
        "message": f"Đã đặt ví {player} còn {format_coin(balance)} Coin.",
    }


@app.post("/api/admin/players/{name}/ban")
async def admin_player_ban(request: Request, name: str):
    """Ban or unban a player.

    A banned player can still log in, but every action that costs or wins
    Coin is refused.
    """
    user = admin_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    player = name.strip()
    if not player:
        return JSONResponse({"detail": "Thiếu tên người chơi."}, status_code=400)
    body = await read_json(request)
    if body.get("banned"):
        reason = str(body.get("reason", "")).strip()[:200]
        # An admin must not be able to lock themselves out of the console.
        if player.lower() == user.lower():
            return JSONResponse(
                {"detail": "Không thể cấm chính tài khoản admin đang đăng nhập."},
                status_code=400,
            )
        try:
            store.set_ban(player, reason)
        except RuntimeError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=503)
        store.log_admin("ban", player, reason, admin=user)
        return {"player": player, "banned": True,
                "message": f"Đã cấm {player}."}
    store.lift_ban(player)
    store.log_admin("unban", player, "", admin=user)
    return {"player": player, "banned": False,
            "message": f"Đã gỡ cấm {player}."}


@app.get("/api/admin/cases")
async def admin_cases(request: Request):
    user = require_admin(request)
    if isinstance(user, JSONResponse):
        return user
    return {"cases": [gacha_case_view(case) for case in load_cases()]}


@app.post("/api/admin/cases")
async def admin_case_save(request: Request):
    """Create or update a case in the shop config."""
    user = admin_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    body = await read_json(request)
    case = body.get("case")
    if not isinstance(case, dict):
        return JSONResponse({"detail": "Dữ liệu rương không hợp lệ."},
                            status_code=400)
    try:
        clean = gacha_upsert_case(gacha_load_config(), case)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    updated = get_case(clean["id"])
    store.log_admin(
        "save_case", clean["id"],
        f"{clean['name']}, gia {format_coin(clean['pull_cost'])}, "
        f"{len(clean['items'])} mon", admin=user,
    )
    return {
        "case": gacha_case_view(updated) if updated else clean,
        "message": f"Đã lưu rương {clean['name']}.",
    }


@app.delete("/api/admin/cases/{case_id}")
async def admin_case_delete(request: Request, case_id: str):
    user = admin_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    gacha_delete_case(gacha_load_config(), case_id)
    store.log_admin("delete_case", case_id, "", admin=user)
    return {"deleted": case_id, "message": f"Đã xoá rương {case_id}."}


@app.get("/api/admin/tx")
async def admin_tx(request: Request, search: str = "", kind: str = ""):
    user = require_admin(request)
    if isinstance(user, JSONResponse):
        return user
    rows = store.list_tx_all(search, kind)
    for row in rows:
        row["when"] = datetime.fromtimestamp(row["created_at"], tz=VN_TZ).strftime("%d/%m %H:%M")
        row["amount_fmt"] = format_coin(row["amount"])
        row["kind_label"] = KIND_LABELS.get(row["kind"], row["kind"])
    return {"tx": rows}


@app.get("/api/admin/inventory")
async def admin_inventory(request: Request, search: str = "", status: str = ""):
    user = require_admin(request)
    if isinstance(user, JSONResponse):
        return user
    rows = store.list_inventory_all(search, status)
    for row in rows:
        row["value_fmt"] = format_coin(row["value"])
    return {"items": rows}


@app.get("/api/admin/battles")
async def admin_battles(request: Request):
    user = require_admin(request)
    if isinstance(user, JSONResponse):
        return user
    battles = store.admin_battles()
    for row in battles:
        row["created_fmt"] = datetime.fromtimestamp(row["created_at"], tz=VN_TZ).strftime("%d/%m %H:%M")
        for seat in row["players"]:
            seat["total_fmt"] = format_coin(seat["total"])
    return {"battles": battles}


@app.post("/api/admin/battles/{battle_id}/cancel")
async def admin_battle_cancel(request: Request, battle_id: int):
    """Cancel a waiting battle and return the Coin to every seat.

    The seats paid on the Minecraft server, so the refund goes back to the
    server too. A refund that only touched the local ledger would be wiped
    by the next sync and the player would lose the money for real.
    """
    user = admin_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    battle = store.get_battle(battle_id)
    if not battle:
        return JSONResponse({"detail": "Không có trận này."}, status_code=404)
    if battle["status"] != "WAITING":
        return JSONResponse({"detail": "Chỉ huỷ được trận đang chờ."},
                            status_code=400)
    refunded = 0
    failed = []
    for seat in battle.get("players") or []:
        player = seat["player"]
        paid = int(seat.get("paid") or 0)
        if paid <= 0:
            continue
        if is_dry_run():
            store.credit(player, paid, "refund", "admin huỷ trận")
            refunded += paid
            continue
        try:
            await pika_give(player, paid, kind="refund")
            refunded += paid
        except HTTPException as exc:
            failed.append(f"{player}: {exc.detail}")
    store.delete_battle(battle_id)
    store.log_admin(
        "cancel_battle", str(battle_id),
        f"hoan {format_coin(refunded)} Coin", admin=user,
    )
    message = f"Đã huỷ trận #{battle_id}, hoàn {format_coin(refunded)} Coin."
    if failed:
        message += " Không hoàn được cho: " + "; ".join(failed)
    return {
        "battle_id": battle_id,
        "refunded": refunded,
        "refunded_fmt": format_coin(refunded),
        "failed": failed,
        "message": message,
    }


@app.post("/api/admin/battles/{battle_id}/finish")
async def admin_battle_finish(request: Request, battle_id: int):
    """Force a waiting battle to finish and roll the drops."""
    user = admin_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    battle = store.get_battle(battle_id)
    if not battle:
        return JSONResponse({"detail": "Không có trận này."}, status_code=404)
    # A RUNNING battle was left behind by a crash and has no result, so
    # the admin can finish it as well.
    if battle["status"] not in ("WAITING", "RUNNING"):
        return JSONResponse({"detail": "Trận này không còn chờ."}, status_code=400)
    if len(battle.get("players") or []) < 2:
        return JSONResponse({"detail": "Cần ít nhất 2 người để kết thúc trận."},
                            status_code=400)
    try:
        game.settle_battle(battle_id)
    except game.GameError as exc:
        return json_error(exc)
    store.log_admin("finish_battle", str(battle_id), "", admin=user)
    return {"battle_id": battle_id, "message": f"Đã kết thúc trận #{battle_id}."}


@app.get("/api/admin/log")
async def admin_log(request: Request):
    """What the admins did, newest first."""
    user = require_admin(request)
    if isinstance(user, JSONResponse):
        return user
    rows = store.list_admin_log(100)
    for row in rows:
        row["when"] = datetime.fromtimestamp(row["created_at"], tz=VN_TZ).strftime("%d/%m %H:%M")
    return {"log": rows}


@app.get("/api/admin/server")
async def admin_server(request: Request):
    """Live state of the PikaMC server and the console connection."""
    user = require_admin(request)
    if isinstance(user, JSONResponse):
        return user
    info = {"console": console_available(), "dry_run": is_dry_run(),
            "server": None, "error": None}
    try:
        info["server"] = await get_server(PIKA_SERVER_UUID) if PIKA_SERVER_UUID else None
        if info["server"] is None:
            servers = await list_servers()
            info["server"] = servers[0] if servers else None
    except HTTPException as exc:
        info["error"] = str(exc.detail)
    return info


# --------------------------------------------------------------------------- #
# Admin list, kept in step with the LuckPerms group on the server
# --------------------------------------------------------------------------- #
@app.get("/api/admin/admins")
async def admin_admins(request: Request, refresh: int = 0):
    """The admin list of the web console and of the server, side by side."""
    user = require_admin(request)
    if isinstance(user, JSONResponse):
        return user
    server_error = ""
    try:
        server_list = await luckperms.fetch_server_admins(force=bool(refresh))
    except HTTPException as exc:
        server_list = luckperms.cached_admins()
        server_error = str(exc.detail)
    # Copy the server list into the local table so the two agree even
    # when the server cannot be reached later.
    if not server_error:
        store.replace_admins(server_list, source="server")
    local = {row["name"].lower(): row for row in store.list_admin_records()}
    names = sorted(set(local) | set(server_list) | set(ADMIN_USERS))
    entries = []
    for name in names:
        record = local.get(name, {})
        entries.append({
            "name": name,
            "web": name in {n.lower() for n in ADMIN_USERS}
                    or name in local,
            "server": name in set(server_list),
            "source": record.get("source", ""),
        })
    return {
        "admins": entries,
        "server_group": ADMIN_GROUP,
        "server_error": server_error,
        "synced_at": datetime.fromtimestamp(
            luckperms.cache_time(), tz=VN_TZ).strftime("%d/%m %H:%M")
        if luckperms.cache_time() else "",
    }


@app.post("/api/admin/admins")
async def admin_admins_update(request: Request):
    """Add or remove an admin, on the web and on the server."""
    user = admin_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    body = await read_json(request)
    name = str(body.get("name") or "").strip()
    action = str(body.get("action") or "").strip()
    if not name:
        return JSONResponse({"detail": "Cần tên tài khoản."}, status_code=400)
    if action not in {"grant", "revoke"}:
        return JSONResponse({"detail": "Hành động không hợp lệ."},
                            status_code=400)
    safe = luckperms.safe_name(name)
    if not safe:
        return JSONResponse(
            {"detail": "Tên tài khoản không hợp lệ (chỉ chữ, số, . _ -)."},
            status_code=400)

    # The server is the source of truth: change the LuckPerms group first,
    # then record it locally. When the server cannot be reached the change
    # is refused, so the two lists cannot drift apart.
    try:
        if action == "grant":
            await luckperms.grant_admin(safe)
        else:
            await luckperms.revoke_admin(safe)
    except HTTPException as exc:
        store.log_admin(f"admin_{action}_failed", safe, str(exc.detail),
                        admin=user)
        return JSONResponse({"detail": str(exc.detail)}, status_code=exc.status_code)

    if action == "grant":
        store.add_admin(safe, source="server")
    else:
        store.remove_admin(safe)
    store.log_admin(f"admin_{action}", safe, f"group={ADMIN_GROUP}", admin=user)
    return {"name": safe, "action": action, "group": ADMIN_GROUP,
            "message": (f"Đã cấp quyền admin cho {safe}."
                        if action == "grant"
                        else f"Đã gỡ quyền admin khỏi {safe}.")}


@app.post("/api/admin/admins/sync")
async def admin_admins_sync(request: Request):
    """Pull the server admin list and copy it into the local list."""
    user = admin_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        server_list = await luckperms.fetch_server_admins(force=True)
    except HTTPException as exc:
        store.log_admin("admin_sync_failed", "", str(exc.detail), admin=user)
        return JSONResponse({"detail": str(exc.detail)}, status_code=exc.status_code)
    store.replace_admins(server_list, source="server")
    store.log_admin("admin_sync", "", f"{len(server_list)} tai khoan", admin=user)
    return {"admins": server_list, "group": ADMIN_GROUP,
            "message": f"Đã đồng bộ {len(server_list)} admin từ server."}


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    token = new_csrf_token()
    request.session["csrf"] = token
    return render(request, "setup.html", csrf=token, pika_ready=pika_ready(), servers=None, error=None)


@app.get("/setup/test")
async def setup_test_get():
    return RedirectResponse("/setup", status_code=303)


@app.post("/setup/test")
async def setup_test(request: Request, csrf: str = Form(...)):
    expected = request.session.get("csrf")
    if not csrf or not expected or not hmac.compare_digest(csrf, str(expected)):
        return RedirectResponse("/setup", status_code=303)
    token = new_csrf_token()
    request.session["csrf"] = token
    if not pika_ready():
        return render(
            request,
            "setup.html",
            csrf=token,
            pika_ready=False,
            servers=None,
            error="Chưa có PIKA_API_KEY trong file .env",
        )
    try:
        servers = [await get_server(PIKA_SERVER_UUID)] if PIKA_SERVER_UUID else await list_servers()
        return render(request, "setup.html", csrf=token, pika_ready=True, servers=servers, error=None)
    except HTTPException as exc:
        return render(request, "setup.html", csrf=token, pika_ready=True, servers=None, error=exc.detail)
