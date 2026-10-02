param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Prompt,
    [string]$Model = "",
    [int]$TimeoutMin = 50,
    [int]$LockWaitMin = 20
)

# Keep this file ASCII-only: Windows PowerShell 5.1 reads BOM-less scripts as the ANSI code page.
#
# Windows Task Scheduler entry point for the blog jobs (blog-post / topic-planning / topic-topup).
# Every job runs on Claude Code (2026-10-02, user instruction; the daily alternation with opencode
# big-pickle was dropped after big-pickle failed every article that day). A machine-wide mutex
# serialises the jobs, so the git and browser-automation steps never overlap.
# Cleanup: if a blog-post run publishes nothing and failed, timed out, abandoned its claimed topic or
# recorded a failure, topic_plan.py recover removes its unpushed commits and leftover files and returns
# the topic to the queue.

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir "$Name-$stamp.log"

function Write-Log($msg) { "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg | Out-File -FilePath $log -Append -Encoding utf8 }

function Invoke-Py([string[]]$pyArgs) {
    $env:PYTHONIOENCODING = "utf-8"
    $out = & python scripts/topic_plan.py @pyArgs 2>$null
    return ($out | Out-String).Trim()
}

# Records this run in scripts/pipeline-status.json and pushes it, so the Android app shows every run
# (including launch failures and timeouts). Only called while holding the lock, so no job is mid-git.
function Publish-Status($state, $detail) {
    try {
        Push-Location $repo
        $detail = ("$detail" -replace '"', "'")
        # PowerShell 5.1 drops empty-string arguments, so only pass --detail when there is one.
        $statusArgs = @("run-status", "--job", $Name, "--state", $state)
        if ($detail) { $statusArgs += @("--detail", $detail) }
        Invoke-Py $statusArgs | Out-Null
        & git add scripts/pipeline-status.json 2>&1 | Out-Null
        & git commit -q -m "Status: $Name $state" -- scripts/pipeline-status.json 2>&1 | Out-Null
        & git pull -q --rebase --autostash origin main 2>&1 | Out-Null
        & git push -q origin main 2>&1 | Out-Null
        Write-Log "status pushed: $state"
    } catch {
        Write-Log "status push failed: $($_.Exception.Message)"
    } finally {
        Pop-Location
    }
}

# Runs Claude Code to completion (or timeout) and returns @{ state; detail }.
function Invoke-Claude {
    $exe = "C:\Users\norio\AppData\Local\Microsoft\WinGet\Links\claude.exe"
    $allowed = @(
        "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "Agent",
        "Bash(hugo:*)", "Bash(git:*)", "Bash(gh:*)", "Bash(curl:*)", "Bash(ls:*)", "Bash(mkdir:*)", "Bash(cp:*)", "Bash(rm:*)",
        "Bash(bash scripts/*)",
        "Bash(cd /c/Users/norio/my-github-blog/scripts && .venv/Scripts/python.exe *)",
        "Bash(cd /c/Users/norio/my-github-blog && python scripts/*)",
        "Bash(python scripts/*)", "Bash(python -c *)"
    )
    $argList = @("-p", $Prompt, "--permission-mode", "auto", "--no-session-persistence", "--allowedTools") + $allowed
    if ($Model) { $argList += @("--model", $Model) }
    if (-not (Test-Path $exe)) { return @{ state = "failed"; detail = "launch error: executable not found: $exe" } }
    # Start-Process (PS 5.1) does not quote array elements, so quote by hand.
    $argString = ($argList | ForEach-Object {
        if ($_ -match '[\s"()*&|]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join " "
    $outFile = Join-Path $logDir "$Name-$stamp.out.tmp"
    $errFile = Join-Path $logDir "$Name-$stamp.err.tmp"
    # Give the engine an empty stdin so it never waits for input.
    $inFile = Join-Path $logDir "$Name-$stamp.in.tmp"
    New-Item -ItemType File -Force -Path $inFile | Out-Null
    Write-Log "launch claude"
    try {
        $p = Start-Process -FilePath $exe -ArgumentList $argString -WorkingDirectory $repo -NoNewWindow -PassThru `
            -RedirectStandardInput $inFile -RedirectStandardOutput $outFile -RedirectStandardError $errFile -ErrorAction Stop
    } catch {
        return @{ state = "failed"; detail = "launch error: $($_.Exception.Message)" }
    }
    $null = $p.Handle
    if (-not $p.WaitForExit($TimeoutMin * 60 * 1000)) {
        Write-Log "TIMEOUT after ${TimeoutMin}m; killing process tree"
        & taskkill /PID $p.Id /T /F | Out-Null
        $result = @{ state = "timeout"; detail = "timed out after ${TimeoutMin} min" }
    } else {
        Write-Log "claude exited code=$($p.ExitCode)"
        $lastLine = ""
        if (Test-Path $outFile) {
            $lastLine = (Get-Content $outFile -Encoding utf8 | Where-Object { $_.Trim() -ne "" } | Select-Object -Last 1)
        }
        $state = if ($p.ExitCode -eq 0) { "finished" } else { "failed" }
        $detail = if ($lastLine) { "$lastLine" } else { "exit code $($p.ExitCode)" }
        $result = @{ state = $state; detail = $detail }
    }
    Write-Log "--- stdout ---"
    if (Test-Path $outFile) { Get-Content $outFile -Encoding utf8 | Out-File -FilePath $log -Append -Encoding utf8 }
    Write-Log "--- stderr ---"
    if (Test-Path $errFile) { Get-Content $errFile -Encoding utf8 | Out-File -FilePath $log -Append -Encoding utf8 }
    Remove-Item $outFile, $errFile, $inFile -Force -ErrorAction SilentlyContinue
    return $result
}

# Keep only the newest 200 logs, and drop temp files a killed process may have left locked.
Get-ChildItem $logDir -Filter *.log | Sort-Object LastWriteTime -Descending | Select-Object -Skip 200 | Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem $logDir -Filter *.tmp | Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-3) } | Remove-Item -Force -ErrorAction SilentlyContinue

Write-Log "start name=$Name model=$Model timeout=${TimeoutMin}m"

$mutex = New-Object System.Threading.Mutex($false, "Local\kingsworksub-blog-x-jobs")
$held = $false
$final = $null
try {
    try { $held = $mutex.WaitOne([TimeSpan]::FromMinutes($LockWaitMin)) }
    catch [System.Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) { Write-Log "another job held the lock for ${LockWaitMin}m; skipping this run"; exit 0 }

    Set-Location $repo
    $env:PYTHONIOENCODING = "utf-8"
    Publish-Status "started" ""

    $isPost = ($Name -eq "blog-post")
    $snap = Join-Path $logDir "$Name-$stamp.snap.json"
    Invoke-Py @("snapshot", $snap) | Out-Null
    if ($isPost) {
        $preCount = [int](Invoke-Py @("today-count"))
        $preHealth = [int](Invoke-Py @("health"))
    }

    $final = Invoke-Claude

    if ($isPost) {
        $published = [int](Invoke-Py @("today-count")) -gt $preCount
        $stale = [int](Invoke-Py @("count", "in_progress"))
        $postHealth = [int](Invoke-Py @("health"))
        if (-not $published -and ($final.state -ne "finished" -or $stale -gt 0 -or $postHealth -gt $preHealth)) {
            $recovered = Invoke-Py @("recover", "--snapshot", $snap, "--reason", "run did not publish ($($final.state)); cleaned up")
            Write-Log "recover: $recovered"
        }
    }
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    $final = @{ state = "failed"; detail = "launch error: $($_.Exception.Message)" }
}
finally {
    if ($held) {
        if ($final) { Publish-Status $final.state $final.detail }
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
    Remove-Item (Join-Path $logDir "$Name-$stamp.snap.json") -Force -ErrorAction SilentlyContinue
    Write-Log "end"
}
