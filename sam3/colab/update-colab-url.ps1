# Update the Colab tunnel URL and restart the gateway. Run from the repo root:
#   powershell -File sam3\colab\update-colab-url.ps1 -Url https://xxx.trycloudflare.com
param(
    [Parameter(Mandatory = $true)]
    [string]$Url
)

$ErrorActionPreference = "Stop"
$repoRoot = Join-Path $PSScriptRoot "..\.."

Set-Content -Path (Join-Path $PSScriptRoot ".env") -Value "COLAB_FUNCTION_URL=$Url"

docker compose `
    -f (Join-Path $repoRoot "docker-compose.yml") `
    -f (Join-Path $repoRoot "components\serverless\docker-compose.serverless.yml") `
    -f (Join-Path $repoRoot "docker-compose.sam3-colab.yml") `
    --env-file (Join-Path $PSScriptRoot ".env") `
    up -d sam3_colab_gateway
