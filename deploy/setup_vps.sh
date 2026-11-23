#!/usr/bin/env bash
# Cai dat toan bo web JellyVale Gacha tren Oracle Cloud Always Free VPS.
#
#   ssh ubuntu@<IP-VPS> 'bash setup_vps.sh'
#
# Script nap san: Docker, SQL Server 2022, ODBC driver 18, web container
# va Caddy (HTTPS mien phi). Chay lai duoc nhieu lan, khong lam hong cai gi.
set -euo pipefail

echo "=============================================="
echo "  JellyVale Gacha - cai dat VPS"
echo "=============================================="

DOMAIN="${DOMAIN:-}"
SSH_USER="${SSH_USER:-deploy}"
APP_DIR="${APP_DIR:-/srv/jellyvale}"
IMAGE="${IMAGE:-ghcr.io/jellyvale/web:latest}"
SA_PASSWORD="${SA_PASSWORD:?Thieu SA_PASSWORD. Vd: SA_PASSWORD='MatKhauManh' bash setup_vps.sh}"
APP_DB_PASSWORD="${APP_DB_PASSWORD:?Thieu APP_DB_PASSWORD}"

log() { echo -e "\n\033[1;34m==> $*\033[0m"; }

# --------------------------------------------------------------------------- #
log "1/7 Docker"
# --------------------------------------------------------------------------- #
if ! command -v docker >/dev/null 2>&1; then
  sudo dnf install -y dnf-plugins-core
  sudo dnf config-manager --add-repo=https://download.docker.com/linux/centos/docker-ce.repo
  sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
sudo systemctl enable --now docker
docker --version

# --------------------------------------------------------------------------- #
log "2/7 SQL Server 2022 + ODBC driver 18"
# --------------------------------------------------------------------------- #
if ! rpm -q mssql-server >/dev/null 2>&1; then
  sudo curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
    | sudo tee /etc/pki/rpm-gpg/RPM-GPG-KEY-mssql-server >/dev/null
  sudo curl -fsSL https://packages.microsoft.com/config/rhel/9/mssql-server-2022.repo \
    | sudo tee /etc/yum.repos.d/mssql-server-2022.repo >/dev/null
  sudo dnf install -y mssql-server msodbcsql18
  sudo MSSQL_SA_PASSWORD="$SA_PASSWORD" /opt/mssql/bin/mssql-conf -n setup accept-eula
  sudo systemctl enable --now mssql-server
fi

# SQL Server can can vai giay de khoi dong lai lan dau.
echo "Doi SQL Server khoi dong..."
for i in $(seq 1 30); do
  if sudo /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$SA_PASSWORD" -C \
       -Q "SELECT 1" >/dev/null 2>&1; then
    echo "SQL Server san sang sau ${i}s."
    break
  fi
  sleep 1
done

# --------------------------------------------------------------------------- #
log "3/7 Tao database + user rieng cho web"
# --------------------------------------------------------------------------- #
# Mat khau SQL Server duoc luu lai tren VPS de cac script ve sau dung
# duoc, khong phai nhap lai. Ghi bang stdin de khong bi shell phan tich
# sai ky tu dac biet trong mat khau.
sudo mkdir -p "$APP_DIR"
printf '%s' "$SA_PASSWORD" | sudo tee "$APP_DIR/.sa_password" >/dev/null
sudo chmod 600 "$APP_DIR/.sa_password"
SQLCMD="sudo /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P $SA_PASSWORD -C"

sudo bash -c "$SQLCMD -Q \"
IF DB_ID('jellyvale') IS NULL
BEGIN
    CREATE DATABASE jellyvale;
END
\""

# User rieng: web khong bao gio dung tai khoan 'sa'.
#
# Script SQL duoc ghi ra file roi chay bang sqlcmd -i, vi lenh truyen
# truc tiep qua shell se lam mat dau nhay neu mat khau chua ky tu dac biet
# (nhu @ trong Admin@admin).
SQL_TMP=$(mktemp /tmp/gacha_user.XXXXXX.sql)
cat > "$SQL_TMP" <<SQL
USE master;
IF NOT EXISTS (SELECT 1 FROM sys.sql_logins WHERE name = 'gacha_app')
BEGIN
    CREATE LOGIN gacha_app WITH PASSWORD = N'$APP_DB_PASSWORD';
END
USE jellyvale;
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'gacha_app')
BEGIN
    CREATE USER gacha_app FOR LOGIN gacha_app;
    ALTER ROLE db_datareader ADD MEMBER gacha_app;
    ALTER ROLE db_datawriter ADD MEMBER gacha_app;
END
SQL
sudo bash -c "$SQLCMD -i $SQL_TMP"
rm -f "$SQL_TMP"

# --------------------------------------------------------------------------- #
log "4/7 Nap schema (jellyvale_full.sql)"
# --------------------------------------------------------------------------- #
if [ -f "$APP_DIR/jellyvale_full.sql" ]; then
  if sudo bash -c "$SQLCMD -d jellyvale -Q \"SELECT COUNT(*) FROM sys.tables WHERE name LIKE 'gacha[_]%'\"" \
       | grep -qE '[1-9]'; then
    echo "Bang gacha_ da co san, bo qua nap schema."
  else
    echo "Dang nap jellyvale_full.sql, co the mat mot luc..."
    sudo bash -c "$SQLCMD -d jellyvale -i $APP_DIR/jellyvale_full.sql" || \
      echo "Can co loi, chay lai lenh nap thu cong."
  fi
else
  echo "KHONG tim thay $APP_DIR/jellyvale_full.sql - hay copy file nay len VPS truoc."
  echo "Neu database da co du lieu thi khong can nap."
fi

# --------------------------------------------------------------------------- #
log "5/7 Caddy (HTTPS mien phi)"
# --------------------------------------------------------------------------- #
if ! command -v caddy >/dev/null 2>&1; then
  sudo dnf install -y 'dnf-command(copr)'
  sudo dnf copr enable @caddy/caddy -y
  sudo dnf install -y caddy
fi

if [ -n "$DOMAIN" ]; then
  sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
${DOMAIN} {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8080
}
EOF
  sudo systemctl enable --now caddy
  sudo systemctl reload caddy
  echo "Caddy da cau hinh cho ${DOMAIN}."
else
  echo "Chua co DOMAIN nen Caddy chi phuc vu cong 80. Ban can dat DNS A record tro ve IP VPS roi chay lai script."
fi

# --------------------------------------------------------------------------- #
log "6/8 File .env cho web"
# --------------------------------------------------------------------------- #
sudo mkdir -p "$APP_DIR/data"
if [ ! -f "$APP_DIR/.env" ]; then
  SESSION_SECRET_VALUE=$(openssl rand -hex 32)
  # Ghi bang printf chu khong dung heredoc: heredoc se lam shell phan tich
  # ky tu dac biet trong mat khau ($, backtick) va lam sai gia tri.
  sudo tee "$APP_DIR/.env" >/dev/null <<EOF
# File nay chua bi khoa. KHONG day len GitHub.
SESSION_SECRET=${SESSION_SECRET_VALUE}
SESSION_HTTPS_ONLY=auto
HOST=0.0.0.0
PORT=8080

SQL_SERVER=host.docker.internal
SQL_DATABASE=jellyvale
SQL_USER=gacha_app
SQL_PASSWORD=${APP_DB_PASSWORD}
SQL_DRIVER=ODBC Driver 18 for SQL Server
SQL_ENCRYPT=yes
SQL_TRUST_SERVER_CERTIFICATE=yes

# File cau hinh shop, phai nam tren volume de khong mat khi restart.
GACHA_FILE=/srv/app/data/gacha.json

PIKA_BASE_URL=https://hub.pikamc.vn
PIKA_API_KEY=${PIKA_API_KEY:-}
PIKA_SERVER_UUID=${PIKA_SERVER_UUID:-}
ADMIN_USERS=${ADMIN_USERS:-hhh21}
ADMIN_PASSWORD=${ADMIN_PASSWORD:-}
ADMIN_GROUP=admin
ADMIN_SYNC_SECONDS=30
GACHA_DRY_RUN=false
EOF
  echo "Da tao $APP_DIR/.env."
  echo "HAY DIEN PIKA_API_KEY, PIKA_SERVER_UUID va ADMIN_PASSWORD trong file do:"
  echo "  sudo nano $APP_DIR/.env"
else
  echo "$APP_DIR/.env da ton tai, giu nguyen."
fi
sudo chmod 600 "$APP_DIR/.env"

# --------------------------------------------------------------------------- #
log "7/8 Docker Compose cho web"
# --------------------------------------------------------------------------- #
sudo tee "$APP_DIR/docker-compose.yml" >/dev/null <<'EOF'
services:
  web:
    image: ghcr.io/jellyvale/web:latest
    container_name: jellyvale-web
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:8080"
    env_file:
      - .env
    environment:
      HOST: "0.0.0.0"
      PORT: "8080"
      # SQL Server chay cung host. host.docker.internal tro ve may host.
      SQL_SERVER: "host.docker.internal"
      GACHA_FILE: "/srv/app/data/gacha.json"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      # Cau hinh shop (gacha.json) phai song lai qua cac lan restart.
      - ./data:/srv/app/data
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
EOF

# --------------------------------------------------------------------------- #
log "8/8 Bat container web"
# --------------------------------------------------------------------------- #
cd "$APP_DIR"
sudo docker compose pull || echo "Chua co image tren GHCR, dung image local neu da build."
sudo docker compose up -d
sleep 15
sudo docker compose ps
echo
curl -fsS http://127.0.0.1:8080/health && echo || echo "Health check chua duoc, xem log: docker compose logs -f web"

echo
echo "=============================================="
echo "  Xong! Kiem tra:"
echo "  curl http://127.0.0.1:8080/health"
echo "  sudo docker compose -f $APP_DIR/docker-compose.yml logs -f web"
echo "=============================================="
