# Deploy miễn phí — JellyVale Gacha

Tài liệu này liệt kê các cách đưa web lên internet **không tốn tiền**, kèm
cách làm cụ thể cho từng phương án.

---

## 0. Vì sao chọn hướng nào?

App này có ba phụ thuộc cứng:

| Phụ thuộc | Vấn đề | Hệ quả |
|---|---|---|
| **Microsoft SQL Server** (`pyodbc` + ODBC Driver 18) | Gần như không nền tảng free nào cấp SQL Server | Render/Koyeb/Vercel/Fly.io **không chạy được** nếu không có SQL Server ở đâu đó |
| **PikaMC API** (`hub.pikamc.vn`) | Chỉ cần internet ra ngoài | Không vấn đề |
| **Ghi file `gacha.json` + `app/static/`** | Cần ổ đĩa ghi được | Không dùng được serverless không có state (Vercel, Lambda) |

Ngoài ra SQL Server phải **mở cho internet** để container cloud kết nối
tới, và đó là điểm khó nhất.

### Bảng so sánh nhanh

| Phương án | Chi phí | Khó | SQL Server | Phù hợp khi |
|---|---|---|---|---|
| **A. Cloudflare Tunnel** (chạy web tại máy chủ Minecraft) | 0đ | ⭐ | ✅ Giữ nguyên, local | ✅ **Khuyên dùng** |
| **B. Oracle Cloud Always Free VPS** | 0đ | ⭐⭐⭐ | ✅ Cài SQL Server trên VPS | Muốn web chạy 24/7 không phụ thuộc máy bạn |
| **C. Render / Railway / Fly.io** | 0đ (giới hạn) | ⭐⭐⭐⭐ | ⚠️ Cần SQL Server public | Đã có SQL Server trên cloud |
| **D. playit.gg / ngrok** | 0đ | ⭐ | ✅ Giữ nguyên, local | Cần URL public tạm để test |

---

## 1. PHƯƠNG ÁN A — Cloudflare Tunnel (khuyên dùng)

**Ý tưởng:** web vẫn chạy trên máy chủ Minecraft (Windows) của bạn, kèm
SQL Server local. Một chương trình nhỏ (`cloudflared`) tạo đường hầm ra
internet qua Cloudflare → bạn có tên miền HTTPS miễn phí.

**Ưu điểm:** không đổi kiến trúc, không mở port trên router, có HTTPS +
WAF miễn phí, tự động renew. Cũng dùng được để test nhanh.

**Nhược điểm:** web chỉ sống khi máy bạn bật. (Có thể khắc phục bằng
phương án B cho phần "always on".)

### 1.1. Chuẩn bị tài khoản Cloudflare

1. Vào <https://dash.cloudflare.com> → tạo tài khoản miễn phí.
2. Chọn **Add a site** → chọn **Free** plan.
3. Nhập tên miền con bạn muốn, ví dụ `gacha.jellyvale.vn`
   (nếu bạn không có tên miền riêng, xem mục 1.5).

### 1.2. Cài cloudflared trên máy chủ Minecraft

```powershell
winget install --id Cloudflare.cloudflared
```

Hoặc tải thủ công: <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/>

### 1.3. Chạy web ở chế độ production

Sửa `.env`:

```dotenv
HOST=127.0.0.1
PORT=8080
SESSION_HTTPS_ONLY=auto
```

Chạy:

```cmd
start_prod.bat
```

Kiểm tra: mở `http://127.0.0.1:8080/health` → phải thấy
`{"status":"ok","database":"ok",...}`

### 1.4. Tạo tunnel

```powershell
cloudflared tunnel login
cloudflared tunnel create jellyvale-gacha
```

Lệnh trên in ra `Tunnel credentials written to C:\Users\<bạn>\.cloudflared\<TUNNEL-ID>.json`.

Tạo file cấu hình `C:\Users\<bạn>\.cloudflared\config.yml`:

```yaml
tunnel: <TUNNEL-ID>
credentials-file: C:\Users\<bạn>\.cloudflared\<TUNNEL-ID>.json

ingress:
  - hostname: gacha.jellyvale.vn
    service: http://127.0.0.1:8080
  - service: http_status:404
```

Trỏ DNS vào tunnel:

```powershell
cloudflared tunnel route dns jellyvale-gacha gacha.jellyvale.vn
```

Chạy tunnel:

```powershell
cloudflared tunnel run jellyvale-gacha
```

Mở `https://gacha.jellyvale.vn/health` → xong.

### 1.5. Không có tên miền riêng?

Dùng **Cloudflare Quick Tunnel** — không cần tài khoản, không cần domain:

```powershell
cloudflared tunnel --url http://127.0.0.1:8080
```

Nó in ra một URL dạng `https://abc-def-ghi.trycloudflare.com`. URL này **đổi
mỗi lần khởi động lại**, nên chỉ dùng để test.

> Với Quick Tunnel, `SESSION_HTTPS_ONLY=auto` vẫn đúng vì URL là HTTPS.

> **Đã kiểm chứng:** quick tunnel + web này đã chạy thật, mọi trang
> (`/gacha`, `/login`, `/admin/login`, `/api/drops`) trả HTTP 200, cookie
> `jv_session` có cờ `Secure`, đăng nhập admin qua URL public trả `303 →
> /admin`, và `/api/admin/overview` trả số liệu thật từ SQL Server.

### 1.6. Chạy tunnel như service (Windows)

Để tunnel tự chạy cùng máy và tự khởi động lại khi rớt:

```powershell
# Chạy với quyền admin
cloudflared service install <TUNNEL-ID>
```

Hoặc đơn giản hơn, dùng **Task Scheduler** → task "At startup" chạy
`cloudflared tunnel run jellyvale-gacha`, bật "Run whether user is logged
on or not".

### 1.7. Bảo mật nên thêm (miễn phí, trong Cloudflare dashboard)

- **SSL/TLS → Edge Certificates → Always Use HTTPS**: bật.
- **Rules → WAF → Custom rules**: chặn các đường dẫn không cần thiết.
- **Security → Settings → Bot Fight Mode**: bật để chặn scraper.

---

## 2. PHƯƠNG ÁN B — Oracle Cloud Always Free VPS (web chạy 24/7)

> **📖 Hướng dẫn chi tiết: [`deploy/HUONG_DAN_ORACLE_VPS.md`](deploy/HUONG_DAN_ORACLE_VPS.md)**
>
> Script tự động: [`deploy/setup_vps.sh`](deploy/setup_vps.sh) ·
> [`deploy/build_push.sh`](deploy/build_push.sh) ·
> [`deploy/upload_data.sh`](deploy/upload_data.sh)

**Ý tưởng:** tạo một VPS Linux **miễn phí vĩnh viễn** (Oracle Cloud Free
Tier), cài Docker + SQL Server lên đó.

**Ưu điểm:** web chạy 24/7, không phụ thuộc máy bạn, có tên miền riêng
và HTTPS qua Let's Encrypt.

**Nhược điểm:** Oracle khó đăng ký (hay hết capacity ở khu vực
`home`).

> ⚠️ **Bắt buộc dùng shape `VM.Standard.A1.Flex` (4 OCPU + 12 GB RAM).**
> Shape `E2.1.Micro` chỉ có 1 GB RAM, SQL Server sẽ bị OOM-killed.
> A1.Flex vẫn thuộc Always Free (tối đa 4 OCPU + 24 GB RAM).

### 2.1. Tạo VM

1. <https://cloud.oracle.com/> → tạo tài khoản miễn phí (cần thẻ visa,
   không bị tính phí nếu chọn đúng "Always Free Eligible").
2. **Create → Instance** → image **Oracle Linux 9 (Always Free Eligible)**,
   shape **VM.Standard.A1.Flex (Always Free Eligible)** với
   **4 OCPU + 12 GB RAM**.
3. Tạo **VCN** với public subnet, và **Security List** mở:
   - TCP 22 (SSH) — giới hạn source về IP của bạn.
   - TCP 80 + 443 (HTTP/HTTPS).
4. SSH vào VM bằng key pair đã tải về.

### 2.2. Chạy script cài đặt tự động

Script làm hết: Docker → SQL Server 2022 + ODBC 18 → tạo database
`jellyvale` + user `gacha_app` → Caddy → file `.env` → Docker Compose →
khởi động container.

```powershell
# Trên máy Windows
scp -i ssh-key-oc.key d:\web-gacha\web-gacha\deploy\setup_vps.sh ubuntu@<PUBLIC-IP>:~/jellyvale-deploy/
```

```bash
# Trên VPS
cd ~/jellyvale-deploy
SA_PASSWORD='MatKhauSqlServerManh' \
APP_DB_PASSWORD='MatKhauChoGachaApp' \
PIKA_API_KEY='<your-pika-api-key>' \
PIKA_SERVER_UUID='de021d06' \
ADMIN_USERS='hhh21' \
ADMIN_PASSWORD='Admin@admin' \
bash setup_vps.sh
```

Script có thể chạy lại nhiều lần, không làm hỏng cái gì đã có.

### 2.3. Nạp dữ liệu

```powershell
# Trên máy Windows
scp -i ssh-key-oc.key d:\web-gacha\web-gacha\jellyvale_full.sql ubuntu@<PUBLIC-IP>:/srv/jellyvale/
```

```bash
# Trên VPS
sudo bash -c '/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$(cat /srv/jellyvale/.sa_password)" -C -d jellyvale -i /srv/jellyvale/jellyvale_full.sql'
```

### 2.4. Build & push image

Trên máy Windows của bạn (cần cài Docker Desktop):

```powershell
cd d:\web-gacha\web-gacha
$token = "ghp_xxxxxxxxxxxx"
$token | docker login ghcr.io -u <TEN-GITHUB-CUA-BAN> --password-stdin
bash deploy/build_push.sh <TEN-GITHUB-CUA-BAN>
```

Rồi trên VPS:

```bash
cd /srv/jellyvale
sudo docker compose pull
sudo docker compose up -d
curl http://127.0.0.1:8080/health
```

### 2.5. HTTPS miễn phí với Caddy

Caddy đã được cài sẵn bởi script. Tạo A record trỏ về IP VPS rồi chạy
lại script với `DOMAIN`:

```bash
cd ~/jellyvale-deploy
DOMAIN='gacha.jellyvale.vn' bash setup_vps.sh
```

Caddy tự lấy chứng chỉ Let's Encrypt và tự renew.

> Chi tiết từng bước, xử lý sự cố, bảo mật: xem
> [`deploy/HUONG_DAN_ORACLE_VPS.md`](deploy/HUONG_DAN_ORACLE_VPS.md).

---
## 3. PHƯƠNG ÁN C — Render / Railway / Fly.io (cần SQL Server ở đâu đó)

Chỉ dùng được khi bạn **đã có** SQL Server trên internet. Với SQL Server
trên máy nhà, bạn phải mở port 1433 ra ngoài — **không khuyến nghị** vì
SQL Server mặc định không an toàn khi lộ ra internet.

Cách làm đúng (nếu vẫn muốn):

1. **Render** → New → Blueprint → trỏ vào repo GitHub có `render.yaml`.
2. Render đọc `render.yaml`, build Docker image, chạy service `free`.
3. Trong Dashboard, điền các biến `sync: false`:
   `SQL_SERVER`, `SQL_USER`, `SQL_PASSWORD`, `PIKA_API_KEY`,
   `PIKA_SERVER_UUID`, `ADMIN_USERS`, `ADMIN_PASSWORD`.
4. Health check: `/health`.

**Giới hạn gói free:**
- Render Free: ngủ sau 15 phút không có traffic, 750 giờ/tháng,
  **mất dữ liệu khi ngủ** (không có persistent disk → `gacha.json` mất!).
- Railway Free: 500 giờ/tháng credit.
- Fly.io Free: có volume persistent được, nhưng cần thẻ visa.

> ⚠️ Vấn đề `gacha.json`: file này lưu cấu hình shop (case, tỉ lệ RTP).
> Trên nền tảng không có persistent disk, mỗi lần restart sẽ mất cấu
> hình đã sửa trong admin console. Nếu dùng Render Free, hãy dùng
> **phương án A** hoặc **B**.

---

## 4. PHƯƠNG ÁN D — playit.gg / ngrok (test nhanh)

Không cần domain, không cần account Cloudflare:

```powershell
winget install --id playit.gg
playit
```

Hoặc ngrok:

```powershell
winget install --id ngrok.ngrok
ngrok config add-authtoken <TOKEN>
ngrok http 8080
```

Dùng cho demo/test, **không** dùng cho production (URL đổi, không có
WAF).

---

## 5. Những thay đổi trong code để phục vụ deploy

Những thay đổi này **đã được áp dụng** trong code:

| Thay đổi | File | Vì sao |
|---|---|---|
| `SQL_USER` / `SQL_PASSWORD` / `SQL_PORT` / `SQL_DRIVER` / `SQL_ENCRYPT` / `SQL_TRUST_SERVER_CERTIFICATE` | `app/config.py` | Windows integrated login không tồn tại trên Linux/Docker |
| `_conn_str()` dựng connection string theo 2 nhánh | `app/store.py` | Nhánh SQL login cho container cloud |
| `GET /health` | `app/main.py` | Health check cho Render/Railway/Fly + báo trạng thái DB |
| `store.init()` không raise khi DB lỗi | `app/store.py` | Container không crash-loop khi SQL Server chưa sẵn sàng |
| `@app.exception_handler(pyodbc.Error)` → 503 | `app/main.py` | 503 = "lát quay lại"; 500 khiến platform restart container |
| `Dockerfile` (cài `msodbcsql18`) | `Dockerfile` | pyodbc cần ODBC driver |
| `docker-compose.yml` | — | Test container build tại máy |
| `Procfile`, `render.yaml`, `railway.json`, `fly.toml` | — | Deploy 1-click |
| `start_prod.bat` | — | Chạy production không `--reload` |
| `.gitignore` / `.dockerignore` | — | `.env` không lên GitHub, không vào image |
| `GACHA_FILE` cấu hình được qua env | `app/config.py`, `app/gacha.py` | Mount volume trên VPS để không mất cấu hình shop khi restart |
| `deploy/entrypoint.sh` | — | Seed `gacha.json` vào volume lần đầu, chạy app non-root |
| `deploy/setup_vps.sh` | — | Cài đặt VPS Oracle tự động (Docker + SQL Server + Caddy) |
| `deploy/build_push.sh`, `deploy/upload_data.sh` | — | Build/push image + nạp dữ liệu lên VPS |

---

## 6. Checklist trước khi lên online

- [ ] `SESSION_SECRET` **không** phải giá trị mặc định (app tự cảnh báo)
- [ ] `SESSION_HTTPS_ONLY=auto` (chỉ khi đã có HTTPS)
- [ ] `ADMIN_PASSWORD` đã đổi, mạnh
- [ ] `PIKA_API_KEY` không nằm trong repo (chỉ trong Dashboard của
      platform / file `.env` trên VPS)
- [ ] SQL dùng **SQL login riêng** (`gacha_app`), không dùng `sa`
- [ ] Firewall chỉ mở 80/443 (và 22 giới hạn IP của bạn)
- [ ] `GACHA_DRY_RUN=false` để tiền thật chạy
- [ ] Đã test đăng nhập + mở rương + bán đồ trên domain thật

---

## 7. Tóm tắt — nên chọn gì?

**Chọn A (Cloudflare Tunnel)** nếu bạn muốn:
- 0đ, không cần Docker, không cần đụng vào SQL Server
- Dùng ngay trong 15 phút
- Web chỉ chạy khi máy chủ Minecraft bật (thường 24/7 vì server game
  luôn bật)

**Chọn B (Oracle Free VPS)** nếu bạn muốn:
- Web chạy 24/7 độc lập với máy bạn
- Domain + HTTPS thật, hiệu năng ổn định hơn

Cả hai đều dùng chung `PIKA_API_KEY` và `ADMIN_PASSWORD` hiện tại, nên
chuyển đổi qua lại không tốn công.
