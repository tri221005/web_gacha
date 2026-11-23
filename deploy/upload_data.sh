#!/usr/bin/env bash
# Nap schema va du lieu gacha tu may Windows len VPS Oracle.
#
#   bash deploy/upload_data.sh <user>@<IP-VPS>
#
# Script copy file .sql len VPS roi nap vao database jellyvale bang sqlcmd.
# Neu database da co du lieu roi, dung co lenh nao de ghi de.
set -euo pipefail

TARGET="${1:?Dung: bash deploy/upload_data.sh <user>@<IP-VPS>}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQL_FILE="$ROOT_DIR/jellyvale_full.sql"

if [ ! -f "$SQL_FILE" ]; then
    echo "Khong tim thay $SQL_FILE"
    exit 1
fi

echo "==> Upload $SQL_FILE len $TARGET (co the mat mot luc, file ~40MB)"
scp "$SQL_FILE" "${TARGET}:/tmp/jellyvale_full.sql"

echo "==> Nap schema vao database jellyvale"
echo "    (nhac: SQL Server se bao loi neu bang da ton tai - muc dua du lieu cu)"
ssh "$TARGET" <<'EOF'
set -e
SA_PASSWORD_FILE=/srv/jellyvale/.sa_password
if [ ! -f "$SA_PASSWORD_FILE" ]; then
    echo "Chua co $SA_PASSWORD_FILE. Hay dat mat khau SQL Server truoc."
    exit 1
fi
SA_PASSWORD=$(cat "$SA_PASSWORD_FILE")
sudo /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$SA_PASSWORD" -C \
    -Q "IF DB_ID('jellyvale') IS NULL CREATE DATABASE jellyvale"
sudo /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$SA_PASSWORD" -C \
    -d jellyvale -i /tmp/jellyvale_full.sql || \
    echo "Nap co loi - neu chi do la 'bang da ton tai' thi du lieu da duoc nap xong."
sudo /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$SA_PASSWORD" -C \
    -d jellyvale -Q "SELECT COUNT(*) AS tables_gacha FROM sys.tables WHERE name LIKE 'gacha[_]%'"
rm -f /tmp/jellyvale_full.sql
EOF

echo
echo "Xong. Kiem tra bang:"
echo "  ssh $TARGET 'sudo /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P \"\$(cat /srv/jellyvale/.sa_password)\" -C -d jellyvale -Q \"SELECT COUNT(*) FROM gacha_wallets\"'"
