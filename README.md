# Bot Discord tìm việc theo CV

Bạn gửi CV lên, bot đọc kỹ năng rồi quét các trang tuyển dụng và liệt kê việc hợp nhất. Bot cũng kiểm tra công ty bạn muốn ứng tuyển có đang đăng tin không.
**Bot chỉ làm việc khi bạn gõ lệnh**, không chạy nền và không tự gửi thông báo.

## Cài đặt
1. https://discord.com/developers/applications → **New Application** → **Bot** → **Reset Token**, copy token.
2. **OAuth2 → URL Generator**: tích `bot` + `applications.commands` → mở link để mời bot vào server (hoặc tự nhắn riêng cho bot).
3. Chạy:
```bash
cd job-bot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env     # mở .env, dán DISCORD_TOKEN
python bot.py
```
"Chỉ chạy khi gõ lệnh" nghĩa là bot không làm gì ngoài lệnh của bạn, nhưng tiến trình `python bot.py` vẫn phải đang mở để nhận lệnh. Bật khi cần dùng, tắt khi xong. Nếu muốn lệnh luôn sẵn sàng, đặt lên máy chủ nhỏ.

## Lệnh
| Lệnh | Việc làm |
|---|---|
| `/cv file:<CV>` | gửi CV (.pdf, .docx, .txt) |
| `/hoso` | xem kỹ năng / chức danh bot rút ra |
| `/timviec [tu_khoa] [dia_diem] [so_luong]` | liệt kê việc hợp CV, kèm % phù hợp và kỹ năng trùng |
| `/congty_them ten [link_tuyen_dung]` | thêm công ty muốn theo dõi |
| `/congty_kiemtra [ten]` | công ty có đăng tuyển không? 🆕 đánh dấu tin mới từ lần kiểm tra trước |
| `/congty_ds`, `/congty_xoa`, `/xoa_cv` | quản lý |

Mọi trả lời đều ẩn (chỉ mình bạn thấy). CV và danh sách công ty lưu theo từng người dùng trong `jobs.db` trên máy chạy bot.

## Nguồn dữ liệu
- **JSearch qua OpenWeb Ninja**: copy API key ở https://app.openwebninja.com rồi dán vào `OPENWEBNINJA_KEY` trong `.env`. Địa chỉ mặc định `https://api.openwebninja.com/jsearch/search`, header `x-api-key`. Nếu trong tài liệu của họ khác, chỉnh bằng `JSEARCH_URL` và `JSEARCH_KEY_HEADER`. Có cả hai khoá thì ưu tiên OpenWeb Ninja.
- **JSearch (RapidAPI)**, nguồn LinkedIn/Indeed/Glassdoor không cần số điện thoại: vào https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch → **Subscribe to Test** → chọn gói **Basic (Free)** → copy **X-RapidAPI-Key** (hiện ở khung code mẫu) → dán vào `RAPIDAPI_KEY` trong `.env`. Mỗi truy vấn tốn 1 request; xem hạn mức gói miễn phí trên trang đó.
- **LinkedIn, Indeed, TopCV, ITviec và nhiều trang khác** qua **Google Jobs (SerpApi)**: đặt `SERPAPI_KEY` trong `.env` là bật. Mỗi `/timviec` tốn tối đa 3 lượt, mỗi công ty kiểm tra tốn 1 lượt (gói miễn phí ~100 lượt/tháng). Kết quả ghi rõ tin đến từ trang nào và có link ứng tuyển.
- Sàn tổng hợp: **Remotive, Arbeitnow, RemoteOK** (API công khai, thiên về việc remote/nước ngoài) và **VietnamWorks** (API nội bộ không chính thức, có thể hỏng khi họ đổi).
- Trang tuyển dụng công ty: tự nhận **Greenhouse, Lever, Ashby, Workable** (đọc qua API chuẩn, chính xác). Trang tự dựng thì đọc HTML chung, ít chính xác hơn.
- Một nguồn lỗi thì bot bỏ qua và ghi chú ở cuối kết quả.

**Không cào trực tiếp LinkedIn/Indeed/TopCV**: các trang này chặn bot và cấm cào trong điều khoản, nên bot lấy tin của chúng qua Google Jobs. Google Jobs không phủ hết mọi tin, nhất là tin chỉ đăng riêng trên TopCV. Muốn thêm, viết hàm mới trong `sources.py` và đăng ký vào `AGGREGATORS`.

## Cách chấm điểm
Bot dò từ điển ~100 kỹ năng (`cv.py`) trong CV. Mỗi tin được chấm: kỹ năng có trong **tiêu đề** tính nặng hơn trong **mô tả**, cộng thêm nếu chức danh khớp. Chỉ hiện tin ≥ `MIN_SCORE` (mặc định 25). Đây là so khớp từ khoá, không phải AI. Kỹ năng ngoài từ điển sẽ không được nhận, sửa `SKILLS` để bổ sung.
CV dạng ảnh/scan không đọc được chữ, hãy dùng PDF có chọn được chữ hoặc .docx.

## Test
```bash
pip install pytest && python -m pytest tests
```
