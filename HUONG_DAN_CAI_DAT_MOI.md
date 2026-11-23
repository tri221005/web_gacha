# CÀI ĐẶT TRÊN MÁY MỚI

Tài liệu này dành cho việc chuyển web gacha sang một máy tính khác.

---

## 1. File cần copy

### Bắt buộc

| File / Thư mục | Vì sao |
| :--- | :--- |
| `app/` | Toàn bộ mã nguồn (Python, template, ảnh, CSS, JS) |
| `requirements.txt` | Danh sách thư viện Python cần cài |
| `.env` | Cấu hình thật: API key PikaMC, tài khoản admin, kết nối SQL Server |
| `gacha.json` | Cấu hình 7 rương: giá, tỉ lệ, độ hiếm, giá trị vật phẩm |
| `start.bat` | Script khởi động (tạo venv + cài thư viện + chạy web) |

### Tùy chọn

| File / Thư mục | Vì sao |
| :--- | :--- |
| `tools/` | Script kiểm thử và công cụ. Không bắt buộc để web chạy |
| `jellyvale_full.sql` | Schema SQL Server (40 MB). Chỉ cần khi máy mới **chưa có** database |
| `HUONG_DAN_DU_AN.md` | Tài liệu dự án |
| `.env.example` | Mẫu cấu hình, để tham khảo khi tạo `.env` mới |

### Không cần copy

| File / Thư mục | Vì sao |
| :--- | :--- |
| `.venv/` | Venv gắn với đường dẫn cũ. Máy mới sẽ tự tạo lại |
| `downloads/` | Database plugin tải từ server, chỉ dùng cho tool export SQL |
| `caseforge-main/`, `Nexo/` | Mã nguồn tham khảo, web không dùng |
| `data/` | Rỗng, web dùng SQL Server |
| `*.log`, `*.err`, `__pycache__/`, `*.zip`, `*.bak` | Log và file tạm |
| `shots/`, `tools/_shots/` | Ảnh chụp màn hình |

> **Cách nhanh:** đã có sẵn gói `web-gacha-portable.zip` (92 file, ~120 KB).
> Giải nén ra là xong phần mã nguồn.

```cmd
python tools\make_portable.py
```

---

## 2. Cài đặt trên máy mới

### Bước 1 — Cài đặt phần mềm nền

| Phần mềm | Bắt buộc | Ghi chú |
| :--- | :---: | :--- |
| Python 3.10 – 3.12 | ✅ | Kiểm tra: `python --version` |
| Microsoft SQL Server | ✅ | Hoặc SQL Server Express (miễn phí) |
| ODBC Driver 18 for SQL Server | ✅ | Bắt buộc cho `pyodbc`. Tải tại [learn.microsoft.com/odbc](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) |
| SQL Server Management Studio (SSMS) | ⬜ | Tiện để quản lý database |
| PikaMC API key | ✅ | Lấy từ [hub.pikamc.vn](https://hub.pikamc.vn), cần quyền `control.console` + `files.query-raw` |

### Bước 2 — Giải nén mã nguồn

Giải nén `web-gacha-portable.zip` vào thư mục, ví dụ `D:\web-gacha\web-gacha`.

### Bước 3 — Tạo và nạp database

Chỉ làm nếu máy mới **chưa có** database `jellyvale`.

**Cách A — có `jellyvale_full.sql`:**

```cmd
sqlcmd -S localhost -E -d jellyvale -i jellyvale_full.sql
```

**Cách B — dùng SSMS:** mở file → chạy.

Sau khi nạp, kiểm tra các bảng `gacha_*` đã có:

```cmd
sqlcmd -S localhost -E -d jellyvale -Q "SELECT COUNT(*) FROM sys.tables WHERE name LIKE 'gacha[_]%'"
```

Kết quả phải lớn hơn 0.

**Bước 3b — Tạo bảng phụ (bắt buộc)**

```cmd
python tools\init_bans_table.py
```

Tạo `gacha_bans`, `gacha_admin_log` và `gacha_admins`. Thiếu bảng thì tính năng cấm, nhật ký và đồng bộ admin tự tắt, phần còn lại vẫn chạy.

### Bước 4 — Tạo file `.env`

Copy `.env.example` thành `.env`, rồi sửa cho đúng:

```env
SESSION_SECRET=doi-chuoi-ngau-nhien-64-ky-tu
HOST=127.0.0.1
PORT=8080

PIKA_BASE_URL=https://hub.pikamc.vn
PIKA_API_KEY=api-key-cua-ban
PIKA_SERVER_UUID=de021d06
PIKA_AUTHME_DB=/plugins/AuthMe/authme.db
PIKA_ECONOMY_DB=/plugins/ExcellentEconomy/data.db

ADMIN_USERS=hhh21
ADMIN_PASSWORD=mat-khau-admin-cua-ban
ADMIN_GROUP=admin
ADMIN_SYNC_SECONDS=30

GACHA_DRY_RUN=false
SQL_SERVER=localhost
SQL_DATABASE=jellyvale
```

| Biến | Ý nghĩa |
| :--- | :--- |
| `SESSION_SECRET` | Chuỗi ngẫu nhiên 64 ký tự. **Bắt buộc đổi** — ai biết là giả được cookie đăng nhập |
| `PIKA_API_KEY` | API key từ hub.pikamc.vn |
| `PIKA_SERVER_UUID` | UUID server Minecraft, `de021d06` |
| `ADMIN_USERS` | Tài khoản admin chắc chắn (danh sách này luôn được tính) |
| `ADMIN_PASSWORD` | Mật khẩu riêng cho bảng điều khiển. Bỏ trống thì dùng mật khẩu Minecraft |
| `ADMIN_GROUP` | Nhóm LuckPerms trên server được coi là admin |
| `GACHA_DRY_RUN` | `false` = dùng Coin thật. `true` = chỉ test, không trừ tiền |
| `SQL_SERVER` / `SQL_DATABASE` | Kết nối SQL Server |

### Bước 5 — Cài thư viện và chạy

```cmd
start.bat
```

Script sẽ tự tạo `.venv`, cài thư viện rồi chạy web ở `http://127.0.0.1:8080`.

Chạy tay từng bước nếu muốn:

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```

---

## 3. Kiểm tra sau khi cài

```cmd
python tools\test_admin.py
python tools\smoke_test.py
```

Nếu SQL Server kết nối được, app khởi động mà không báo lỗi là ổn.

Kiểm tra nhanh:

| Kiểm tra | Kết quả mong đợi |
| :--- | :--- |
| Mở `http://127.0.0.1:8080/` | Tự chuyển tới `/gacha` |
| `/login` | Đăng nhập bằng tài khoản Minecraft |
| `/admin/login` | Đăng nhập bằng `ADMIN_USERS` + `ADMIN_PASSWORD` |
| Tab "Đội ngũ admin" | Hiện danh sách admin trên server |

---

## 4. Cần SQL Server không?

Có. Toàn bộ ledger gacha nằm trong SQL Server:

- `gacha_wallets` — số dư
- `gacha_pulls`, `gacha_drops` — lịch sử mở rương
- `gacha_inventory` — túi đồ
- `gacha_tx` — sổ giao dịch
- `gacha_battles`, `gacha_battle_players` — battle
- `gacha_bans`, `gacha_admin_log`, `gacha_admins` — quản trị

**Chuyển database sang máy mới:**

```cmd
sqlcmd -S localhost -E -d jellyvale -Q "BACKUP DATABASE jellyvale TO DISK='C:\backup\jellyvale.bak' WITH FORMAT"
```

Rồi restore trên máy mới:

```cmd
sqlcmd -S localhost -E -Q "RESTORE DATABASE jellyvale FROM DISK='C:\backup\jellyvale.bak' WITH MOVE 'jellyvale' TO 'C:\SQLData\jellyvale.mdf'"
```

> Nếu máy mới đã có database rồi thì **không cần** nạp `jellyvale_full.sql` — làm vậy sẽ
> ghi đè dữ liệu người chơi đang có.

---

## 5. Lỗi thường gặp

| Lỗi | Nguyên nhân | Cách sửa |
| :--- | :--- | :--- |
| `Login failed for user` | Sai thông tin SQL Server | Kiểm tra `SQL_SERVER`, `SQL_DATABASE`; đảm bảo đã bật **Windows Authentication** hoặc đúng tài khoản |
| `IM002` / `Data source name not found` | Chưa cài ODBC Driver 18 | Cài driver, xem Bước 1 |
| `Khong tim thay bang gacha_` | Chưa nạp schema | Chạy `jellyvale_full.sql`, rồi `init_bans_table.py` |
| `Chua cau hinh PIKA_API_KEY` | `.env` thiếu hoặc sai tên | Kiểm tra file `.env` nằm cùng cấp `app/` |
| `API key PikaMC khong hop le` | Key sai hoặc hết hạn | Tạo key mới trên hub.pikamc.vn |
| `API key thieu quyen control.console` | Key thiếu quyền | Bật quyền `control.console` rồi tạo lại key |
| Port 8080 đã bị chiếm | Chương trình khác dùng port | Đổi `PORT` trong `.env`, hoặc `netstat -ano \| findstr 8080` rồi `taskkill /PID <pid> /F` |
| Đăng nhập admin báo "error=rate" | Thử sai quá 8 lần trong 10 phút | Chờ 10 phút hoặc restart server |

---

## 6. Chạy nhiều máy cùng lúc

Mỗi máy dùng **SQL Server riêng** hoặc cùng một server nhưng **database riêng**:

```env
SQL_DATABASE=jellyvale_may2
```

Còn `SESSION_SECRET` thì **phải khác nhau** giữa các máy, nếu không cookie đăng
nhập của máy này sẽ dùng được trên máy kia.
