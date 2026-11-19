param(
    [int]$Max = 5,
    [int]$LockWaitMin = 10,
    [switch]$DryRun
)

# Keep this file ASCII-only (see job-common.ps1).
#
# Windows Task Scheduler entry point for x-follow-dm: follow back new followers.
# Replaces the old run-claude-task.ps1 -Name x-follow-dm job. The DM text used to be generated
# inside post-to-x.py --auto-welcome via x_llm.py, but since 2026-11-19 (X temporary reach label)
# the scheduled job passes --no-dm and only follows back, so no LLM call happens here.
# This script supplies the shared cross-job mutex, logging and status-push plumbing.
#
# -DryRun still opens X, but does not follow or change any state.

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot "job-common.ps1")

$name = "x-follow-dm"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = New-JobLogger -Repo $repo -Name $name -Stamp $stamp
$logDir = Split-Path -Parent $log

Get-ChildItem $logDir -Filter "$name-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 200 | Remove-Item -Force -ErrorAction SilentlyContinue

Write-JobLog $log "start dryrun=$($DryRun.IsPresent) max=$Max"

Invoke-WithJobLock -Repo $repo -Log $log -Name $name -LockWaitMin $LockWaitMin -Body {
    Set-Location $repo
    $env:PYTHONIOENCODING = "utf-8"

    $pyArgs = @("scripts/post-to-x.py", "--auto-welcome", "--max", "$Max", "--no-dm")
    if (-not $DryRun) { $pyArgs += "--publish" }

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

    if ($exitCode -eq 0) {
        return @{ state = "finished"; detail = $lastLine }
    } else {
        $detail = if ($lastErr) { $lastErr } else { $lastLine }
        return @{ state = "failed"; detail = "exit code ${exitCode}: $detail" }
    }
}

Write-JobLog $log "done"
