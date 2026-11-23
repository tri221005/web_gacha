# web_gacha

Web Gacha (case opening) cho server Minecraft — đồng bộ trực tiếp với PikaMC API.

> **JellyVale Gacha** — Python (FastAPI) · Microsoft SQL Server · Vanilla JS

---

## Tính năng

| Nhóm | Mô tả |
| :--- | :--- |
| **Rương may mắn** | 7 rương, mở 1x–5x, dải cuộn roulette ngang / đa dải dọc, bảng tổng kết lãi/lỗ |
| **Ví Coin** | Ledger nội bộ trong SQL Server, tự đồng bộ với số dư thật trên server Minecraft |
| **Túi đồ** | Bán lẻ / bán tất cả, mọi giao dịch ghi log (`gacha_tx`) |
| **Nâng cấp** | Upgrade vật phẩm theo bậc độ hiếm |
| **Case Battle** | Đấu với bot, có hoàn Coin kèm nếu bị hủy |
| **Bonus hằng ngày** | Vòng quay may mắn, chống nhận trùng ngày |
| **Bảng điều khiển Admin** | Quản lý ví, rương, giao dịch, battle, nhật ký, đồng bộ nhóm LuckPerms |
| **Realtime** | Header tự cập nhật số dư qua polling, không cần F5 |

## Công nghệ

- **Backend**: FastAPI · Jinja2 · pyodbc (SQL Server) · httpx
- **Frontend**: HTML/CSS/JS thuần, không framework, không build step
- **Database**: Microsoft SQL Server (`jellyvale`, các bảng tiền tố `gacha_`)
- **Dữ liệu server**: PikaMC API (AuthMe, ExcellentEconomy) · LuckPerms (đồng bộ admin)

Dự án **không dùng SQLite** và **không dùng Redis** — RAM khoảng 50 MB.

## Cấu trúc

```
app/
  main.py         # FastAPI app, routes web + JSON API
  store.py        # Truy cập SQL Server, transaction, hàm nguyên tử
  game.py         # Luật game: mở rương, bán đồ, bonus, battle
  gacha.py        # Đọc/ghi cấu hình rương (gacha.json)
  pika.py         # Client PikaMC API + console command
  luckperms.py    # Đồng bộ nhóm admin hai chiều
  bots.py         # Người chơi bot cho battle
  session.py      # Middleware session thích ứng HTTP/HTTPS
  config.py       # Đọc cấu hình từ .env
  templates/      # Jinja2 templates
  static/         # CSS, JS, ảnh rương & vật phẩm
tools/            # Script bảo trì, export SQL, test tự động
deploy/           # Script cài đặt VPS, hướng dẫn Oracle Cloud
```

## Chạy dự án

```cmd
pip install -r requirements.txt
copy .env.example .env      # sửa lại cho máy của bạn
python tools\init_gacha_schema.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Trên Windows có thể dùng `start.bat`.

Truy cập `http://127.0.0.1:8080/gacha`.

## Biến môi trường

| Biến | Ý nghĩa |
| :--- | :--- |
| `SQL_SERVER` / `SQL_DATABASE` | Kết nối SQL Server |
| `SQL_USER` / `SQL_PASSWORD` | Tài khoản SQL (bắt buộc trên Linux/Docker) |
| `PIKA_API_KEY` | API key PikaMC |
| `PIKA_SERVER_UUID` | UUID server Minecraft |
| `SESSION_SECRET` | Khóa ký cookie session |
| `SESSION_HTTPS_ONLY` | `auto` / `true` / `false` — tự thêm cờ `Secure` khi qua HTTPS |
| `ADMIN_USERS` | Danh sách tài khoản admin (phân tách bằng dấu phẩy) |
| `ADMIN_PASSWORD` | Mật khẩu riêng cho bảng điều khiển admin |
| `ADMIN_GROUP` | Nhóm LuckPerms được coi là admin |
| `GACHA_DRY_RUN` | `true` = chế độ thử nghiệm, không đụng tiền thật |

Xem `.env.example` để có danh sách đầy đủ.

## Nhập dữ liệu server

```cmd
python tools\export_sqlserver.py                 # tải từ PikaMC rồi xuất .sql
sqlcmd -S localhost -E -d jellyvale -i jellyvale_full.sql
```

## Triển khai

`Dockerfile`, `docker-compose.yml`, `render.yaml` và `deploy/setup_vps.sh` đã có sẵn.
Hướng dẫn chi tiết: `DEPLOY_MIEN_PHI.md` và `deploy/HUONG_DAN_ORACLE_VPS.md`.

Vì dùng SQL Server nên cần một instance SQL Server chạy cùng máy — Render/Koyeb/Vercel
(serverless) không phù hợp. VPS riêng hoặc Oracle Cloud Always Free là lựa chọn hợp lý.

## Kiểm thử

```cmd
python tools\run_all_tests.py
```

Bao gồm test logic battle, test race condition, test audit log, test bảo mật,
test session cookie, test đồng bộ realtime và test UI với Playwright.

Lint:

```cmd
ruff check .
```

## Tài liệu

- `HUONG_DAN_DU_AN.md` — hướng dẫn chi tiết về game, rương và ảnh
- `DEPLOY_MIEN_PHI.md` — cách triển khai miễn phí
- `deploy/HUONG_DAN_ORACLE_VPS.md` — cài đặt lên Oracle VPS
