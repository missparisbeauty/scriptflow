# ScriptFlow 本機開發啟動腳本
#
# 用法：
#   ./dev.ps1                   # 預設 port 8086，DEBUG mode，連 prod Firestore
#   ./dev.ps1 -Port 9000        # 指定其他 port
#   ./dev.ps1 -ResetPassword    # 重設本機 admin 密碼
#
# 第一次跑前必須做：
#   gcloud auth application-default login
#   （瀏覽器點 Allow，建立 Application Default Credentials）

param(
    [int]$Port = 8086,
    [switch]$ResetPassword,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# --- 檢查 venv ---
$python = ".\venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "ERROR: venv 不存在，請先跑：python -m venv venv 然後 venv\Scripts\pip install -r requirements.txt" -ForegroundColor Red
    exit 1
}

# --- 環境變數 ---
$env:DEBUG = "true"
$env:GCP_PROJECT_ID = "seo-mpb"
$env:SCHEDULER_ENABLED = "false"   # 本機不要跑 09:00 排程

# Session secret：自動產生，跨重啟保留（cookie 不失效）
$secretFile = ".\.devsecret"
if (-not (Test-Path $secretFile)) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = [Convert]::ToBase64String($bytes)
    Set-Content $secretFile $secret -NoNewline -Encoding ascii
    Write-Host "✓ 產生新 SF_SESSION_SECRET 並存到 .devsecret" -ForegroundColor Green
}
$env:SF_SESSION_SECRET = (Get-Content $secretFile -Raw).Trim()

# Admin password：預設 localdev，可用 -ResetPassword 重置
$pwdFile = ".\.devpassword"
if ($ResetPassword -or (-not (Test-Path $pwdFile))) {
    $defaultPwd = "localdev"
    Set-Content $pwdFile $defaultPwd -NoNewline -Encoding ascii
    Write-Host "✓ 設定本機密碼為 'localdev' (寫入 .devpassword)" -ForegroundColor Green
}
$env:SF_ADMIN_PASSWORD = (Get-Content $pwdFile -Raw).Trim()

# --- 顯示資訊 ---
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  ScriptFlow 本機開發伺服器" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  網址:   http://127.0.0.1:$Port" -ForegroundColor White
Write-Host "  密碼:   $($env:SF_ADMIN_PASSWORD)" -ForegroundColor Yellow
Write-Host "  Docs:   http://127.0.0.1:$Port/docs" -ForegroundColor White
Write-Host "  GCP:    $($env:GCP_PROJECT_ID) (Firestore via ADC)" -ForegroundColor White
Write-Host "  停止:   Ctrl+C" -ForegroundColor Gray
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# --- 啟動 uvicorn ---
$reloadFlag = if ($NoReload) { @() } else { @("--reload") }
& $python -m uvicorn main:app --host 127.0.0.1 --port $Port $reloadFlag
