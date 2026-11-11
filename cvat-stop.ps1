# Stops CVAT + Nuclio and closes the public tunnel.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File D:\Vinuni\cvat-day2\cvat-stop.ps1

Write-Host "== Stopping cloudflared tunnel..." -ForegroundColor Cyan
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Write-Host "   Tunnel closed (trycloudflare URL is now dead)."

Write-Host "== Stopping CVAT containers..." -ForegroundColor Cyan
Push-Location "D:\Vinuni\cvat-day2"
docker compose -f docker-compose.yml -f components/serverless/docker-compose.serverless.yml stop
Pop-Location

Write-Host ""
Write-Host "All stopped. Safe to shut down the PC." -ForegroundColor Green
Write-Host "(Your data is saved in Docker volumes - 'stop' keeps everything.)"
