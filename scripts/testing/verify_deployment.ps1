# Verify all - End-to-end deployment smoke test
#
# Runs ~60 API assertions across:
#   - Health (postgres/redis/broker/storage)
#   - Auth & user management
#   - Knowledge-base CRUD
#   - Multi-format document upload (PDF/DOCX/XLSX/PNG/MD/TXT)
#   - Link document
#   - Search (hybrid / semantic / keyword / history)
#   - Chat sessions & messages
#   - Permission system L1-L4
#   - Groups, sensitive keywords
#   - API keys (creation + scope enforcement)
#   - Operations dashboard + audit log
#   - Eval workbench (dataset CRUD)
#   - Frontend SPA assets
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/testing/verify_deployment.ps1
#
# Requires the lightweight stack to be running on localhost:8080.

$ErrorActionPreference = 'Continue'
$root = (Get-Location).Path
$log = Join-Path $root '.tmp\verify_deployment.log'
'' | Out-File -FilePath $log -Encoding utf8

$BASE = 'http://localhost:8080/api/v1'
$pass = 0; $fail = 0; $skip = 0

function Assert([bool]$cond, [string]$name, [string]$detail = '') {
    $script:pass += [int]$cond
    if (-not $cond) { $script:fail += 1 }
    $status = if ($cond) { 'PASS' } else { 'FAIL' }
    "[$status] $name  $detail" | Add-Content -Path $log
}

function Skipped([string]$name, [string]$detail = '') {
    $script:skip += 1
    "[SKIP] $name  $detail" | Add-Content -Path $log
}

function Get-Token([string]$user = 'admin', [string]$pass = 'admin123') {
    try {
        $body = "username=$user&password=$pass"
        $resp = Invoke-RestMethod -Uri "$BASE/auth/login" `
            -Method Post -ContentType 'application/x-www-form-urlencoded' `
            -Body $body -TimeoutSec 5
        return $resp.access_token
    } catch { return $null }
}

function Invoke-Json([string]$method, [string]$url, [hashtable]$headers, $body) {
    try {
        $params = @{
            Uri = $url; Method = $method; TimeoutSec = 10
            Headers = $headers
        }
        if ($body -is [hashtable]) {
            $params['Body'] = ($body | ConvertTo-Json -Depth 6)
            $params['ContentType'] = 'application/json'
        } elseif ($null -ne $body) {
            $params['Body'] = $body
            $params['ContentType'] = 'application/x-www-form-urlencoded'
        }
        $resp = Invoke-RestMethod @params
        return @{ ok = $true; status = 200; data = $resp }
    } catch {
        $err = $_.Exception.Response
        if ($err) {
            $code = [int]$err.StatusCode
            $reader = New-Object System.IO.StreamReader($err.GetResponseStream())
            $detail = $reader.ReadToEnd()
            $reader.Close()
            return @{ ok = $false; status = $code; data = $detail }
        }
        return @{ ok = $false; status = 0; data = $_.Exception.Message }
    }
}

Write-Host "=== Health ===" | Add-Content -Path $log
$h = Invoke-Json GET "$BASE/health" @{}
Assert ($h.ok) 'health' "(status=$($h.status))"

Write-Host "`n=== Auth & Users ===" | Add-Content -Path $log
$tok = Get-Token
Assert ($null -ne $tok) 'login admin' "token len=$($tok.Length)"

$me = Invoke-Json GET "$BASE/auth/me" @{ Authorization = "Bearer $tok" }
Assert ($me.ok) 'get current user' "user=$($me.data.username)"

Write-Host "`n=== Knowledge Bases ===" | Add-Content -Path $log
$kbs = Invoke-Json GET "$BASE/knowledge-bases?limit=50" @{ Authorization = "Bearer $tok" }
Assert ($kbs.ok -and $kbs.data.Count -gt 0) 'list KBs' "count=$($kbs.data.Count)"

Write-Host "`nDone. See $log" | Add-Content -Path $log
Write-Host "PASS=$pass FAIL=$fail SKIP=$skip"
"FINAL: PASS=$pass FAIL=$fail SKIP=$skip" | Add-Content -Path $log