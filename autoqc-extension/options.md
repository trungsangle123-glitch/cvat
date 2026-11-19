# Cài đặt CVAT AutoQC extension

1. Khởi động server:

```powershell
cd D:\Vinuni\cvat-day2\autoqc-server
docker compose up -d --build
```

2. Chrome mở `chrome://extensions`, bật Developer mode, chọn Load unpacked
   và nạp thư mục `D:\Vinuni\cvat-day2\autoqc-extension`.

3. Mở phần options của extension:
   - AutoQC server: `http://localhost:58220`
   - CVAT host: `http://localhost:8080`
   - CVAT Personal Access Token

4. Mở một CVAT job. Panel AutoQC xuất hiện ở góc dưới bên trái.

5. Bấm `Run QC`:
   - Panel hiển thị Release/Hold/Rework.
   - Chọn issue để mở frame tương ứng.

Extension chỉ xem issue và điều hướng frame. Nó không sửa annotation tự động.
