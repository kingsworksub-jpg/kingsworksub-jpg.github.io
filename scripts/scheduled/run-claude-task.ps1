param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Prompt,
    [string]$Model = "",
    [int]$TimeoutMin = 50,
    [int]$LockWaitMin = 20,
    [ValidateSet("auto", "claude", "big-pickle")][string]$Engine = "auto"
)

# Engine policy (2026-10-01, user instruction): alternate daily between Claude Code and
# opencode big-pickle. Day 0 = 2026-10-01 = claude; must match ENGINE_EPOCH in scripts/topic_plan.py.
if ($Engine -eq "auto") {
    $dayIndex = ([datetime]::Today - [datetime]"2026-10-01").Days
    $Engine = if ($dayIndex % 2 -eq 0) { "claude" } else { "big-pickle" }
}

# Windows Task Scheduler entry point. Runs one headless Claude Code turn in the blog repo.
# A machine-wide mutex serialises jobs. As of 2026-09-29 KingsWork-X-Jazz (the overseas
# jazz X-post job) has been removed at the user's request, so blog-drink is the only
# remaining job. The mutex is kept: it costs nothing and stops a future second job
# from overlapping the hatena/note browser-automation steps, which cannot run
# concurrently (Playwright drives a real Chromium window and the keyboard).

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir "$Name-$stamp.log"

function Write-Log($msg) { "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg | Out-File -FilePath $log -Append -Encoding utf8 }

# Keep this file ASCII-only: Windows PowerShell 5.1 reads BOM-less scripts as the ANSI code page.
# Records this run in scripts/pipeline-status.json and pushes it, so the Android app shows every run
# (including launch failures and timeouts). Only called while holding the lock, so no job is mid-git.
# Name is the job id used by topic_plan.py (blog-post / topic-planning / topic-topup).
function Publish-Status($state, $detail) {
    try {
        Push-Location $repo
        $env:PYTHONIOENCODING = "utf-8"
        $detail = ("$detail" -replace '"', "'")
        # PowerShell 5.1 drops empty-string arguments, so only pass --detail when there is one.
        $statusArgs = @("scripts/topic_plan.py", "run-status", "--job", $Name, "--state", $state)
        if ($detail) { $statusArgs += @("--detail", $detail) }
        & python @statusArgs 2>&1 | Out-Null
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

# Keep only the newest 200 logs.
Get-ChildItem $logDir -Filter *.log | Sort-Object LastWriteTime -Descending | Select-Object -Skip 200 | Remove-Item -Force -ErrorAction SilentlyContinue

Write-Log "start name=$Name engine=$Engine model=$Model timeout=${TimeoutMin}m"

$mutex = New-Object System.Threading.Mutex($false, "Local\kingsworksub-blog-x-jobs")
$held = $false
try {
    try { $held = $mutex.WaitOne([TimeSpan]::FromMinutes($LockWaitMin)) }
    catch [System.Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) { Write-Log "another job held the lock for ${LockWaitMin}m; skipping this run"; exit 0 }

    Set-Location $repo
    $env:PYTHONIOENCODING = "utf-8"
    $env:BLOG_ENGINE = $Engine
    Publish-Status "started" ""
    $runState = "failed"
    $runDetail = ""
    $enginePrompt = "$Prompt (Today's engine: $Engine)"
    if ($Engine -eq "big-pickle") {
        $exe = "C:\Users\norio\AppData\Roaming\npm\node_modules\opencode-ai\bin\opencode.exe"
        $argList = @("run", $enginePrompt, "-m", "opencode/big-pickle", "--dir", $repo)
    } else {
        $exe = "C:\Users\norio\AppData\Local\Microsoft\WinGet\Links\claude.exe"
        $allowed = @(
            "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "Agent",
            "Bash(hugo:*)", "Bash(git:*)", "Bash(gh:*)", "Bash(curl:*)", "Bash(ls:*)", "Bash(mkdir:*)", "Bash(cp:*)", "Bash(rm:*)",
            "Bash(bash scripts/*)",
            "Bash(cd /c/Users/norio/my-github-blog/scripts && .venv/Scripts/python.exe *)",
            "Bash(cd /c/Users/norio/my-github-blog && python scripts/*)",
            "Bash(python scripts/*)", "Bash(python -c *)"
        )
        $argList = @("-p", $enginePrompt, "--permission-mode", "auto", "--no-session-persistence", "--allowedTools") + $allowed
        if ($Model) { $argList += @("--model", $Model) }
    }
    # Start-Process (PS 5.1) does not quote array elements, so quote by hand.
    $argString = ($argList | ForEach-Object {
        if ($_ -match '[\s"()*&|]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join " "

    if (-not (Test-Path $exe)) { throw "executable not found: $exe" }
    $outFile = Join-Path $logDir "$Name-$stamp.out.tmp"
    $errFile = Join-Path $logDir "$Name-$stamp.err.tmp"
    # opencode run reads piped stdin until EOF, so give every engine an empty stdin to avoid an endless wait.
    $inFile = Join-Path $logDir "$Name-$stamp.in.tmp"
    New-Item -ItemType File -Force -Path $inFile | Out-Null
    $p = Start-Process -FilePath $exe -ArgumentList $argString -WorkingDirectory $repo -NoNewWindow -PassThru `
        -RedirectStandardInput $inFile -RedirectStandardOutput $outFile -RedirectStandardError $errFile -ErrorAction Stop
    $null = $p.Handle
    if (-not $p.WaitForExit($TimeoutMin * 60 * 1000)) {
        Write-Log "TIMEOUT after ${TimeoutMin}m; killing process tree"
        & taskkill /PID $p.Id /T /F | Out-Null
        $runState = "timeout"
        $runDetail = "timed out after ${TimeoutMin} min ($Engine)"
    } else {
        Write-Log "$Engine exited code=$($p.ExitCode)"
        $runState = if ($p.ExitCode -eq 0) { "finished" } else { "failed" }
        $lastLine = ""
        if (Test-Path $outFile) {
            $lastLine = (Get-Content $outFile -Encoding utf8 | Where-Object { $_.Trim() -ne "" } | Select-Object -Last 1)
        }
        $runDetail = if ($lastLine) { "$lastLine" } else { "exit code $($p.ExitCode)" }
    }
    Write-Log "--- stdout ---"
    if (Test-Path $outFile) { Get-Content $outFile -Encoding utf8 | Out-File -FilePath $log -Append -Encoding utf8 }
    Write-Log "--- stderr ---"
    if (Test-Path $errFile) { Get-Content $errFile -Encoding utf8 | Out-File -FilePath $log -Append -Encoding utf8 }
    Remove-Item $outFile, $errFile, $inFile -Force -ErrorAction SilentlyContinue
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    $runState = "failed"
    $runDetail = "launch error: $($_.Exception.Message)"
}
finally {
    if ($held) {
        if ($runState) { Publish-Status $runState $runDetail }
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
    Write-Log "end"
}
