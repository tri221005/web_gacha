# HƯỚNG DẪN CHI TIẾT DỰ ÁN JELLYVALE GACHA (WEB GACHA MINECRAFT)

> **Cập nhật ngày:** 23/11/2026  
> **Phiên bản:** v2.0 — Phong cách tươi sáng, Hỗ trợ Mở nhiều rương (1x, 2x, 3x, 4x, 5x), 7 Rương hoàn chỉnh & Đổi theme Sáng/Tối.

---

## 1. Tổng Quan & Cảm Hứng Thiết Kế

Dự án được xây dựng lấy cảm hứng trực tiếp từ nền tảng **CaseForge** (mở hòm CS2 chuyên nghiệp), nhưng được thiết kế lại toàn bộ bằng **Python (FastAPI) + Microsoft SQL Server** để phù hợp hoàn hảo với hệ sinh thái server **Minecraft (Nexo / ItemsAdder / ExcellentEconomy / AuthMe)**:
- **Siêu nhẹ & Tối ưu**: Thay vì tốn 2.5GB – 4GB RAM như bản gốc CaseForge (chạy Next.js + NestJS + Redis + Postgres + Worker), web này chỉ tiêu thụ **~50MB RAM**, khởi động trong tích tắc.
- **Không còn SQLite**: Toàn bộ ledger gacha (ví, pulls, túi đồ, battle) nằm trong **SQL Server** (`jellyvale` database, các bảng tiền tố `gacha_`). Dữ liệu server Minecraft được tải về từ **PikaMC API** và hợp nhất vào một file `.sql` duy nhất.
- **Phong cách Tươi Sáng**: Thiết kế nền sáng dịu mắt, thẻ trắng viền tinh xảo, hiệu ứng vàng kim bắt mắt chuẩn game phiêu lưu, có sẵn nút chuyển đổi qua lại giữa giao diện Tươi Sáng và Ban Đêm (☀️/🌙).
- **Core Loop Hoàn Chỉnh**: Mở rương (1x–5x) ➔ Túi đồ ➔ Bán lấy Coin ➔ Nâng cấp (Upgrade) ➔ Case Battle với Bot ➔ Vòng quay may mắn (Daily Bonus).

---

## 2. Hệ Thống 7 Rương Mặc Định & Cấu Trúc

Toàn bộ thông số rương, tỷ lệ rơi (`weight`) và giá trị Coin nằm trong file `gacha.json`:

| ID Rương | Tên Rương | Giá Mở | Đồ Nổi Bật |
| :--- | :--- | :---: | :--- |
| `jelly-starter` | **Rương Jelly Starter** | 5.000 Coin | Bụi vàng, Táo vàng, Túi Coin, Phôi Netherite, Jackpot Starter |
| `jelly-magic` | **Rương Ma Pháp** *(Mới)* | 15.000 Coin | Thạch anh tím, Ngọc Ender, Đinh ba Thủy thần, Trượng Ma Pháp |
| `jelly-elite` | **Rương Elite** | 25.000 Coin | Kim cương, Sách Elite, Totem bất tử, Cánh Elytra, Mangekyo |
| `jelly-vault` | **Rương Vault** | 50.000 Coin | Khối Netherite, Mangekyo, Trứng rồng, Vương miện Jelly |
| `jelly-nether` | **Rương Hỏa Ngục Nether** *(Mới)* | 75.000 Coin | Que quỷ lửa, Đầu lâu Wither, Hỏa Kiếm Nether, Sao Địa Ngục |
| `jelly-celestial` | **Rương Thiên Giới** *(Mới)* | 150.000 Coin | Lông vũ Thiên Sứ, Cánh Ánh Kim, Cung Ánh Sáng, Cầu Vũ Trụ |
| `jelly-jackpot` | **Rương Hoàng Gia VIP** *(Mới)* | 300.000 Coin | Khối Kim Cương, Đầu Rồng, Vương trượng, Lõi Thần & Kho Báu Bất Tận |

---

## 3. Tính Năng Mở Đa Rương (1x, 2x, 3x, 4x, 5x)

- **Bộ nút Preset**: Cho phép người chơi chọn nhanh số lượng mở: `×1`, `×2`, `×3`, `×4`, `×5`.
- **Hiệu ứng trực quan**:
  - Khi chọn **×1**: Dải quay Roulette ngang (Horizontal) truyền thống.
  - Khi chọn **×2 – ×5**: Hệ thống tự động chuyển sang **Đa dải cuộn dọc (Multi Vertical Reels)** xếp hàng ngang. Các dải dừng so le 260ms tạo cảm giác hồi hộp như các sàn gacha lớn.
- **Bảng tổng kết Drop (Drop Results)**:
  - Hiển thị đầy đủ thông số: **Đã chi**, **Tổng nhận**, **Chênh lệch lãi/lỗ (+/-)**.
  - Mỗi món rơi ra có thẻ riêng hiển thị ảnh, tên, giá bán và nút **"Bán"** lẻ.
  - Nút **"Bán tất cả (X món)"** giúp thanh lý nhanh toàn bộ để nhận lại Coin ngay tại trang mở rương.

---

## 4. Hướng Dẫn Thay Đổi & Thêm Ảnh Rương / Vật Phẩm

Hệ thống được thiết kế với cơ chế **Auto Image Resolver**, tuyệt đối **không hard-code đường dẫn ảnh**.

### 4.1. Thư mục chứa ảnh
- **Ảnh rương**: Nằm trong `app/static/cases/`
- **Ảnh vật phẩm**: Nằm trong `app/static/items/`

### 4.2. Quy tắc đặt tên file
Tên file ảnh phải trùng khớp chính xác với `id` khai báo trong `gacha.json`:
- Ví dụ rương `jelly-magic` ➔ file ảnh là `jelly-magic.png` (hoặc `.svg`, `.webp`, `.jpg`).
- Ví dụ item `inferno_sword` ➔ file ảnh là `inferno_sword.png`.

### 4.3. Thứ tự ưu tiên định dạng
`png` ➔ `webp` ➔ `jpg` ➔ `jpeg` ➔ `svg`.  
*(Hiện tại dự án đã tạo sẵn đầy đủ ảnh vector `.svg` cho 100% rương và item mới. Sau này bạn chỉ cần thả ảnh `.png` đẹp hơn vào là web sẽ tự động nhận diện file `.png` thay thế file `.svg`, không cần sửa code).*

### 4.4. Bảng mã màu phẩm cấp (Rarity)
- `consumer` / `common`: `#b0c3d9` (Trắng / Xám nhạt)
- `industrial`: `#5e98d9` (Xanh da trời)
- `milspec` / `uncommon`: `#4b69ff` (Xanh dương)
- `restricted` / `rare`: `#8847ff` (Tím ma thuật)
- `classified` / `epic`: `#d32ce6` (Hồng cánh sen)
- `covert`: `#eb4b4b` (Đỏ rực rỡ)
- `extraordinary` / `legendary`: `#e4ae39` (Vàng kim / Hổ phách)

---

## 5. Luu tru du lieu: SQL Server

Web **khong dung SQLite nua**. Toan bo du lieu nam trong Microsoft SQL Server.

### 5.1. Nap du lieu server Minecraft
File `jellyvale_full.sql` (~38 MB, 86 bang) chua toan bo du lieu 15 plugin Minecraft + ledger gacha, da chuyen doi sang **T-SQL**. Nap vao database:

```cmd
sqlcmd -S localhost -E -d jellyvale -i jellyvale_full.sql
```

> File duoc ghi bang **UTF-8 kem BOM** nen tieng Viet khong bi loi font khi nap.

Nguon du lieu duoc tai truc tiep tu PikaMC API roi xuat ra file `.sql`:

```cmd
python tools\export_sqlserver.py                 # tai moi tu PikaMC + xuat file .sql
python tools\export_sqlserver.py --no-download   # xuat lai tu file da tai
```

### 5.2. Ledger gacha (bang `gacha_*`)
Ung dung doc/ghi ledger truc tiep tren SQL Server qua `app/store.py` (ket noi `pyodbc`, mot connection dung chung co transaction + tu reconnect).

Neu database chua co bang gacha:

```cmd
python tools\init_gacha_schema.py
```

### 5.3. Cau hinh ket noi
Trong `.env`:

```
SQL_SERVER=localhost
SQL_DATABASE=jellyvale
```

### 5.4. Luu y khi host
Vi dung SQL Server, web can mot instance SQL Server chay cung may (hoac trong cung mang noi bo). Render / Koyeb / Vercel (serverless) **khong phu hop** voi kien truc nay — hay dung VPS rieng hoac Oracle Cloud Always Free.

### 5.5. Cloudflare Tunnel (khuyen dung neu host tai may chu/VPS)
Neu ban da co may tinh chay server Minecraft hoac VPS Windows/Linux:
1. Chay web ngay tren may chu qua lenh: `start.bat`.
2. Cai dat **Cloudflare Tunnel (mien phi 100%)**:
   - Tro domain (vi du `gacha.yourserver.com`) ve port `8080` noi bo.
   - Co ngay ket noi **HTTPS**, tuong lua chong DDoS manh me cua Cloudflare, khong can mo port modem (No Port Forwarding).

---

## 6. Hướng Dẫn Chạy & Cấu Hình

### Khởi động dự án trên máy:
Nhấp đúp chuột vào file:
```cmd
start.bat
```
Truy cập: `http://127.0.0.1:8080/gacha`

### Cấu hình file `.env`:
- `GACHA_DRY_RUN=true`: Chế độ an toàn / thử nghiệm. Người chơi nạp tiền ảo (seed 250.000 Coin) trên web để test toàn bộ tính năng mà không ảnh hưởng tới kinh tế server thật.
- Khi muốn kết nối trừ Coin in-game thật:
  1. Thêm API key PikaMC vào `PIKA_API_KEY`.
  2. Đặt `GACHA_DRY_RUN=false`.
  3. Khoi dong lai `start.bat`.

---

## 7. Bang Dieu Khien Admin

Trang `/admin` la bang dieu khien day dung cho nguoi quan tri.

### 7.1. Dang nhap admin

Co **hai cach**, dung nhieu theo nhu cau:

**Cach 1 - mat khau rieng cho bang dieu khien (khuyen nghi)**

Dat trong `.env`:

```
ADMIN_USERS=hhh21
ADMIN_PASSWORD=mat-khau-cua-ban
```

Sau do vao `http://127.0.0.1:8080/admin/login`, nhap ten + mat khau tren.
Mat khau nay **khong lien quan** den mat khau trong game, nen doi mat khau Minecraft
hay doi ten nhan vat khong lam mat quyen admin.

**Cach 2 - dung mat khau Minecraft**

Bo trong `ADMIN_PASSWORD`. Ten admin phai kem mat khau Minecraft de vao,
trung voi cach dang nhap game binh thuong.

> Ten tai khoan `ADMIN_USERS` **khong bao gio duy du**. Neu `ADMIN_PASSWORD` rong,
> he thong van kiem tra mat khau Minecraft. Neu `ADMIN_PASSWORD` co gia tri,
> mat khau rieng la thu tu vien duy nhat.

### 7.1b. Dong bo admin voi server Minecraft

Danh sach admin cua web **tu dong dong bo hai chieu** voi nhom LuckPerms
`admin` tren server Minecraft:

- **Server -> web**: web doc danh sach nhom `admin` tren server. Ai co quyen
  do thi dang nhap duoc `/admin/login` ngay, du khong co trong `.env`.
- **Web -> server**: cap hoac go quyen trong tab "Doi ngu admin" se chay
  `lp user <ten> parent add|remove admin` tren server that, roi cap nhat danh
  sach web. Server la **nguon su that**: khi server khong phan hoi, thay doi
  bi tu choi thay vi tao ra hai danh sach lech nhau.

Dat trong `.env` neu can doi:

```
ADMIN_GROUP=admin          # nhom LuckPerms duoc coi la admin
ADMIN_SYNC_SECONDS=30      # do lai danh sach sau bao lau (giay)
```

> LuckPerms luu du lieu bang H2 chu phai SQLite, nen panel khong doc truc tiep
> duoc. Web dung `lp export` de lay danh sach, roi tai file gzip xuong.
> File export duoc xoay ten theo timestamp va xoa ngay sau khi dung, nen
> thu muc plugin khong bi day file.

> Khi server Minecraft khong phan hoi, web van chay binh thuong bang danh
> sach trong `.env` va bang `gacha_admins`. Tinh nang dong bo thi bao loi
> nhung khong khoa bang dieu khien.

### 7.2. Nam tab

| Tab | Noi dung |
| :--- | :--- |
| **Tong quan** | Thong so gacha, do hiem, top nguoi chi nhieu, 40 luot gan nhat |
| **Nguoi choi** | Danh sach vi (tim theo ten), loc bot |
| **Ruong** | Sua gia, tỉ le, do hiem va gia tri cua tung mon; them / xoa ruong |
| **Giao dich** | Lich su giao dich cua moi nguoi, loc theo loai |
| **Battle** | Danh sach tran, ket thuc tran, huy tran va hoan Coin |
| **Doi ngu admin** | Dong bo danh sach admin voi nhom LuckPerms tren server |
| **Nhat ky** | Moi thao tac cua admin: ai, lam gi, cho ai, bao nhieu |

### 7.3. Hinh thuc quan tri

Tren `/admin/player/<ten>` co ho so cua tung nguoi choi:

- **Cong / tru Coin**: lenh `eco give` / `eco take` chay tren server Minecraft thật, khong phai so du ao. Web doc lai so du sau khi lenh chay, nen khong the "cong o" ma server khong nhan.
- **Dat vi**: tinh chenh lech giua so du server va so du mong muon, roi gui lenh len server. Ket qua cuoi cung khop tren ca hai noi.
- **Cam tai khoan**: nguoi bi cam van dang nhap duoc, nhung moi hanh dong quay ruong, ban do, vao battle deu bi tu choi. Admin khong the tu cam chinh minh.
- **Huy battle**: hoan Coin ve **server** cho tung nguoi choi, khong chi sua so noi bo.

### 7.4. Sua ruong

Sua ruong ghi thang vao `gacha.json`. File cu duoc giu lai o `gacha.json.bak`, va file duoc ghi qua file tam nen server khong bao gio giap bang mot `gacha.json` rong.

RTP ly thuyet cua moi ruong duoc tinh tu bang `weight` va `coin`, hien ngay tren tieu de ruong de doi chieu voi do chenh lech thuc te trong tab Tong quan.

Sua xong khong can restart: web doc lai file theo thoi diem sua.

### 7.5. Cac bang phu

`gacha_bans` (danh sach cam), `gacha_admin_log` (nhat ky admin) va
`gacha_admins` (danh sach admin cua web, dong bo voi server). Neu database cu
chua co cac bang nay, chay:

```cmd
python tools\init_bans_table.py
```

Khong co bang nay thi chuc nang tu tat, phan con lai van chay binh thuong.

### 7.6. Bao mat da dung

- Moi route admin deu qua `require_admin()`, nen route moi khong the quen check quyen.
- Moi thao tac ghi tien duoi co kiem tra CSRF.
- So sanh mat khau bang `hmac.compare_digest` de khong lo thoi gian phan hoi.
- Admin khong tu cam chinh minh, nen khong ket truc voi bang dieu khien.
- Moi thay doi tien deu duoc ghi vao tab Nhat ky.

---

## 8. Chuyen Sang May Moi

Xem **`HUONG_DAN_CAI_DAT_MOI.md`** de biet can copy file nao va cai dat ra sao.

Tat nhanh nhat:

```cmd
python tools\make_portable.py
```

Sinh ra `web-gacha-portable.zip` chua toan bo ma nguon (93 file, ~126 KB).
Giai nen, tao `.env`, nap database SQL Server roi chay `start.bat`.

> File `jellyvale_full.sql` (40 MB) **khong** nam trong zip. Neu may moi chua co
> database thi copy rieng file nay va nap bang `sqlcmd`.

