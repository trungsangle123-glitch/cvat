# Starts CVAT + Nuclio and opens the public tunnel.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File D:\Vinuni\cvat-day2\cvat-start.ps1
# NOTE: the trycloudflare URL is NEW every time - copy it from the output and share it.

$cf = "C:\Program Files (x86)\cloudflared\cloudflared.exe"

Write-Host "== Starting CVAT containers..." -ForegroundColor Cyan
Push-Location "D:\Vinuni\cvat-day2"
docker compose -f docker-compose.yml -f components/serverless/docker-compose.serverless.yml -f docker-compose.serverless.override.yml -f docker-compose.tunnel.yml up -d
Pop-Location

Write-Host "== Waiting for CVAT web UI..." -ForegroundColor Cyan
$ok = $false
foreach ($i in 1..30) {
    Start-Sleep -Seconds 5
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8080/" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}
if (-not $ok) {
    Write-Host "CVAT did not come up after 2.5 min. Check:  docker ps" -ForegroundColor Red
    exit 1
}
Write-Host "   CVAT is up locally at http://localhost:8080" -ForegroundColor Green

Write-Host "== Opening public tunnel (keep this window open!)..." -ForegroundColor Cyan
Write-Host "   --> The URL below is NEW every time. Share it with your team." -ForegroundColor Yellow
Write-Host ""
& $cf tunnel --url http://localhost:8080 --http-host-header localhost
