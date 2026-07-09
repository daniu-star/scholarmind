<#
.SYNOPSIS
    Batch configure Railway backend service environment variables.

.DESCRIPTION
    Configures all environment variables for the Railway 'backend' service
    via the Railway CLI (v5 syntax: railway variables set KEY=value --service backend).
    Does NOT read or modify the local .env file.

    Sensitive values are passed as mandatory script parameters.
    Non-sensitive values are hardcoded based on src/backend/config.py.

.PARAMETER DeepseekApiKey
    DeepSeek API Key (sensitive, required).

.PARAMETER AlipayAppId
    Alipay APP_ID (sensitive, required).

.PARAMETER AlipayPrivateKey
    Alipay application private key (sensitive, required). Pass as a single-line
    string (PEM newlines stripped or escaped) to avoid shell argument splitting.

.PARAMETER AlipayPublicKey
    Alipay public key (sensitive, required).

.PARAMETER AlipaySellerId
    Alipay seller ID (sensitive, required).

.PARAMETER SmtpPassword
    SMTP email authorization code (sensitive, required).

.EXAMPLE
    .\scripts\configure-railway-env.ps1 `
        -DeepseekApiKey "sk-xxx" `
        -AlipayAppId "2021006170600179" `
        -AlipayPrivateKey "MIIEvA..." `
        -AlipayPublicKey "MIIBIj..." `
        -AlipaySellerId "2088242324300000" `
        -SmtpPassword "xxxxx"

.NOTES
    Prerequisites:
    - Railway CLI installed (npm i -g @railway/cli)
    - `railway login` completed
    - `railway link` completed (project linked)

    Idempotent: existing variables are overwritten; re-running has no side effects.
    Railway reference variables like ${{Postgres.DATABASE_URL}} are resolved by
    Railway at deploy time; they are passed through as literal text (single-quoted
    in the hashtable so PowerShell does not interpolate the braces).
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, HelpMessage = "DeepSeek API Key")]
    [ValidateNotNullOrEmpty()]
    [string]$DeepseekApiKey,

    [Parameter(Mandatory = $true, HelpMessage = "Alipay APP_ID")]
    [ValidateNotNullOrEmpty()]
    [string]$AlipayAppId,

    [Parameter(Mandatory = $true, HelpMessage = "Alipay application private key (single-line)")]
    [ValidateNotNullOrEmpty()]
    [string]$AlipayPrivateKey,

    [Parameter(Mandatory = $true, HelpMessage = "Alipay public key")]
    [ValidateNotNullOrEmpty()]
    [string]$AlipayPublicKey,

    [Parameter(Mandatory = $true, HelpMessage = "Alipay seller ID")]
    [ValidateNotNullOrEmpty()]
    [string]$AlipaySellerId,

    [Parameter(Mandatory = $true, HelpMessage = "SMTP email authorization code")]
    [ValidateNotNullOrEmpty()]
    [string]$SmtpPassword
)

$ErrorActionPreference = "Continue"

# ── Pre-flight checks ──────────────────────────────────────────
Write-Host "[INFO] Configuring Railway backend service env vars..." -ForegroundColor Cyan

$railwayCmd = Get-Command railway -ErrorAction SilentlyContinue
if (-not $railwayCmd) {
    Write-Host "[ERROR] Railway CLI not found on PATH. Install: npm i -g @railway/cli" -ForegroundColor Red
    exit 1
}

# Verify project is linked (non-fatal if status command differs, but catches obvious unlink)
$statusOutput = railway status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Not linked to a Railway project. Run 'railway link' first." -ForegroundColor Red
    Write-Host "$statusOutput" -ForegroundColor DarkGray
    exit 1
}

# ── Non-sensitive variables (hardcoded, ordered) ───────────────
# NOTE: ${{...}} values use SINGLE quotes so PowerShell treats braces literally;
# Railway resolves these references at deploy time.
$nonSensitiveVars = [ordered]@{
    "ENVIRONMENT"                      = "production"
    "DEBUG"                            = "false"
    "LOG_LEVEL"                        = "INFO"
    "LOG_FORMAT"                       = "json"
    "DEEPSEEK_BASE_URL"               = "https://api.deepseek.com"
    "DEEPSEEK_MODEL"                   = "deepseek-chat"
    "DEEPSEEK_MODEL_FLASH"            = "deepseek-v4-flash"
    "DEEPSEEK_MODEL_PRO"              = "deepseek-v4-pro"
    "LLM_TIMEOUT"                      = "60"
    "LLM_MAX_RETRIES"                  = "3"
    "CORS_ORIGINS"                     = "https://quannengyanjiu.cn,https://www.quannengyanjiu.cn,http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000"
    "CORS_ALLOW_ALL_IN_DEV"           = "false"
    "JWT_ALGORITHM"                    = "HS256"
    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES" = "1440"
    "JWT_REFRESH_TOKEN_EXPIRE_DAYS"   = "30"
    "JWT_SECRET_KEY"                   = "0e7Jm2VhF9sQ4xN8kP6uC3aW1rT5yL0bG7dZ9iM2nX4qS8vK"
    "RATE_LIMIT_ENABLED"              = "true"
    "RATE_LIMIT_REQUESTS"             = "60"
    "MAX_FILES_PER_SESSION"           = "15"
    "MAX_FILE_SIZE_MB"                = "20"
    "RAG_TOP_K"                        = "5"
    "RAG_EMBEDDING_MODEL"             = "paraphrase-multilingual-MiniLM-L12-v2"
    "UPLOAD_DIR"                       = "/app/data/uploads"
    "SKILLS_DIR"                       = "/app/data/skills"
    "CHARTS_DIR"                       = "/app/data/charts"
    "CONVERSATIONS_DIR"               = "/app/data/conversations"
    "CHROMA_DIR"                       = "/app/data/chroma"
    "DB_PATH"                          = "/app/data/scholarmind.db"
    "DATABASE_URL"                     = '${{Postgres.DATABASE_URL}}'
    "REDIS_URL"                        = '${{Redis.REDIS_URL}}'
    "CELERY_BROKER_URL"               = '${{Redis.REDIS_URL}}'
    "CELERY_RESULT_BACKEND"           = '${{Redis.REDIS_URL}}'
    "TASK_BACKEND"                     = "celery"
    "HF_ENDPOINT"                      = "https://hf-mirror.com"
    "PAYMENT_ENABLED"                  = "true"
    "PAYMENT_VERIFY_REQUIRED"          = "true"
    "ALIPAY_SANDBOX"                   = "false"
    "ALIPAY_NOTIFY_URL"               = "https://api.quannengyanjiu.cn/api/v1/payment/alipay/notify"
    "ALIPAY_RETURN_URL"               = "https://www.quannengyanjiu.cn/#payment"
    "SMTP_USER"                        = "18229499131@163.com"
    "SMTP_FROM_NAME"                   = "ScholarMind"
    "VERIFICATION_CODE_EXPIRE_MINUTES" = "5"
    "VERIFICATION_CODE_LENGTH"          = "6"
    "ADMIN_USERNAMES"                  = "admin,1306737664@qq.com"
    "BASE_URL"                         = "https://api.quannengyanjiu.cn"
    "WECHAT_PAY_NOTIFY_URL"            = "https://api.quannengyanjiu.cn/api/v1/payment/wechat/notify"
}

# ── Sensitive variables (from parameters) ──────────────────────
$sensitiveVars = [ordered]@{
    "DEEPSEEK_API_KEY"   = $DeepseekApiKey
    "ALIPAY_APP_ID"      = $AlipayAppId
    "ALIPAY_PRIVATE_KEY" = $AlipayPrivateKey
    "ALIPAY_PUBLIC_KEY"  = $AlipayPublicKey
    "ALIPAY_SELLER_ID"   = $AlipaySellerId
    "SMTP_PASSWORD"       = $SmtpPassword
}

$totalCount        = $nonSensitiveVars.Count + $sensitiveVars.Count
$sensitiveCount    = $sensitiveVars.Count
$nonSensitiveCount = $nonSensitiveVars.Count

Write-Host "[INFO] Total: $totalCount variables ($sensitiveCount sensitive from params, $nonSensitiveCount non-sensitive hardcoded)" -ForegroundColor Cyan
Write-Host ""

# ── Helper: set a single variable via Railway CLI ──────────────
function Set-RailwayVar {
    param(
        [string]$Key,
        [string]$Value,
        [bool]$IsSensitive
    )

    # Build "KEY=value" pair. Double-quoted interpolation is safe here because
    # $Value's content (even ${{...}}) is inserted literally — PowerShell does
    # not recursively re-parse interpolated variable values.
    $pair = "$Key=$Value"

    try {
        # Railway CLI v5: --service flag targets a specific service.
        # Quote $pair so values containing spaces/commas/braces stay as one arg.
        $output = & railway variables set "$pair" --service backend 2>&1
        if ($LASTEXITCODE -eq 0) {
            if ($IsSensitive) {
                Write-Host "[OK] $Key=*** (set)" -ForegroundColor Green
            } else {
                Write-Host "[OK] $Key=$Value" -ForegroundColor Green
            }
            return $true
        } else {
            $msg = ($output | Out-String).Trim()
            Write-Host "[WARN] Failed to set ${Key}: $msg" -ForegroundColor Yellow
            return $false
        }
    } catch {
        Write-Host "[WARN] Failed to set ${Key}: $($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
}

# ── Apply non-sensitive variables ──────────────────────────────
$success    = 0
$failed     = 0
$failedList = @()

foreach ($key in $nonSensitiveVars.Keys) {
    $ok = Set-RailwayVar -Key $key -Value $nonSensitiveVars[$key] -IsSensitive $false
    if ($ok) { $success++ } else { $failed++; $failedList += $key }
}

# ── Apply sensitive variables ─────────────────────────────────
foreach ($key in $sensitiveVars.Keys) {
    $ok = Set-RailwayVar -Key $key -Value $sensitiveVars[$key] -IsSensitive $true
    if ($ok) { $success++ } else { $failed++; $failedList += $key }
}

# ── Summary ────────────────────────────────────────────────────
Write-Host ""
Write-Host "[INFO] Done: $success/$totalCount succeeded, $failed failed" -ForegroundColor Cyan
if ($failed -gt 0) {
    Write-Host "[INFO] Failed variables:" -ForegroundColor Yellow
    foreach ($k in $failedList) {
        Write-Host "  - $k" -ForegroundColor Yellow
    }
    exit 1
}

Write-Host "[INFO] All variables configured successfully." -ForegroundColor Green
exit 0
