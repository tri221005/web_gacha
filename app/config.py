import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-only-change-me")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8080"))
# The session cookie is only sent over HTTPS when the site is served over
# HTTPS. Turning this on while the site runs on plain HTTP would lock every
# player out, so it follows the deployment.
#
# "auto" (the default) marks the cookie as Secure only when the request
# that made it arrived over HTTPS. That way the same build works on a
# local HTTP server and on a live HTTPS site. "true" forces Secure on
# (the cookie is then never sent over plain HTTP), "false" never does.
_session_https = os.getenv("SESSION_HTTPS_ONLY", "auto").strip().lower()
SESSION_HTTPS_ONLY: bool | None
if _session_https in {"1", "true", "yes"}:
    SESSION_HTTPS_ONLY = True
elif _session_https in {"0", "false", "no"}:
    SESSION_HTTPS_ONLY = False
else:
    SESSION_HTTPS_ONLY = None

PIKA_BASE_URL = os.getenv("PIKA_BASE_URL", "https://hub.pikamc.vn").rstrip("/")
PIKA_API_KEY = os.getenv("PIKA_API_KEY", "").strip()
PIKA_SERVER_UUID = os.getenv("PIKA_SERVER_UUID", "").strip()
PIKA_AUTHME_DB = os.getenv("PIKA_AUTHME_DB", "/plugins/AuthMe/authme.db")
PIKA_ECONOMY_DB = os.getenv("PIKA_ECONOMY_DB", "/plugins/ExcellentEconomy/data.db")
ADMIN_USERS = {
    name.strip().lower()
    for name in os.getenv("ADMIN_USERS", "").split(",")
    if name.strip()
}
# A password of its own for the admin console. When it is set, an admin can
# sign in at /admin/login without the Minecraft password, so the game
# account and the admin account stay separate. An empty value disables the
# password login and leaves only the ADMIN_USERS accounts.
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()

# The LuckPerms group that counts as "admin" on the Minecraft server. The
# web console admin list is kept in step with this group.
ADMIN_GROUP = os.getenv("ADMIN_GROUP", "admin").strip() or "admin"

# How long the server admin list stays cached. The list only changes when
# somebody is promoted, so a short window is enough.
ADMIN_SYNC_SECONDS = float(os.getenv("ADMIN_SYNC_SECONDS", "30") or 30)
STATIC_DIR = ROOT / "app" / "static"

# The shop config is the only file the app writes at runtime, so it lives
# on its own and its path can be pointed at a mounted volume on a
# container host. Without that, every restart would lose the cases and
# the RTP values edited in the admin console.
GACHA_FILE = Path(
    os.getenv("GACHA_FILE", str(ROOT / "gacha.json"))
).expanduser()

# SQL Server holds the gacha ledger (tables prefixed `gacha_`).
SQL_SERVER = os.getenv("SQL_SERVER", "localhost").strip()
SQL_DATABASE = os.getenv("SQL_DATABASE", "jellyvale").strip()
# Optional SQL login. When it is empty the app uses the Windows integrated
# login (Trusted_Connection), which only exists on a Windows machine. A
# Linux host, a Docker container or a cloud instance must use a SQL login
# instead, so the credentials are configurable.
SQL_USER = os.getenv("SQL_USER", "").strip()
SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")
# "ODBC Driver 18 for SQL Server" everywhere, but the name differs on a
# few Linux distributions that ship the 17 build.
SQL_DRIVER = os.getenv("SQL_DRIVER", "ODBC Driver 18 for SQL Server").strip()
# Some self-signed SQL instances cannot be verified, so the certificate
# check has to be turned off. It is on by default.
SQL_TRUST_CERT = os.getenv("SQL_TRUST_SERVER_CERTIFICATE", "yes").strip().lower() not in {
    "0", "false", "no",
}
SQL_ENCRYPT = os.getenv("SQL_ENCRYPT", "yes").strip().lower() not in {"0", "false", "no"}
SQL_PORT = os.getenv("SQL_PORT", "").strip()
SQL_TIMEOUT = int(os.getenv("SQL_TIMEOUT", "30") or 30)


def pika_ready() -> bool:
    return bool(PIKA_API_KEY)


def dry_run() -> bool:
    return os.getenv("GACHA_DRY_RUN", "true").strip().lower() in {"1", "true", "yes"}
