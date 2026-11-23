param(
    [int]$LockWaitMin = 15,
    [switch]$DryRun
)

# Keep this file ASCII-only (see job-common.ps1).
#
# Windows Task Scheduler entry point for X auto-improvement.
# Picks one next action from the latest consulting proposal, generates a post via LLM,
# optionally resolves a relevant link, and posts it (native text + first-reply link by default).

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot "job-common.ps1")

$name = "x-auto-improve"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = New-JobLogger -Repo $repo -Name $name -Stamp $stamp
$logDir = Split-Path -Parent $log

Get-ChildItem $logDir -Filter "$name-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 200 | Remove-Item -Force -ErrorAction SilentlyContinue

Write-JobLog $log "start dryrun=$($DryRun.IsPresent)"

$jobResult = Invoke-WithJobLock -Repo $repo -Log $log -Name $name -LockWaitMin $LockWaitMin -Body {
    Set-Location $repo
    $env:PYTHONIOENCODING = "utf-8"

    $pyArgs = @("scripts/x_auto_improve.py")
    if (-not $DryRun) { $pyArgs += "--publish" }

    $outFile = Join-Path $logDir "$name-$stamp.out.tmp"
    $errFile = Join-Path $logDir "$name-$stamp.err.tmp"
    # The runner already holds the shared X job mutex; do not let Python take it twice.
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
    return @{ state = "finished"; detail = $lastLine }
}

Write-JobLog $log "done"
if ($jobResult -and $jobResult.state -eq "failed") { exit 1 }
