# Mini guideline — bài làm cá nhân

> Điền nội dung này trước khi bắt đầu gán nhãn. Giữ lại các quyết định sau khi self-QC.

## Định nghĩa lớp

| Lớp | Định nghĩa | Ví dụ / điểm phân biệt |
| --- | --- | --- |
| `car` | Xe con chở người, gầm thấp hoặc trung bình, thân liền khối, thường 4 đến 7 chỗ. | Sedan, hatchback, coupe, SUV, crossover, taxi, xe công nghệ. **Phân biệt:** không có thùng hàng hở phía sau, không có thân hộp dài kiểu xe tải nhỏ (đó là `van`). |
| `truck` | Xe chuyên chở hàng, có thùng hàng riêng hoặc cabin tách khỏi thùng. | Xe tải nhỏ/lớn, xe ben, xe bồn, xe container, đầu kéo (kèm rơ-moóc), xe cẩu, xe chuyên dụng, **xe bán tải (pickup)**. **Phân biệt:** cabin và thùng tách nhau rõ, hoặc có thùng hở phía sau. |
| `bus` | Xe chở khách cỡ lớn, thân dài, nhiều cửa sổ dọc thân, từ khoảng 17 chỗ trở lên. | Xe buýt thành phố, xe khách đường dài, xe giường nằm, xe đưa đón nhân viên/học sinh cỡ lớn. **Phân biệt:** dài và cao hơn `van` rõ rệt, hàng cửa sổ liên tục. |
| `van` | Xe thân hộp liền khối, cỡ vừa, chở người hoặc hàng nhẹ, tối đa khoảng 16 chỗ. | Ford Transit, Hyundai Solati, minivan/MPV, xe van chở hàng (cửa hông trượt, không có cửa sổ phía sau). **Phân biệt:** cabin liền thân, mui cao, ngắn hơn `bus`. |

## Quy tắc chung

- **Box bám sát vật thể nghĩa là:** hình chữ nhật nhỏ nhất bao trọn phần thân xe nhìn thấy được, các cạnh chạm sát mép ngoài cùng (bao gồm cả gương chiếu hậu, cản, thùng hàng, rơ-moóc). Không để dư viền trống quá 2 đến 3 pixel, không bao bóng đổ, phản chiếu, người đứng cạnh hay hàng hóa chìa ra quá xa khỏi thùng.
- **Vật thể bị che khuất:** Chỉ vẽ box quanh **phần nhìn thấy**, không đoán phần bị khuất.
  - Còn thấy từ khoảng 30% thân xe trở lên và nhận ra được lớp → gắn nhãn.
  - Còn thấy dưới 30%, hoặc không chắc là lớp nào → **không gắn**, hoặc gắn cờ `ignore` nếu công cụ hỗ trợ.
  - Xe bị xe khác che một phần: mỗi xe một box riêng, box có thể chồng lấn nhau.
- **Vật thể bị cắt bởi rìa ảnh:** Vẽ box đến sát rìa ảnh, chỉ bao phần nằm trong khung hình. Gắn nhãn nếu còn thấy từ khoảng 30% thân xe trở lên và nhận ra được lớp. Nếu chỉ thấy một góc nhỏ (ví dụ chỉ thấy bánh hoặc cản) → bỏ qua.
- **Vật thể rất nhỏ/mơ hồ:**
  - Box nhỏ hơn khoảng 16×16 px (hoặc cạnh ngắn dưới ~12 px) → không gắn.
  - Rõ là xe nhưng không phân biệt được lớp (xa, mờ, ngược sáng) → **không đoán**, gắn cờ `ignore`/`uncertain` hoặc bỏ qua theo quy định dự án.
  - Tuyệt đối không gắn nhãn dựa trên suy đoán; nhãn sai gây hại hơn nhãn thiếu.
- **Xe đỗ, xe dừng, xe trong bãi:** vẫn gắn nhãn như xe đang chạy.
- **Không gắn nhãn:** xe trong ảnh phản chiếu (kính, gương, vũng nước), xe trên biển quảng cáo/poster/màn hình, đồ chơi, mô hình, xe trong tranh vẽ.
- **Xe chở hàng chồng cao hoặc kéo theo vật:** box bao thân xe và thùng hàng; hàng hóa chìa ra bất thường thì bỏ phần chìa ra.

## Ghi lại quyết định cho ít nhất ba ca mơ hồ

| Ảnh | Tình huống | Quyết định cuối | Lý do theo schema |
| --- | --- | --- | --- |
| `drive_005.jpg` | Quá nhiều xe ở phía xa chồng lên nhau nên khó annotate| annotate 1 phần những xe ở gần có thể nhìn thấy, ở xa thì bỏ qua | có scheam là `car` |
| `drive_004.jpg` | có nhiều loại xe khác và có cả người đi bộ , xe đạp | annotate 1 phần theo đúng schema, những cái nào không có thì không annotate | có schema là `car` |
| `drive_031.jpg` | có cả biển báo giao thông , nhưng không thuộc schema | annotate những thứ thuộc schema | có schema là `car`, `van`   |
