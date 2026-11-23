param(
    [int]$LockWaitMin = 15,
    [switch]$DryRun,
    [switch]$SkipLlm,
    [switch]$SkipVerify
)

# Keep this file ASCII-only (see job-common.ps1).
#
# Windows Task Scheduler entry point for daily X consulting + self-improvement.
# Collects account snapshot/metrics, writes report artifacts, auto-applies bounded rule
# changes from the latest proposal, and auto-rolls back degraded deployments.

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot "job-common.ps1")

$name = "x-consulting"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = New-JobLogger -Repo $repo -Name $name -Stamp $stamp
$logDir = Split-Path -Parent $log

Get-ChildItem $logDir -Filter "$name-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 200 | Remove-Item -Force -ErrorAction SilentlyContinue

Write-JobLog $log "start dryrun=$($DryRun.IsPresent) skipllm=$($SkipLlm.IsPresent) skipverify=$($SkipVerify.IsPresent)"

$jobResult = Invoke-WithJobLock -Repo $repo -Log $log -Name $name -LockWaitMin $LockWaitMin -Body {
    Set-Location $repo
    $env:PYTHONIOENCODING = "utf-8"

    $pyArgs = @("scripts/x_consultant.py")
    if ($DryRun) { $pyArgs += "--dry-run" }
    if ($SkipLlm) { $pyArgs += "--skip-llm" }

    $outFile = Join-Path $logDir "$name-$stamp.out.tmp"
    $errFile = Join-Path $logDir "$name-$stamp.err.tmp"
    # The runner already holds the shared X job mutex. Tell Python not to take it again,
    # otherwise it times out against this very process (the 11/23 + 11/24 failures).
    $prevSkipMutex = $env:X_SKIP_JOB_MUTEX
    $env:X_SKIP_JOB_MUTEX = "1"
    try {
        & python @pyArgs 1>$outFile 2>$errFile
        $exitCode = $LASTEXITCODE
    } finally {
        if ($null -eq $prevSkipMutex) {
            Remove-Item Env:X_SKIP_JOB_MUTEX -ErrorAction SilentlyContinue
        } else {
            $env:X_SKIP_JOB_MUTEX = $prevSkipMutex
        }
    }

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

    # Phase 3: auto-deploy rule changes from latest proposal (bounded by hard cap/step/cooldown).
    $deployDetail = ""
    $proposalFile = Get-ChildItem "data\x-consulting\proposals\*.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($proposalFile) {
        Write-JobLog $log "--- deploy --auto-safe ---"
        $dOut = Join-Path $logDir "$name-$stamp.deploy.out.tmp"
        $dErr = Join-Path $logDir "$name-$stamp.deploy.err.tmp"
        & python @("scripts/x_deploy.py", "--proposal", $proposalFile.FullName, "--auto-safe") 1>$dOut 2>$dErr
        $dExit = $LASTEXITCODE
        if (Test-Path $dOut) { Get-Content $dOut | Out-File -FilePath $log -Append -Encoding utf8 }
        if (Test-Path $dErr) { Get-Content $dErr | Out-File -FilePath $log -Append -Encoding utf8 }
        if (Test-Path $dOut) {
            $deployDetail = (Get-Content $dOut | Where-Object { $_.Trim() -ne "" } | Select-Object -Last 1)
        }
        Remove-Item $dOut, $dErr -Force -ErrorAction SilentlyContinue
        if ($dExit -ne 0) {
            Write-JobLog $log "deploy failed exit=$dExit (consulting report already generated)"
        }
    } else {
        Write-JobLog $log "deploy skipped: no proposal found"
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
            Write-JobLog $log "verify failed exit=$vExit (consulting report already generated)"
        }
    }

    $parts = @($lastLine)
    if ($deployDetail) { $parts += "deploy: $deployDetail" }
    if ($verifyDetail) { $parts += "verify: $verifyDetail" }
    $detail = ($parts | Where-Object { $_ }) -join " | "
    return @{ state = "finished"; detail = $detail }
}

Write-JobLog $log "done"
if ($jobResult -and $jobResult.state -eq "failed") { exit 1 }
