# JellyVale Gacha — ghi chú cho lần sau

Cập nhật: 2026-11-23 (gỡ chức năng hợp đồng; sửa lỗi hoàn tiền battle)

## Mục tiêu

Web gacha JellyVale, login AuthMe, Coin live PikaMC, catalogue rương + dải quay giống CaseForge, cộng vòng chơi đầy đủ:

- Live drop (bot + người)
- Túi đồ, bán lại lấy Coin
- Nâng cấp (cược món rẻ lấy món đắt)
- Case battle vs bot (Standard / Crazy)
- Vòng bonus ngày
- Ví web riêng (dry-run)

Không mang Steam / market CS2. Đồ là item Minecraft (Nexo/AE sau này).

Console **tạm tắt**. `GACHA_DRY_RUN=true` — chơi trên **ví web** (seed 250.000 Coin lần đầu). Không `eco take` / `eco give`.

## Chạy

`E:\code\log\web-gacha\start.bat` → http://127.0.0.1:8080

- `/gacha` catalogue + bonus
- `/case/{slug}` mở rương → đồ vào túi
- `/inventory` túi đồ / bán
- `/upgrade` nâng cấp
- `/battles` lobby + tạo trận, bot tự vào
- `/vi` ví web + Coin in-game
- `/admin` thống kê

## Tiền

- **Coin web**: SQL Server `jellyvale` (bảng `gacha_*`), dùng hết vòng chơi trên web.
- **Coin in-game**: ExcellentEconomy qua Pika, chỉ đọc khi dry-run.
- Mở rương **không** cộng Coin ngay — món vào túi, bán mới ra Coin.

Khi bật trừ Coin thật:

1. API key Pika thêm `control.console`
2. `.env`: `GACHA_DRY_RUN=false`
3. Restart `start.bat`

Lúc đó: mở rương / vào battle có `eco take`; bán / bonus có `eco give`.

## Thay ảnh đồ / rương

Web **không hard-code ảnh**. Mỗi `id` trong `gacha.json` map 1 file trong `app/static/items/` hoặc `cases/`.

Ưu tiên: `png`, `webp`, `jpg`, `jpeg`, `svg`.

Rarity: `consumer`, `industrial`, `milspec`, `restricted`, `classified`, `covert`, `extraordinary`.

## File chính

- `gacha.json` — rương, tỉ lệ, giá
- `app/game.py` — mở / bán / nâng cấp / battle
- `app/store.py` — ledger gacha trên SQL Server (pyodbc)
- `app/bots.py` — bot mở rương + ngồi battle
- `app/static/roulette.js` — dải quay
- `app/static/live.js` — dải drop
- `jellyvale_full.sql` — dump T-SQL toàn bộ dữ liệu server + ledger
- `tools/export_sqlserver.py` — tải từ PikaMC API và xuất `.sql`

## Pika

- Panel: https://hub.pikamc.vn/server/de021d06
- DB: `/plugins/AuthMe/authme.db`, `/plugins/ExcellentEconomy/data.db`
- `Trez1724` Coin in-game = 0; dry-run thì ví web vẫn chơi được.

## Battle — ghi chú logic

- Một ghế = `pull_cost * rounds`. Chủ phòng trả **ghế của mình + mỗi ghế bot** nó gọi.
- Người thắng nhận **toàn bộ** đồ của trận (kiểu CS:GO), không phải chỉ đồ của mình.
- Hoà thì bốc random, không ưu tiên chủ phòng.
- Ledger local chỉ giữ **ghế của chủ phòng**; phần bot trả từ ví bot. Khi server từ chối
  thanh toán, phải hoàn đúng số ledger đã mất, không phải số server đã bị trừ.
- Test: `tools/test_battle_logic.py` (luật chơi), `tools/test_battle_money.py` (dòng tiền).

## Việc tiếp

- Thả PNG đồ Nexo/AE vào `static/items`
- `nexo give` khi hết dry-run (rút đồ vào server thay vì chỉ bán Coin)
- HTTPS / VPS
- Không commit `.env`
