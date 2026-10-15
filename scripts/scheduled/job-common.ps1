# Shared helpers for new, non-Claude Windows Task Scheduler entry points under scripts/scheduled/.
# Dot-sourced by run-platform-sync.ps1.
#
# Deliberately NOT wired into run-claude-task.ps1: that script already works and is relied on
# by three live scheduled jobs (blog-automation-task / blog-topic-planning / blog-topic-topup)
# running unattended; refactoring it to share this code would risk destabilizing it for a benefit
# (de-duplication) that isn't worth that risk. The mutex these helpers use is a plain OS-level
# named mutex ("Local\kingsworksub-blog-x-jobs"), so a new script using it here still serializes
# correctly against run-claude-task.ps1's jobs without sharing any code with it.
#
# Keep this file ASCII-only: Windows PowerShell 5.1 reads a BOM-less script as the ANSI code
# page, and this repo's content is Japanese.

function New-JobLogger {
    param([string]$Repo, [string]$Name, [string]$Stamp)
    $logDir = Join-Path $Repo "scripts\scheduled\logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    return (Join-Path $logDir "$Name-$Stamp.log")
}

function Write-JobLog {
    param([string]$Log, [string]$Msg)
    "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Msg | Out-File -FilePath $Log -Append -Encoding utf8
}

function Invoke-TopicPlanPy {
    param([string[]]$PyArgs)
    $env:PYTHONIOENCODING = "utf-8"
    $out = & python scripts/topic_plan.py @PyArgs 2>$null
    return ($out | Out-String).Trim()
}

# Records this run in scripts/pipeline-status.json and pushes it, so the Android app shows every
# run (including launch failures). Only call this while holding the mutex (Invoke-WithJobLock
# below already does).
function Publish-JobStatus {
    param([string]$Repo, [string]$Log, [string]$Name, [string]$State, [string]$Detail)
    try {
        Push-Location $Repo
        $Detail = ("$Detail" -replace '"', "'")
        $statusArgs = @("run-status", "--job", $Name, "--state", $State)
        if ($Detail) { $statusArgs += @("--detail", $Detail) }
        Invoke-TopicPlanPy $statusArgs | Out-Null
        & git add scripts/pipeline-status.json 2>&1 | Out-Null
        & git commit -q -m "Status: $Name $State" -- scripts/pipeline-status.json 2>&1 | Out-Null
        & git pull -q --rebase --autostash origin main 2>&1 | Out-Null
        & git push -q origin main 2>&1 | Out-Null
        Write-JobLog $Log "status pushed: $State"
    } catch {
        Write-JobLog $Log "status push failed: $($_.Exception.Message)"
    } finally {
        Pop-Location
    }
}

# Acquires the shared cross-job mutex, runs $Body (a no-arg scriptblock that must return
# @{ state; detail }) while holding it, pushes that result via Publish-JobStatus, then always
# releases the mutex. Skips the run (does not call $Body) if another job still holds the lock
# after $LockWaitMin minutes, same as run-claude-task.ps1's behavior.
function Invoke-WithJobLock {
    param([string]$Repo, [string]$Log, [string]$Name, [int]$LockWaitMin, [scriptblock]$Body)
    $mutex = New-Object System.Threading.Mutex($false, "Local\kingsworksub-blog-x-jobs")
    $held = $false
    $final = $null
    try {
        try { $held = $mutex.WaitOne([TimeSpan]::FromMinutes($LockWaitMin)) }
        catch [System.Threading.AbandonedMutexException] { $held = $true }
        if (-not $held) {
            Write-JobLog $Log "another job held the lock for ${LockWaitMin}m; skipping this run"
            return
        }

        Set-Location $Repo
        $env:PYTHONIOENCODING = "utf-8"
        Publish-JobStatus $Repo $Log $Name "started" ""
        try {
            $final = & $Body
        } catch {
            Write-JobLog $Log "ERROR: $($_.Exception.Message)"
            $final = @{ state = "failed"; detail = "error: $($_.Exception.Message)" }
        }
    } finally {
        if ($held) {
            if ($final) { Publish-JobStatus $Repo $Log $Name $final.state $final.detail }
            $mutex.ReleaseMutex()
        }
        $mutex.Dispose()
        Write-JobLog $Log "end"
    }
}
