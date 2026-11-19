# CVAT AutoQC server

FastAPI worker phục vụ panel AutoQC trong CVAT.

MVP kiểm:

- frame không có rectangle annotation (`EMPTY_FRAME`)
- box không đủ 4 toạ độ
- box có chiều rộng/cao bằng 0
- box tràn ảnh
- box nhỏ
- box trùng
- frame trùng hoặc gần trùng
- frame không đọc được

## Chạy

```powershell
cd D:\Vinuni\cvat-day2\autoqc-server
docker compose up -d --build
Invoke-RestMethod http://localhost:58220/health
```

## Gọi thử

```powershell
$body = @{
  cvat_host = "http://localhost:8080"
  token = "<CVAT personal access token>"
  job_id = 42
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:58220/run" -Method Post `
  -ContentType "application/json" -Body $body
```
