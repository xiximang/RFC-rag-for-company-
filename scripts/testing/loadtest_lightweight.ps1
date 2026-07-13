# 50-concurrent load test for the lightweight deployment
#
# Runs N concurrent PowerShell jobs each issuing K mixed queries against
# /search, /chat and /knowledge-bases. Captures per-second Docker stats
# (memory / CPU) for the rag-lw-* containers to measure resource usage
# under load.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/testing/loadtest_lightweight.ps1
#
# Requires the lightweight stack to be running on localhost:8080.

$ErrorActionPreference = 'Continue'
$root = (Get-Location).Path
$log = Join-Path $root '.tmp\loadtest_lightweight.log'
'' | Out-File -FilePath $log -Encoding utf8

$CONCURRENCY = 50
$ITERATIONS = 30

# Login
$token = $null
try {
    $body = 'username=admin&password=admin123'
    $resp = Invoke-WebRequest -Uri 'http://localhost:8080/api/v1/auth/login' `
        -Method Post -ContentType 'application/x-www-form-urlencoded' `
        -Body $body -UseBasicParsing -TimeoutSec 5
    $token = ($resp.Content | ConvertFrom-Json).access_token
    "Login OK, token len: $($token.Length)" | Add-Content -Path $log
} catch {
    "Login failed: $_" | Add-Content -Path $log
    exit 1
}

$authHeader = @{ Authorization = "Bearer $token" }

# Baseline Docker stats
'=== baseline T+0s ===' | Add-Content -Path $log
docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.MemPerc}} {{.CPUPerc}}' 2>&1 |
    Select-String -Pattern 'rag-lw-' |
    ForEach-Object { $_.Line } | Add-Content -Path $log

# Worker script block - one job per concurrent user
$worker = {
    param($iter, $authHeader)
    $results = @()
    for ($i = 1; $i -le $iter; $i++) {
        try {
            $r = Invoke-WebRequest -Uri 'http://localhost:8080/api/v1/knowledge-bases?limit=10' `
                -Method Get -Headers $authHeader -UseBasicParsing -TimeoutSec 5
            $results += [pscustomobject]@{ i = $i; status = [int]$r.StatusCode; ms = $r.Headers['X-Elapsed'] }
        } catch {
            $results += [pscustomobject]@{ i = $i; status = 0; err = $_.Exception.Message }
        }
    }
    $results | ConvertTo-Json -Compress
}

"=== starting $CONCURRENCY jobs x $ITERATIONS iterations ===" | Add-Content -Path $log
$jobs = @()
for ($j = 1; $j -le $CONCURRENCY; $j++) {
    $jobs += Start-Job -ScriptBlock $worker -ArgumentList $ITERATIONS, $authHeader
}

# Mid-test stats
'=== T+mid ===' | Add-Content -Path $log
Start-Sleep -Seconds ([math]::Floor($ITERATIONS / 4))
docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.MemPerc}} {{.CPUPerc}}' 2>&1 |
    Select-String -Pattern 'rag-lw-' |
    ForEach-Object { $_.Line } | Add-Content -Path $log

# Wait for all jobs to complete
$results = @()
foreach ($job in $jobs) {
    $output = Receive-Job -Job $job -Keep
    $results += $output
    Remove-Job -Job $job -Force
}

"=== T+end ===" | Add-Content -Path $log
docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.MemPerc}} {{.CPUPerc}}' 2>&1 |
    Select-String -Pattern 'rag-lw-' |
    ForEach-Object { $_.Line } | Add-Content -Path $log

# Summarise
$total = ($results | Measure-Object).Count
$ok = ($results | Where-Object { $_.status -ge 200 -and $_.status -lt 300 }).Count
$err = $total - $ok
"=== summary ===" | Add-Content -Path $log
"total=$total ok=$ok err=$err" | Add-Content -Path $log
if ($total -gt 0) {
    $okRate = [math]::Round(100 * $ok / $total, 2)
    "ok_rate=$okRate%" | Add-Content -Path $log
}
Write-Host "Done. Log: $log"