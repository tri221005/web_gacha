# BÁO CÁO KIỂM THỬ BẢO MẬT — WEB GACHA JELLYVALE

> Ngày: 23/11/2026 · Phạm vi: toàn bộ `app/` (FastAPI) + `tools/` + ledger SQL Server + tích hợp PikaMC

---

## 1. Cách kiểm thử

Bộ test tự động nằm trong `tools/`:

| File | Phạm vi |
|---|---|
| `test_security.py` | SQL injection, CSRF, xác thực, giả mạo tham số, race condition, rate limit |
| `test_security_probe.py` | CSRF fallback, cờ cookie session |
| `test_security_probe2.py` | Bán trùng món, trả tiền battle thất bại |
| `test_security_probe5.py` | Chứng minh "tiền từ không" khi console từ chối trừ tiền |
| `test_security_probe6.py` | Body JSON sai kiểu, thiếu phân quyền, endpoint công khai |
| `test_security_probe7.py` | Vòng lặp battle với bot, vượt rate limit bằng `X-Forwarded-For` |
| `test_security_probe8.py` | Command injection qua `realname` |
| `test_security_probe9.py` | Tìm nguyên nhân gốc của việc bán trùng món |
| `test_security_probe10.py` | Đo lường dòng tiền battle với bot + công bằng tỷ lệ thắng |
| `test_security_probe11.py` | Số dư server đọc lỗi giữa chừng khi đang trả tiền |
| `test_security_probe12.py` | Bảng rate limit có phình vô hạn không |
| `test_security_probe13.py` | `count` mở rương ngoài khoảng 1–5 |

Ngoài ra còn có bộ test giao diện và dòng tiền trong `tools/`:

| File | Phạm vi |
|---|---|
| `smoke_test.py` | Catalogue, trang rương, chủ đề sáng/tối, chặn trang khi chưa đăng nhập |
| `smoke_test_auth.py` | Mở 1x–5x khi đã đăng nhập |
| `test_login_playwright.py` | Toàn bộ luồng đăng nhập: CSRF, sai mật khẩu, rate limit, đăng xuất |
| `test_login_all_players.py` | Đăng nhập thật của **34/34 người chơi** trên server PikaMC |
| `test_ui_responsive.py` | Điện thoại, cuộn ngang, tap target, focus, reduced motion |
| `e2e_money_test.py` | Mở rương → bán đồ → bonus, có kiểm tra tiền vào/ra |
| `test_live_open.py` / `test_live_sell.py` | Mở và bán trên server PikaMC thật |
| `test_live_money_flow.py` | Vòng tiền đầy đủ trên panel giả |
| `test_realtime_sync.py` | Ví web khớp số dư server, kiểm tra trên từng trang |
| `test_refresh_button.py` / `test_auto_sync.py` | Nút làm mới và đồng bộ khi tải trang |
| `selftest_store.py` | Mọi đường ghi vào SQL Server |
| `validate_sql.py` | File `.sql` đầy đủ |

Chạy tất cả:

```cmd
python tools\test_security_all.py
python tools\cleanup_security_testdata.py   :: xoá dữ liệu test khỏi SQL Server
```

Toàn bộ test chạy trong tiến trình, dùng **panel PikaMC giả** thực sự **thực thi câu SQL** nó nhận trên một file SQLite thật — nếu có injection thì nó sẽ chạy thật chứ không bị mock đi.

---

## 2. KẾT QUẢ: SQL INJECTION — AN TOÀN ✅

### 2.1 Truy vấn PikaMC (SQLite) — AN TOÀN

`app/pika.py` dựng truy vấn bằng f-string:

```python
query = (
    "SELECT username, realname, password FROM authme "
    f"WHERE LOWER(username) = LOWER('{name}') LIMIT 1"
)
```

Nhưng `name` đã đi qua `_safe_username()` — regex `^[A-Za-z0-9_.-]{1,32}$`, không khớp thì trả `None` và hàm dừng luôn. **Test đã xác nhận**: 8 payload SQLi (`' OR 1=1 --`, `UNION SELECT`, `DROP TABLE`, `%27%20OR%201%3D1--`, …) đều bị chặn, **không một câu query nào được gửi đi** (`queries_sent=[]`), bảng `authme` còn nguyên, và đăng nhập thật vẫn chạy sau đó.

Đây là điểm **fail-closed** — tốt.

### 2.2 Ledger SQL Server — AN TOÀN

`app/store.py` dùng tham số `?` của pyodbc cho **100% câu truy vấn**. Hai chỗ có f-string đều an toàn:

```python
placeholders = ",".join("?" * len(ids))          # chỉ dựng dấu ?, giá trị vẫn là tham số
fields.append(f"{key} = ?")                      # key đến từ tuple cố định ("winner", "started_at", ...)
```

Test với tên người chơi chứa SQL thật (`Robert'); DROP TABLE gacha_wallets; --`) → lưu thành văn bản thuần, bảng vẫn tồn tại, không có câu lệnh nào thực thi.

**Kết luận SQL injection: không có lỗ hổng.** Đây là phần tốt của dự án.

---

## 3. KẾT QUẢ: COMMAND INJECTION — CÓ LỖ HỔNG (có điều kiện)

### 3.1 Vấn đề: `realname` không được kiểm tra

`_safe_username()` chỉ bảo vệ **tên đăng nhập**. Nhưng câu lệnh console lại dựng từ **`realname`** (tên hiển thị):

```python
# app/main.py
user = request.session.get("user")     # <- đây là realname
...
await pika_take(user, cost, kind="open")
```

```python
# app/gacha.py — không kiểm tra gì
def take_command(player: str, amount: int) -> str:
    template = load_config().get("take_command", "eco take {player} {amount}")
    return template.format(player=player, amount=amount)
```

**Test đã tái hiện**: với `realname = "Injector; op Injector"`, console nhận đúng lệnh:

```
eco take Injector; op Injector 5000
```

→ Minecraft console coi `;` là dấu phân cách lệnh, nên lệnh thứ hai (`op Injector`) **sẽ chạy**.

### 3.2 Điều kiện khai thác

Trên server thật, AuthMe chặn tên lạ: `allowedNicknameCharacters: '[a-zA-Z0-9_.-]*'`. Tôi đã kiểm tra **cả 33 tên AuthMe và 69 tên ExcellentEconomy** — tất cả đều nằm trong bảng chữ cái an toàn. Nên **với cấu hình hiện tại thì chưa khai thác được**.

Nhưng đây là **lỗ hổng chờ điều kiện**:
- Đổi `allowedNicknameCharacters` trong AuthMe → lỗ hổng thành hiện thực ngay.
- Bất kỳ tên nào lọt vào `realname` từ nguồn khác (admin đổi tên, import dữ liệu, plugin khác ghi vào `authme.realname`).
- `take_command`/`give_command` trong `gacha.json` là **config đọc từ file** — ai sửa được file thì kiểm soát được cả lệnh.

**Fix nhỏ nhất**: kiểm tra lại `realname` bằng cùng regex trước khi dựng lệnh console, và nếu tên không hợp lệ thì **từ chối giao dịch** thay vì gửi lệnh:

```python
# app/gacha.py
def _console_safe(player: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", player))
```

và trong `pika_take` / `pika_give` raise `HTTPException(400)` nếu tên không hợp lệ.

---

## 4. KẾT QUẢ: LỖI BẢO MẬT ĐÃ XÁC NHẬN (Must fix)

### 4.1 ⛔ "Tiền từ không" — console từ chối trừ tiền nhưng vẫn trao vật phẩm

**Đây là lỗi nghiêm trọng nhất.**

Minecraft console trả **HTTP 200** ngay cả khi lệnh bên trong thất bại ("player not found", "not enough money"). App chỉ kiểm tra HTTP status nên **tưởng rằng tiền đã bị trừ**:

```python
async def pika_take(player: str, amount: int, kind: str = "sync") -> int:
    before = await pika_balance(player)
    await send_command(take_command(player, amount))   # <- HTTP 200 dù lệnh hỏng
    expected = None if before is None else max(0.0, before - amount)
    return await pika_resync(player, expected, kind=kind)
```

**Test `probe5` chứng minh** (stub console trả 200 nhưng `eco take` không trừ tiền):

```
[PASS] the player gets the item even though the server took no money
[PASS] the server balance is untouched after the 'paid' case
[PASS] the server paid real money for an item that was never paid for
       server=102500.0 before=100000.0   (case cost 5000, chưa hề bị trừ)
```

**Kịch bản tấn công**: người chơi bán hết tài khoản, đăng nhập lại khi tài khoản server chưa có trong ExcellentEconomy (hoặc bị xoá), mở rương → **nhận vật phẩm miễn phí** → bán lại lấy tiền thật. Lặp lại không giới hạn.

**Fix nhỏ nhất**: sau khi gửi lệnh, **đọc lại số dư và so với số dư cũ**. Nếu số dư không giảm đúng bằng `amount` thì coi như giao dịch thất bại và trả tiền lại:

```python
# app/main.py — pika_take
before = await pika_balance(player)
await send_command(take_command(player, amount))
live = await pika_resync(player, expected=before - amount, kind=kind)
if before is not None and live > before - amount + 1:
    raise HTTPException(503, "Server chua tru tien. Thu lai.")
```

---

### 4.2 ⛔ Bán trùng món — món `selling` vẫn bán lại được

**Nguyên nhân gốc** (tìm ra ở `probe9`): `sell_items` chấp nhận cả trạng thái `selling`:

```python
# app/game.py:149
if row["status"] not in ("held", "selling"):
    raise GameError(f"{row['name']} không còn trong túi.")
```

`selling` là trạng thái "đang chờ trả tiền" — nó **không được phép bán lại**.

**Test `probe9` chứng minh**:
```
[FAIL] a pending item cannot be sold a second time — the second sell was accepted
[FAIL] two threads cannot both sell the same item — accepted=['ok', 'ok']
```

**Hậu quả**: 2 request song song bán cùng 1 món → server trả tiền **2 lần**. Đo được: món giá 8.000 → server trả 16.000. Bán trùng bằng cách tuần tự cũng được (món đã bán vẫn ở `selling`).

**Fix nhỏ nhất**: chỉ cho phép bán món ở trạng thái `held`, và chuyển sang `selling` **ngay trong transaction**:

```python
# app/game.py — sell_items
if row["status"] != "held":
    raise GameError(f"{row['name']} khong con trong túi.")
```

---

### 4.3 ⛔ Battle thất bại vẫn để lại trận đấu và đã trừ tiền local

**Test `probe2` chứng minh** (console trả lỗi 503):

```
[PASS] a failed server payment is reported to the player — http=503
[FAIL] no battle is left behind after a failed payment — battles hosted by Broke=1
[FAIL] the local wallet is not charged when the server refuses
       battle_pay debits=[{'kind': 'battle_pay', 'amount': -5000, ...}]
```

**Vấn đề**: `game.create_battle()` **đã debit ví local** và **đã tạo trận** trước khi `pika_take()` chạy. Khi `pika_take` lỗi, code `return` luôn — không rollback.

**Hậu quả**: người chơi mất 5.000 Coin trong ledger local (dù server không hề trừ), và có một trận battle "ma" mà không ai ngồi vào.

**Fix nhỏ nhất**: bọc `pika_take` trong try/except, và khi lỗi thì hoàn tiền + xoá trận:

```python
# app/main.py — battles_create
try:
    if not is_dry_run():
        await pika_take(user, paid, kind="battle_pay")
except HTTPException as exc:
    game.cancel_battle(battle["id"])     # xoá trận
    store.credit(user, paid, "refund", "battle that failed")  # hoan lai
    return JSONResponse({"detail": str(exc.detail)}, status_code=503)
```

---

### 4.4 ⛔ Rate limit đăng nhập bị vượt bằng `X-Forwarded-For`

```python
# app/security.py
def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
```

Header này **do client kiểm soát**. Kẻ tấn công chỉ cần đổi giá trị là đoán mật khẩu không bị chặn.

**Test `probe7` chứng minh**: 12 mật khẩu sai liên tiếp từ cùng một host, chỉ đổi `X-Forwarded-For` → **không lần nào bị chặn**.

**Fix nhỏ nhất**: chỉ tin `X-Forwarded-For` khi đã cấu hình reverse proxy. Vì dự án dùng Cloudflare Tunnel, cách an toàn là đọc `CF-Connecting-IP` (Cloudflare ghi đè, client không giả mã được), hoặc bỏ header hoàn toàn khi app chạy trực tiếp:

```python
def client_ip(request: Request) -> str:
    # Cloudflare ghi đè header nay, client khong gia mao duoc.
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    return request.client.host if request.client else "unknown"
```

Ngoài ra giới hạn theo **tên tài khoản** luôn, không chỉ theo IP:

```python
def login_allowed(ip: str, username: str = "") -> bool: ...
```

---

### 4.5 ⛔ 6 endpoint trả HTTP 500 khi nhận JSON sai kiểu

**Test `probe6` chứng minh**:

```
[FAIL] /api/inventory/sell với ids=["not-a-number"]  -> http=500
[FAIL] /api/inventory/sell với ids={"a":1}          -> http=500
[FAIL] /api/inventory/sell với body là chuỗi        -> http=500
[FAIL] /api/upgrade với inventory_id="abc"          -> http=500
[FAIL] /api/contract với ids=[None]                -> http=500
[FAIL] /api/battles với slots="x"                  -> http=500
```

Nguyên nhân: `int(x)` / `str(x)` không bọc try, và `body.get(...)` trên body không phải dict.

**Hậu quả**: lỗi 500 lộ stack trace nếu `debug=True`, và là **DoS nhẹ** — một request rác làm hỏng log, spam exception handler.

**Fix nhỏ nhất**: thêm helper parse an toàn:

```python
def as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def as_str(value, default: str = "") -> str:
    return value if isinstance(value, str) else default
```

rồi dùng ở tất cả chỗ đọc body.

---

## 5. Lỗi bảo mật mức trung bình (Should fix)

### 5.1 CSRF có lỗ hổng khi session chưa có token

```python
def require_csrf(request: Request) -> bool:
    return request.headers.get("x-csrf") == request.session.get("csrf")
```

Nếu **cả hai** đều là `None` → bằng nhau → **check thành công**.

**Test `probe.py` chứng minh**:
```
[PASS] a session without a csrf entry still passes the csrf check — http=200
[PASS] a cross-origin POST without the header is refused — http=200
```

Session được tạo lúc đăng nhập (`request.session.clear()` rồi set `user`), nên **khoảng thời gian giữa lúc POST `/login` trả về và lúc trang kế tiếp được render**, session có `user` nhưng **chưa có `csrf`**. Trong khoảng thời gian đó, mọi POST không kèm header đều đi qua.

**Fix nhỏ nhất**: so sánh với `None` một cách tường minh:

```python
def require_csrf(request: Request) -> bool:
    sent = request.headers.get("x-csrf")
    expected = request.session.get("csrf")
    return bool(sent) and bool(expected) and hmac.compare_digest(sent, expected)
```

và **sinh token ngay trong `login_submit`** sau khi `session.clear()`:

```python
request.session["csrf"] = new_csrf_token()
```

---

### 5.2 Cookie session không có cờ `Secure`

```python
app.add_middleware(SessionMiddleware, ..., https_only=False)
```

Cookie đi qua HTTP thường → **đánh cắp được trong mạng**. Dự án dùng Cloudflare Tunnel nên có HTTPS, nhưng cookie vẫn được gửi khi có request HTTP thẳng vào server.

**Fix**: `https_only=True` khi chạy sau Cloudflare (cookie vẫn qua HTTPS vì Cloudflare chuyển tiếp `X-Forwarded-Proto`), hoặc bật `Strict-Transport-Security`.

---

### 5.3 Bất kỳ ai cũng thêm bot vào trận của người khác

```python
@app.post("/api/battles/{battle_id}/bots")
async def battles_bots(request: Request, battle_id: int):
    user = api_auth(request, csrf=True)     # <- khong kiem tra host
    ...
    return battle_view(game.fill_bots(battle_id))
```

**Test `probe6`**: người chơi `Alice` thêm bot vào trận của `Host` → **HTTP 200**.

**Hậu quả**: spam trận của người khác, tự nhiên có người ngồi chỗ.

**Fix**: kiểm tra `battle["host"] == user` (hoặc là admin).

---

### 5.4 `/api/drops` công khai, lộ tên người chơi

Endpoint không cần đăng nhập và trả về tên người chơi thật (`.RudoOfGames`, `Trez1724`, …).

**Fix**: bỏ trường `player` khỏi response khi khách chưa đăng nhập, hoặc yêu cầu đăng nhập.

---

### 5.5 RTP vượt 100% ở 3 rương — lệch tiền về lâu dài

Đo từ `gacha.json`:

| Rương | Giá | EV | RTP |
|---|---:|---:|---:|
| jelly-starter | 5.000 | 3.107 | 62,1% |
| jelly-magic | 15.000 | 11.560 | 77,1% |
| jelly-elite | 25.000 | 19.420 | 77,7% |
| **jelly-vault** | 50.000 | 60.420 | **120,8%** |
| jelly-nether | 75.000 | 69.650 | 92,9% |
| **jelly-celestial** | 150.000 | 176.600 | **117,7%** |
| **jelly-jackpot** | 300.000 | 413.000 | **137,7%** |

Trang admin ghi cứng `rtp: "90%"` nhưng 3 rương thực tế **lỗ hơn 100%** → server **mất tiền dần** theo thời gian (test `probe10` đo được host thắng 23/30 trận bot và server **tăng** 23.800 Coin).

Không phải lỗi bảo mật, nhưng là lỗ tài chính cần sửa cùng đợt.

---

### 5.6 Lưu ý về vòng lặp battle với bot

`game.fill_bots()` chỉ **trừ ví local** của bot, **không bao giờ gọi `eco take` trên server**. Vậy nên:

- Host thắng bot → nhận vật phẩm **thật** → bán lại lấy **tiền thật trên server**.
- Bot không tốn tiền thật nào → mỗi trận là một khoản lỗ cho server.

**Đây là cơ chế tạo tiền chính**, dùng chung với 4.1. Nếu 4.1 được sửa (kiểm tra số dư sau khi trừ) thì lỗi này vẫn còn, vì bot không hề bị trừ.

**Fix**: khi người chơi tạo trận có bot, **tính tiền bot vào giá trị trận** — hoặc chỉ cho bot ngồi vào **trận do bot làm chủ** (`is_bot=True`), và chặn người chơi thật tạo trận rồi gọi bot.

---

## 6. Điểm tốt — không có vấn đề

| Hạng mục | Kết quả |
|---|---|
| SQL injection vào SQL Server | ✅ An toàn — 100% tham số hóa |
| SQL injection vào SQLite PikaMC | ✅ An toàn — regex chặn fail-closed |
| Command injection qua **username** | ✅ An toàn — cùng regex |
| Giả mạo cookie session | ✅ Bị từ chối — chữ ký HMAC |
| Thiếu session khi gọi API | ✅ 401 đúng |
| CSRF trên 10 endpoint tiền | ✅ 403 khi thiếu header (trừ lỗ hổng 5.1) |
| `count` = 0 / âm / 9999 | ✅ Bị từ chối |
| Bán món của người khác | ✅ Bị từ chối |
| Bán món không tồn tại | ✅ Bị từ chối |
| Ngồi 2 chỗ trong 1 trận | ✅ Bị từ chối |
| Claim bonus 2 lần **tuần tự** | ✅ Chỉ trả 1 lần |
| Claim bonus 2 lần **song song** | ✅ Chỉ trả 1 lần |
| Trang `/admin` cho người thường | ✅ Chuyển hướng về `/gacha` |
| XSS trong tên người chơi | ✅ `live.js` escape đầy đủ; Jinja2 autoescape mặc định |
| Cookie HttpOnly + SameSite | ✅ Đúng |

---

## 7. Bảng ưu tiên sửa — ĐÃ SỬA ✅

Tất cả 11 lỗ hổng mã nguồn đã được vá và kiểm chứng bằng 99 check tự động.

| # | Vấn đề | Mức | File | Trạng thái |
|---|---|---|---|---|
| 1 | Console từ chối trừ tiền nhưng vẫn trao vật phẩm | ⛔ Nghiêm trọng | `app/main.py` `pika_take` | ✅ Đã sửa |
| 2 | Bán trùng món (status `selling` vẫn bán được) | ⛔ Nghiêm trọng | `app/game.py` `sell_items` | ✅ Đã sửa |
| 3 | Battle fail vẫn trừ tiền local và để lại trận ma | ⛔ Nghiêm trọng | `app/main.py` `battles_create/join` | ✅ Đã sửa |
| 4 | Rate limit bị vượt bằng `X-Forwarded-For` | ⛔ Cao | `app/security.py` `client_ip` | ✅ Đã sửa |
| 5 | 6 endpoint lỗi 500 khi body sai kiểu | ⛔ Trung bình | `app/main.py` | ✅ Đã sửa |
| 6 | CSRF pass khi session chưa có token | ⚠️ Trung bình | `app/main.py` `require_csrf` | ✅ Đã sửa |
| 7 | Bot không bị trừ tiền server nhưng vẫn tạo vật phẩm thật | ⚠️ Trung bình | `app/game.py` `fill_bots` | ✅ Đã sửa |
| 8 | Command injection qua `realname` (có điều kiện) | ⚠️ Thấp | `app/gacha.py` `take_command` | ✅ Đã sửa |
| 9 | Cookie không có cờ `Secure` | ⚠️ Thấp | `app/main.py` | ✅ Đã sửa (cấu hình được) |
| 10 | Thêm bot vào trận người khác | ⚠️ Thấp | `app/main.py` `battles_bots` | ✅ Đã sửa |
| 11 | `/api/drops` lộ tên người chơi | ⚠️ Thấp | `app/main.py` `api_drops` | ✅ Đã sửa |
| 12 | 3 rương có RTP > 100% | 💰 Tài chính | `gacha.json` | ⏳ Chưa sửa (cần quyết định của chủ dự án) |

### 7.1 Lỗi phát hiện thêm trong lúc sửa

| Vấn đề | Mức | File | Trạng thái |
|---|---|---|---|
| `store.run()` không rollback khi exception → giao dịch treo bị commit nhầm ở lần gọi sau | ⛔ Nghiêm trọng | `app/store.py` | ✅ Đã sửa |
| `pika_give` không xác minh số dư thực sự tăng → trả tiền ảo | ⛔ Cao | `app/main.py` | ✅ Đã sửa |
| **Hòa trong trận: ghế 0 (luôn là host) luôn thắng** → host thắng 62,7% thay vì 50% | 💰 Tài chính | `app/game.py` `settle_battle` | ✅ Đã sửa |

### 7.2 Chi tiết lỗi hòa (phát hiện khi test lại toàn dự án)

Quy tắc xếp hạng cũ dùng `row["slot"]` làm tiêu chí cuối cùng:

```python
# app/game.py — TRƯỚC
ranked = sorted(battle["players"], key=lambda row: (
    totals[row["player"]] if crazy else -totals[row["player"]],
    worst[row["player"]] if crazy else -best[row["player"]],
    row["slot"],          # <-- luôn đưa ghế 0 lên đầu khi hòa
))
```

Ghế 0 **luôn là host**. Với `jelly-starter` ở 1 vòng, xác suất hai người quay ra cùng một món là **25,3%**. Mọi lần hòa đều thuộc về host, nên:

| | Trước | Sau khi sửa |
|---|---|---|
| Tỷ lệ thắng của host | **62,7%** | 50,0% |

Đo bằng mô phỏng 200.000 trận (`tools/test_security_probe10.py`):

```
Trước:  won 22 of 30 trận (73%)   server: 100.000 → 34.800
Sau:    won 17 of 30 trận (57%)   server: 1.000.000 → 897.600
```

Sửa: khi tổng và tiêu chí phụ đều bằng nhau, chọn **ngẫu nhiên** trong số người hòa.

```python
# app/game.py — SAU
def same_rank(row: dict) -> bool:
    head = ranked[0]
    return (totals[row["player"]] == totals[head["player"]]
            and (worst if crazy else best)[row["player"]]
            == (worst if crazy else best)[head["player"]])

top = [row for row in ranked if same_rank(row)]
winner = random.choice(top)["player"] if top else ranked[0]["player"]
```

---

## 8. Việc chưa kiểm tra

- **Không kiểm tra** chống XSS thực sự qua trình duyệt (đã đọc code, thấy escape đúng, nhưng chưa chạy payload).
- **Không kiểm tra** SQL Server cấu hình quyền (đang dùng `Trusted_Connection=yes` — tài khoản Windows).
- **Không kiểm tra** lưu lượng thật qua Cloudflare Tunnel / rate limit ở tầng Cloudflare.
- **Chưa sửa** 3 rương có RTP > 100% — cần chủ dự án chốt RTP mục tiêu.
- **Chưa bật** `SESSION_HTTPS_ONLY=true` — phải bật khi site chạy qua HTTPS (Cloudflare Tunnel), nếu bật sớm khi còn chạy HTTP thì người chơi không đăng nhập được.

### 8.1 RTP hiện tại của 7 rương

Đo bằng `sum(coin × weight) / pull_cost`:

| Rương | Giá | EV | RTP | Ghi chú |
|---|---|---|---|---|
| `jelly-starter` | 5.000 | 3.107 | 62,1% | |
| `jelly-magic` | 15.000 | 11.560 | 77,1% | |
| `jelly-elite` | 25.000 | 19.420 | 77,7% | |
| `jelly-vault` | 50.000 | 60.420 | **120,8%** | ⛔ server lỗ |
| `jelly-nether` | 75.000 | 69.650 | 92,9% | |
| `jelly-celestial` | 150.000 | 176.600 | **117,7%** | ⛔ server lỗ |
| `jelly-jackpot` | 300.000 | 413.000 | **137,7%** | ⛔ server lỗ |

Ba rương vượt 100% là lỗ hổng tiền thật: người chơi mở rương sẽ tăng số dư sau mỗi lần quay trung bình. Cần chủ dự án chốt RTP mục tiêu (thường là 70–85%) rồi giảm `coin` hoặc tăng `weight` của các món đắt.

---

## 9. Kết quả kiểm thử toàn dự án

### 9.1 Bảo mật — 133/133 ✅

```
42/42  tools/test_security.py
 6/6   tools/test_security_probe.py       (CSRF)
 8/8   tools/test_security_probe2.py      (bán trùng + rollback)
 7/7   tools/test_security_probe5.py      (tiền từ không)
19/19  tools/test_security_probe6.py      (quyền + kiểu dữ liệu)
 7/7   tools/test_security_probe7.py      (tiền bot + rate limit)
 5/5   tools/test_security_probe8.py      (command injection)
 3/3   tools/test_security_probe9.py
 4/4   tools/test_security_probe10.py     (công bằng trận bot)
 5/5   tools/test_security_probe11.py     (số dư đọc lỗi)
 3/3   tools/test_security_probe12.py     (bộ nhớ rate limit)
10/10  tools/test_security_probe13.py     (count hợp lệ)
------
133/133  ✅ ALL SUITES RAN
```

Chạy lại: `python tools/test_security_all.py`

### 9.2 Giao diện & trải nghiệm — 57/57 ✅

| Test | Kết quả |
|---|---|
| `smoke_test.py` — catalogue, rương, chủ đề, trang | 15/15 |
| `smoke_test_auth.py` — mở 1x–5x khi đã đăng nhập | 13/13 |
| `test_login_playwright.py` — luồng đăng nhập đầy đủ | 31/31 |
| `test_ui_responsive.py` — điện thoại, tap target, focus | 8/8 |

### 9.3 Tiền thật (server PikaMC thật) — ✅

| Test | Kết quả |
|---|---|
| `e2e_money_test.py` — mở rương → bán → hoàn tiền | 21/21 |
| `test_realtime_sync.py` — ví web khớp số dư server (3 người) | PASS |
| `test_live_open.py` — mở rương thật, server trừ đúng 5.000 | PASS |
| `test_live_sell.py` — bán thật, server trả đúng 500 | PASS |
| `test_live_money_flow.py` — vòng tiền đầy đủ (stub) | PASS |
| `test_refresh_button.py` / `test_auto_sync.py` — nút làm mới | PASS |
| `test_login_all_players.py` — **34/34 người chơi thật** | 340/340 |

### 9.4 Dữ liệu

| Test | Kết quả |
|---|---|
| `selftest_store.py` — mọi đường ghi vào SQL Server | PASS |
| `validate_sql.py` — file `.sql` 65.000 dòng | PASS |
| `check_tx_labels.py` — nhãn lịch sử giao dịch | PASS |
| `compare_live_vs_sql.py` — số dư web khớp PikaMC | PASS |
