param(
    [int]$LockWaitMin = 10,
    [switch]$DryRun
)

# Keep this file ASCII-only (see job-common.ps1).
#
# Windows Task Scheduler entry point for PPP (post-platform) reconciliation: applies platform
# changes requested from the netaManager Android app (scripts/ppp-requests/*.json) by diffing
# them against scripts/post-platforms.json and calling the relevant publish/delete scripts.
#
# Deliberately does NOT launch Claude Code (unlike run-claude-task.ps1's jobs): this work is
# mechanical (diff a platform list, call an existing script, commit) and an LLM agent in the
# loop of an unattended, partly-destructive operation would make it non-deterministic for no
# benefit. scripts/platform_sync.py does the actual work; this script only provides the same
# cross-job mutex, logging and status-push plumbing the other scheduled jobs use.
#
# Safety net: platform_sync.py's own git_commit_push treats a push failure as non-fatal (so one
# transient network hiccup mid-run doesn't abort processing of the remaining slugs), which can
# leave local-only commits behind. The final `git push` below sweeps up anything like that so it
# reaches origin by the end of this run at the latest, even if platform_sync.py itself errored.

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot "job-common.ps1")

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = New-JobLogger -Repo $repo -Name "ppp-reconcile" -Stamp $stamp
$logDir = Split-Path -Parent $log

Get-ChildItem $logDir -Filter "ppp-reconcile-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 200 | Remove-Item -Force -ErrorAction SilentlyContinue

Write-JobLog $log "start dryrun=$($DryRun.IsPresent)"

Invoke-WithJobLock -Repo $repo -Log $log -Name "ppp-reconcile" -LockWaitMin $LockWaitMin -Body {
    Set-Location $repo
    $env:PYTHONIOENCODING = "utf-8"

    $pyArgs = @("scripts/platform_sync.py", "reconcile")
    if ($DryRun) { $pyArgs += "--dry-run" }

    $outFile = Join-Path $logDir "ppp-reconcile-$stamp.out.tmp"
    $errFile = Join-Path $logDir "ppp-reconcile-$stamp.err.tmp"
    & python @pyArgs 1>$outFile 2>$errFile
    $exitCode = $LASTEXITCODE

    Write-JobLog $log "--- stdout ---"
    if (Test-Path $outFile) { Get-Content $outFile -Encoding utf8 | Out-File -FilePath $log -Append -Encoding utf8 }
    Write-JobLog $log "--- stderr ---"
    if (Test-Path $errFile) { Get-Content $errFile -Encoding utf8 | Out-File -FilePath $log -Append -Encoding utf8 }

    $lastLine = ""
    if (Test-Path $outFile) {
        $lastLine = (Get-Content $outFile -Encoding utf8 | Where-Object { $_.Trim() -ne "" } | Select-Object -Last 1)
    }
    Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue

    # Safety-net push: catches up any local-only commits platform_sync.py's own (best-effort)
    # push left behind, whether or not the script itself exited cleanly.
    Push-Location $repo
    & git push -q origin main 2>&1 | Out-Null
    Pop-Location

    if ($exitCode -eq 0) {
        return @{ state = "finished"; detail = $lastLine }
    } else {
        return @{ state = "failed"; detail = "exit code ${exitCode}: $lastLine" }
    }
}

Write-JobLog $log "done"
