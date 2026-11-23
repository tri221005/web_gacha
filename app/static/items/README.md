# Ảnh đồ trong rương

Mỗi món có `id` trong `gacha.json`. Web tự tìm file theo thứ tự:

`png → webp → jpg → jpeg → svg`

Ví dụ món `scroll`:

1. Đặt ảnh vào đây, **đúng tên id**: `scroll.png`
2. Không sửa JSON nếu id đã khớp.
3. Reload trang rương.

Cùng cách với rương: `app/static/cases/jelly-starter.png` sẽ thay SVG placeholder.

Nên dùng PNG/WebP nền trong suốt, khoảng 256–512px.

Id hiện có: `dust`, `apple`, `pouch`, `iron`, `scroll`, `book`, `diamond`, `netherite`, `totem`, `elytra`, `susanoo`, `dragon`, `jackpot`, `crown`.
