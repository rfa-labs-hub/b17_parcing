# Chrome with remote debugging on port 9222.
# Run: powershell -ExecutionPolicy Bypass -File chrome_start_debug.ps1
# (ASCII-only file so Windows PowerShell does not mangle encoding.)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Chrome + remote debugging :9222 ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/3] Stopping chrome.exe..."
Get-Process -Name "chrome" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$chrome = $null
$candidates = @(
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe"),
    "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
)
foreach ($p in $candidates) {
    if (Test-Path -LiteralPath $p) {
        $chrome = $p
        break
    }
}
if (-not $chrome) {
    Write-Host "[ERROR] chrome.exe not found." -ForegroundColor Red
    Read-Host "Press Enter"
    exit 1
}

$userData = Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data"
$profile = "Default"

Write-Host "[2/3] Chrome: $chrome"
Write-Host "      User Data: $userData"
Write-Host "      Profile: $profile"
Write-Host ""

# One argv per array element; path with spaces stays one argument (--user-data-dir=...User Data).
# Omit --remote-debugging-address: on some PCs Chrome then does not listen on 9222.
$argList = @(
    "--remote-debugging-port=9222",
    "--remote-allow-origins=*",
    "--user-data-dir=$userData",
    "--profile-directory=$profile"
)

Write-Host "[3/3] Starting Chrome (Start-Process with quoted User Data path)..."
Start-Process -FilePath $chrome -ArgumentList $argList

Write-Host "      Waiting for port 9222 (up to 25 s)..."
$ok = $false
for ($i = 0; $i -lt 25; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:9222/json/version" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200 -and $r.Content -match "Browser") {
            $ok = $true
            break
        }
    } catch {
    }
}

Write-Host ""
if ($ok) {
    Write-Host "OK: debugging at http://127.0.0.1:9222 responds." -ForegroundColor Green
    Write-Host "In another terminal:  python b17_login.py --chrome-cdp"
} else {
    Write-Host "[WARN] Port 9222 does not respond." -ForegroundColor Yellow
    Write-Host "netstat (look for LISTENING on 9222):"
    netstat -ano | findstr ":9222"
    Write-Host ""
    Write-Host "Open in browser: http://127.0.0.1:9222/json/version"
}
Write-Host ""
Read-Host "Press Enter to close"
