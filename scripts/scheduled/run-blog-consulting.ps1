param(
    [int]$LockWaitMin = 15,
    [switch]$SkipLlm,
    [switch]$NoLive,
    [switch]$SkipDeploy,
    [switch]$SkipVerify
)

# Keep this file ASCII-only (see job-common.ps1).
#
# Windows Task Scheduler entry point for the 4-blog daily analysis tabs.
# Uses the same snapshot -> metrics -> diagnosis -> proposal -> report flow as
# the X consulting job, then rebuilds xaccounting-reports.html with 5 tabs.
# Auto-applies allowlisted, per-platform prompt_set hints from today's proposals
# via x_deploy (the same bounded deploy/rollback loop as X parameters), then
# verifies them. At generation time only canonical_platform's knobs are used.

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot "job-common.ps1")

$name = "blog-consulting"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = New-JobLogger -Repo $repo -Name $name -Stamp $stamp
$logDir = Split-Path -Parent $log

Get-ChildItem $logDir -Filter "$name-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 200 | Remove-Item -Force -ErrorAction SilentlyContinue

Write-JobLog $log "start skipllm=$($SkipLlm.IsPresent) nolive=$($NoLive.IsPresent) skipdeploy=$($SkipDeploy.IsPresent) skipverify=$($SkipVerify.IsPresent)"

$jobResult = Invoke-WithJobLock -Repo $repo -Log $log -Name $name -LockWaitMin $LockWaitMin -Body {
    Set-Location $repo
    $env:PYTHONIOENCODING = "utf-8"

    $pyArgs = @("scripts/blog_consultant.py")
    if ($SkipLlm) { $pyArgs += "--skip-llm" }
    if ($NoLive) { $pyArgs += "--no-live" }

    $outFile = Join-Path $logDir "$name-$stamp.out.tmp"
    $errFile = Join-Path $logDir "$name-$stamp.err.tmp"
    & python @pyArgs 1>$outFile 2>$errFile
    $exitCode = $LASTEXITCODE

    Write-JobLog $log "--- stdout ---"
    if (Test-Path $outFile) { Get-Content $outFile | Out-File -FilePath $log -Append -Encoding utf8 }
    Write-JobLog $log "--- stderr ---"
    if (Test-Path $errFile) { Get-Content $errFile | Out-File -FilePath $log -Append -Encoding utf8 }

    $lastLine = ""
    if (Test-Path $outFile) {
        $lastLine = (Get-Content $outFile | Where-Object { $_.Trim() -ne "" } | Select-Object -Last 1)
    }
    $lastErr = ""
    if (Test-Path $errFile) {
        $lastErr = (Get-Content $errFile | Where-Object { $_.Trim() -ne "" } | Select-Object -Last 1)
    }
    Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue

    if ($exitCode -ne 0) {
        $detail = if ($lastErr) { $lastErr } else { $lastLine }
        return @{ state = "failed"; detail = "exit code ${exitCode}: $detail" }
    }

    $deployDetail = ""
    if (-not $SkipDeploy) {
        $today = Get-Date -Format "yyyy-MM-dd"
        $proposalFiles = @()
        foreach ($platform in @("github", "hatena", "ameba", "note")) {
            $candidate = Join-Path $repo "data\blog-consulting\$platform\proposals\$today.json"
            if (Test-Path $candidate) { $proposalFiles += $candidate }
        }
        if ($proposalFiles.Count -gt 0) {
            Write-JobLog $log "--- deploy --auto-safe (blog prompts) ---"
            $dOut = Join-Path $logDir "$name-$stamp.deploy.out.tmp"
            $dErr = Join-Path $logDir "$name-$stamp.deploy.err.tmp"
            $dArgs = @("scripts/x_deploy.py")
            foreach ($proposalFile in $proposalFiles) { $dArgs += @("--proposal", $proposalFile) }
            $dArgs += "--auto-safe"
            & python @dArgs 1>$dOut 2>$dErr
            $dExit = $LASTEXITCODE
            if (Test-Path $dOut) { Get-Content $dOut | Out-File -FilePath $log -Append -Encoding utf8 }
            if (Test-Path $dErr) { Get-Content $dErr | Out-File -FilePath $log -Append -Encoding utf8 }
            if (Test-Path $dOut) {
                $deployDetail = (Get-Content $dOut | Where-Object { $_.Trim() -ne "" } | Select-Object -Last 1)
            }
            Remove-Item $dOut, $dErr -Force -ErrorAction SilentlyContinue
            if ($dExit -ne 0) {
                Write-JobLog $log "deploy failed exit=$dExit (blog report already generated)"
            }
        } else {
            Write-JobLog $log "deploy skipped: no proposal for $today"
        }
    }

    $verifyDetail = ""
    if (-not $SkipVerify) {
        Write-JobLog $log "--- verify --apply-rollbacks ---"
        $vOut = Join-Path $logDir "$name-$stamp.verify.out.tmp"
        $vErr = Join-Path $logDir "$name-$stamp.verify.err.tmp"
        & python @("scripts/x_verify.py", "--apply-rollbacks") 1>$vOut 2>$vErr
        $vExit = $LASTEXITCODE
        if (Test-Path $vOut) { Get-Content $vOut | Out-File -FilePath $log -Append -Encoding utf8 }
        if (Test-Path $vErr) { Get-Content $vErr | Out-File -FilePath $log -Append -Encoding utf8 }
        if (Test-Path $vOut) {
            $verifyDetail = (Get-Content $vOut | Where-Object { $_.Trim() -ne "" } | Select-Object -Last 1)
        }
        Remove-Item $vOut, $vErr -Force -ErrorAction SilentlyContinue
        if ($vExit -ne 0) {
            Write-JobLog $log "verify failed exit=$vExit (blog report already generated)"
        }
    }

    # Publish the new dashboard/tabs immediately. The HTTP server also syncs on
    # request, but its Python process keeps old code in memory until restarted,
    # so do this from the generator job as well (idempotent).
    $syncOut = Join-Path $logDir "$name-$stamp.sync.out.tmp"
    $syncErr = Join-Path $logDir "$name-$stamp.sync.err.tmp"
    & python -c "import sys; sys.path.insert(0, 'scripts'); import x_report_server; x_report_server.sync_publish_dir()" 1>$syncOut 2>$syncErr
    $syncExit = $LASTEXITCODE
    $syncErrText = ""
    if (Test-Path $syncErr) {
        $syncErrText = (Get-Content $syncErr | Where-Object { $_.Trim() -ne "" } | Select-Object -Last 1)
    }
    Remove-Item $syncOut, $syncErr -Force -ErrorAction SilentlyContinue
    if ($syncExit -ne 0) {
        return @{ state = "failed"; detail = "publish sync failed (exit ${syncExit}): $syncErrText" }
    }

    $parts = @($lastLine)
    if ($deployDetail) { $parts += "deploy: $deployDetail" }
    if ($verifyDetail) { $parts += "verify: $verifyDetail" }
    $detail = ($parts | Where-Object { $_ }) -join " | "
    return @{ state = "finished"; detail = $detail }
}

Write-JobLog $log "done"
if ($jobResult -and $jobResult.state -eq "failed") { exit 1 }
