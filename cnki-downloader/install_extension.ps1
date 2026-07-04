# CNKI Extension Installer
Write-Host "=== CNKI Extension Installer ===" -ForegroundColor Cyan

# Kill Chrome
Write-Host "Stopping Chrome..." -ForegroundColor Yellow
Get-Process -Name "chrome" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

# Verify killed
$remaining = Get-Process -Name "chrome" -ErrorAction SilentlyContinue
if ($remaining) {
    Write-Host "WARNING: Chrome processes still running!" -ForegroundColor Red
} else {
    Write-Host "Chrome fully stopped." -ForegroundColor Green
}

# Verify extension files
$extPath = "C:\cnki_extension"
Write-Host "`nExtension path: $extPath"
if (Test-Path "$extPath\manifest.json") {
    $manifest = Get-Content "$extPath\manifest.json" -Raw | ConvertFrom-Json
    Write-Host "Extension: $($manifest.name) v$($manifest.version)" -ForegroundColor Green
} else {
    Write-Host "ERROR: Extension files not found at $extPath" -ForegroundColor Red
    exit 1
}

# Launch Chrome with extension
Write-Host "`nLaunching Chrome with extension..." -ForegroundColor Cyan
$v2Page = "file:///c:/Users/13067/Desktop/AI产品/cnki-downloader/downloads/all_papers_v2.html"

Start-Process "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    -ArgumentList "--load-extension=$extPath", "--new-window", $v2Page

Start-Sleep -Seconds 5

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  Chrome launched with extension!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Verify: Open chrome://extensions/ in Chrome"
Write-Host "Look for: CNKI Auto PDF Download"
Write-Host ""
Write-Host "Then press S on the V2 page to start downloading!"
Write-Host ""
Pause
