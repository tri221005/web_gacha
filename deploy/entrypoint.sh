#!/bin/sh
# Khoi dong container web.
#
# File cau hinh shop (gacha.json) nam tren volume de khong mat khi restart.
# Lan chay dau tien, file do chua ton tai trong volume, nen se duoc sao
# chep tu ban trong image.
#
# Script chay voi quyen root de chuan hoa quyen cua volume, roi chuyen sang
# user khong phai quyen root truoc khi chay app.
set -e

GACHA_TARGET="${GACHA_FILE:-/srv/app/data/gacha.json}"

if [ -n "$GACHA_TARGET" ] && [ ! -f "$GACHA_TARGET" ]; then
    echo "==> Seed $GACHA_TARGET tu image"
    mkdir -p "$(dirname "$GACHA_TARGET")"
    if [ -f /srv/app/gacha.json ]; then
        cp /srv/app/gacha.json "$GACHA_TARGET"
    else
        echo '{"cases": []}' > "$GACHA_TARGET"
    fi
fi

# Volume do host mount vao thuong thuoc thuoc root. App chay voi user
# "appuser" nen folder phai doi chu truoc, neu khong app se khong ghi
# duoc gacha.json.
if [ "$(id -u)" = "0" ] && id appuser >/dev/null 2>&1; then
    chown -R appuser:appuser "$(dirname "$GACHA_TARGET")" 2>/dev/null || true
    chown -R appuser:appuser /srv/app 2>/dev/null || true
    exec setpriv --reuid=appuser --regid=appuser --clear-groups "$@"
fi

exec "$@"
