# Phương án B — Oracle Cloud Always Free VPS (web chạy 24/7)

Mục tiêu: web chạy 24/7 trên VPS Linux của Oracle, **0đ vĩnh viễn**, có
HTTPS thật, không phụ thuộc máy chủ Minecraft của bạn.

---

## ⚠️ Đọc trước: yêu cầu RAM

SQL Server cần **tối thiểu 2 GB RAM** để chạy ổn định. Shape
`VM.Standard.E2.1.Micro` (1 GB) của Oracle **không đủ** — SQL Server sẽ
bị OOM-killed.

Dùng shape **`VM.Standard.A1.Flex`**:

- **4 OCPU + 24 GB RAM** — thuộc Always Free, **đủ chạy SQL Server + web**
- Tổng cộng Oracle cho phép 4 OCPU / 24 GB RAM ở dạng A1.Flex
- Lấy 4 OCPU + 12 GB RAM là dư (để dành cho việc khác)

> **Lưu ý:** Oracle thường **hết capacity** ở khu vực `home` (Singapore).
> Nếu không tạo được, thử khu vực khác: `ap-southeast-1` (Singapore),
> `ap-southeast-2` (Sydney), `ap-northeast-1` (Tokyo), `us-ashburn-1`.

---

## Bước 1 — Tạo tài khoản Oracle Cloud

1. Mở <https://cloud.oracle.com/free> → **Start for Free**.
2. Điền email, quốc gia (Việt Nam), mật khẩu.
3. Yêu cầu **thẻ Visa/Mastercard** (chỉ để xác minh, **Oracle không tính
   phí** cho tài nguyên Always Free — nhưng phải **hủy thẻ ảo** trong
   ngân hàng sau khi xác nhận để tránh bị charge).
4. Chọn **Home Region** — chọn khu vực gần bạn nhất.

---

## Bước 2 — Tạo VM

1. Vào <https://cloud.oracle.com/compute/instances> → **Create instance**.
2. **Name**: `jellyvale-web`
3. **Image and shape**:
   - Image: **Oracle Linux 9 (Always Free Eligible)**
   - Shape: **Change shape** → **Ampere** → `VM.Standard.A1.Flex`
   - **4 OCPU**, **12 GB RAM**
   - Nếu chỉ thấy `E2.1.Micro`, nghĩa là hết capacity A1 ở khu vực đó.
     Thử khu vực khác hoặc thử lại sau.
4. **Networking**: chọn VCN có sẵn, **subnet public**.
5. **Add SSH keys**: tạo key mới và **tải `ssh-key-oc.key` về** (chỉ tải
   được 1 lần duy nhất) → `Public Key` tự động điền.
6. **Boot volume**: mặc định 50 GB, đủ.
7. **Create**.

Chờ vài phút để VM chạy. Ghi lại **Public IP**.

---

## Bước 3 — Mở firewall

Vào <https://cloud.oracle.com/security/firewalls> → chọn **Security List**
của VCN → **Add Ingress Rules**:

| Source CIDR | Protocol | Port |
|---|---|---|
| `0.0.0.0/0` | TCP | 443 |
| `0.0.0.0/0` | TCP | 80 |
| **IP của bạn** | TCP | 22 |

> Chỉ mở port 22 cho IP của bạn để không bị dò mật khẩu SSH.

---

## Bước 4 — SSH vào VPS

```powershell
# Windows: chmod cho file key
icacls ssh-key-oc.key /inheritance:r /grant:r "$($env:USERNAME):(R)"

ssh -i ssh-key-oc.key ubuntu@<PUBLIC-IP>
```

Lần đầu gõ `yes` để đồng ý fingerprint.

---

## Bước 5 — Cài đặt tự động

**Trên máy Windows:**
```powershell
scp -i ssh-key-oc.key d:\web-gacha\web-gacha\deploy\setup_vps.sh ubuntu@<PUBLIC-IP>:~/jellyvale-deploy/
```

**Trên VPS:**
```bash
mkdir -p ~/jellyvale-deploy
cd ~/jellyvale-deploy
chmod +x setup_vps.sh

SA_PASSWORD='MatKhauSqlServerManh' \
APP_DB_PASSWORD='MatKhauChoGachaApp' \
PIKA_API_KEY='<your-pika-api-key>' \
PIKA_SERVER_UUID='de021d06' \
ADMIN_USERS='hhh21' \
ADMIN_PASSWORD='Admin@admin' \
bash setup_vps.sh
```

Script làm hết: Docker → SQL Server 2022 + ODBC 18 → tạo database
`jellyvale` + user `gacha_app` → Caddy → file `.env` → Docker Compose →
khởi động container.

---

## Bước 6 — Nạp dữ liệu

File `jellyvale_full.sql` (~40 MB) chứa toàn bộ dữ liệu từ server
Minecraft + ledger gacha.

**Trên máy Windows:**
```powershell
scp -i ssh-key-oc.key d:\web-gacha\web-gacha\jellyvale_full.sql ubuntu@<PUBLIC-IP>:/srv/jellyvale/
```

**Trên VPS:**
```bash
sudo bash -c '/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$(cat /srv/jellyvale/.sa_password)" -C -d jellyvale -i /srv/jellyvale/jellyvale_full.sql'
```

Kiểm tra:
```bash
sudo bash -c '/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$(cat /srv/jellyvale/.sa_password)" -C -d jellyvale -Q "SELECT COUNT(*) FROM gacha_wallets"'
```

---

## Bước 7 — Build & push image

Cần **Docker Desktop** trên máy Windows: <https://docs.docker.com/desktop/setup/install/windows-install/>

**Trên máy Windows:**
```powershell
cd d:\web-gacha\web-gacha

# Token tai https://github.com/settings/tokens (quyen write:packages)
$token = "ghp_xxxxxxxxxxxx"
$token | docker login ghcr.io -u <TEN-GITHUB-CUA-BAN> --password-stdin

bash deploy/build_push.sh <TEN-GITHUB-CUA-BAN>
```

> Nếu bạn **không có tài khoản GitHub**, build image trực tiếp trên VPS
> rồi chạy bằng image local — xem Bước 8.

---

## Bước 8 — Chạy container

**Trên VPS:**
```bash
cd /srv/jellyvale

# Neu da push len GHCR:
sudo docker compose pull
sudo docker compose up -d

# Neu KHONG co GitHub, build tai VPS:
sudo docker build -t jellyvale-web:latest .
# roi doi image trong docker-compose.yml thanh jellyvale-web:latest
sudo docker compose up -d
```

Kiểm tra:
```bash
sudo docker compose logs -f web
curl http://127.0.0.1:8080/health
```

Kết quả mong đợi:
```json
{"status":"ok","database":"ok","database_error":"","pika":"ready"}
```

---

## Bước 9 — Trỏ domain + HTTPS

1. Tạo **A record** trong nhà cung cấp domain:
   - Type: `A`
   - Name: `gacha`
   - Value: `<PUBLIC-IP-VPS>`
   - TTL: 300
2. Chạy lại script để Caddy lấy chứng chỉ:
   ```bash
   cd ~/jellyvale-deploy
   DOMAIN='gacha.jellyvale.vn' bash setup_vps.sh
   ```
3. Caddy tự lấy chứng chỉ Let's Encrypt và tự renew.

Kiểm tra:
```bash
curl -I https://gacha.jellyvale.vn/health
```

### Không có domain?

Dùng Cloudflare Tunnel **từ VPS** — vẫn miễn phí, không cần domain:

```bash
curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
cloudflared service install
```

---

## Bước 10 — Bảo mật

```bash
# 1. Firewall tren VPS
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload

# 2. Fail2ban (chan brute-force SSH)
sudo dnf install -y fail2ban
sudo systemctl enable --now fail2ban

# 3. SSH: khoa password, chi dung key
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd

# 4. Giu container khong co quyen Docker socket
#    (docker-compose.yml khong co 'docker.sock' nen mac dinh an toan)
```

---

## Bước 11 — Cập nhật web sau này

```powershell
# Tren may Windows
cd d:\web-gacha\web-gacha
bash deploy/build_push.sh <TEN-GITHUB-CUA-BAN>
```

```bash
# Tren VPS
cd /srv/jellyvale
sudo docker compose pull
sudo docker compose up -d
```

Cấu hình shop (`gacha.json`) nằm trên volume `./data` nên **không mất**
khi restart container.

---

## Vấn đề thường gặp

| Triệu chứng | Nguyên nhân | Cách sửa |
|---|---|---|
| `Login failed for user 'sa'` | Sai mật khẩu SA | `sudo /opt/mssql/bin/mssql-conf -n setup` để đặt lại |
| `Login failed for user 'gacha_app'` | User chưa tạo, hoặc sai mật khẩu | Chạy lại `setup_vps.sh` |
| `Cannot open a connection` từ container | `host.docker.internal` không resolve | Kiểm tra `extra_hosts` trong compose |
| `SQL Server khong start` | Thiếu RAM | Dùng A1.Flex 12 GB, không dùng E2.1.Micro |
| Container restart liên tục | Xem log | `sudo docker compose logs --tail=50 web` |
| `Caddy khong lay duoc chung chi` | DNS chưa lan, hoặc port 80 bị chặn | Kiểm tra A record + mở port 80 |
| `gacha.json` biến mất sau restart | Thiếu volume | Kiểm tra `volumes:` trong compose |
| Trang báo "Cơ sở dữ liệu đang bận" | SQL Server chưa sẵn sàng | `sudo systemctl status mssql-server` |