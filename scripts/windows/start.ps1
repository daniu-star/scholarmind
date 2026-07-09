# ScholarMind 一键启动脚本
# 用法: 在项目根目录运行 .\start.ps1

Write-Host "=== ScholarMind 启动中 ===" -ForegroundColor Cyan

# 检查 Python
$pythonOk = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonOk) {
    Write-Host "[错误] 未找到 Python，请先安装 Python 3.10+" -ForegroundColor Red
    exit 1
}

# 检查 Node.js
$nodeOk = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeOk) {
    Write-Host "[错误] 未找到 Node.js，请先安装 Node.js 18+" -ForegroundColor Red
    exit 1
}

# 优先使用项目虚拟环境，避免系统 Python 缺少支付/ORM 依赖
$pythonExe = if (Test-Path "$PSScriptRoot\.venv\Scripts\python.exe") {
    "$PSScriptRoot\.venv\Scripts\python.exe"
} elseif (Test-Path "$PSScriptRoot\src\backend\.venv\Scripts\python.exe") {
    "$PSScriptRoot\src\backend\.venv\Scripts\python.exe"
} else {
    "python"
}

# 启动后端
Write-Host "[1/2] 启动后端 (http://localhost:8000)..." -ForegroundColor Yellow
$backendCommand = "Set-Location '$PSScriptRoot'; & '$pythonExe' -m uvicorn src.backend.app:create_app --factory --host 0.0.0.0 --port 8000 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCommand

# 启动前端
Write-Host "[2/2] 启动前端 (http://localhost:5173)..." -ForegroundColor Yellow
$frontendCommand = "Set-Location '$PSScriptRoot\src\frontend'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCommand

# 与 start.bat 保持一致：默认打开当前产品主入口（单文件交互原型）
Start-Process powershell -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$PSScriptRoot\wait_and_open.ps1" -WindowStyle Hidden

Write-Host ""
Write-Host "=== 启动完成 ===" -ForegroundColor Green
Write-Host "后端 API: http://localhost:8000/api/v1/health" -ForegroundColor Green
Write-Host "产品主界面: http://localhost:8000/app/interactive-prototype.html" -ForegroundColor Green
Write-Host "工程版前端: http://localhost:5173" -ForegroundColor Gray
Write-Host ""
Write-Host "提示: 两个终端窗口已打开，关闭窗口即可停止服务" -ForegroundColor Gray
