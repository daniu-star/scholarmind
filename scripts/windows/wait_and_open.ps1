# Wait for backend health endpoint, then open browser.
# Invoked by start.bat to avoid nested-quote issues in cmd.
$ErrorActionPreference = 'SilentlyContinue'
$ok = $false
# Poll every 1s for up to 60s (backend starts in ~5s)
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest -Uri 'http://localhost:8000/api/v1/health' -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) {
            $ok = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 1
}
if ($ok) {
    Write-Host '[INFO] Backend is ready. Opening browser...'
    Start-Process 'http://localhost:8000/app/interactive-prototype.html'
} else {
    Write-Host '[WARN] Backend not ready after 2 minutes. Please open browser manually:'
    Write-Host '       http://localhost:8000/app/interactive-prototype.html'
}
