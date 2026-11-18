param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Prompt,
    # Passed straight to opencode as provider/model#variant. Pinned here so an interactive
    # session's /model choice can never change an unattended run (2026-10-03 image-forgery incident).
    # -Model is stage 1; -FallbackModels is a semicolon-separated list for stages 2-4.
    [string]$Model = "opencode/big-pickle",
    [string]$FallbackModels = "",
    [int]$TimeoutMin = 50,
    [int]$LockWaitMin = 20
)

# Keep this file ASCII-only: Windows PowerShell 5.1 reads BOM-less scripts as the ANSI code page.
#
# Windows Task Scheduler entry point for the blog jobs (blog-post / topic-planning / topic-topup).
# The file name is kept for compatibility with existing task actions and log names, but Claude Code
# is no longer launched. All jobs run through opencode and switch models on failure (4 stages):
#   - blog-post       : gemini-3.5-flash#high -> gemini-3.5-flash-lite -> deepseek-free -> longcat-free
#   - topic-planning  : big-pickle -> gemini-lite -> gemini-high -> deepseek-free
#   - topic-topup     : same as topic-planning
# big-pickle is never used for article bodies (2026-10-02 mixed-language / false-completion incident).
# A machine-wide mutex serialises the jobs, so the git and browser-automation steps never overlap.
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

# Runs the opencode CLI with -Model to completion (or timeout) and returns @{ state; detail }.
# opencode run takes the message as an argument; the scheduled prompts are single-line, so they
# survive the Windows command-line quoting (a multi-line argument would be cut at the first newline).
function Invoke-OpenCode([string]$AttemptModel, [int]$AttemptNo) {
    $exe = (Get-Command opencode.cmd -ErrorAction SilentlyContinue).Source
    if (-not $exe) { $exe = "C:\Users\norio\AppData\Roaming\npm\opencode.cmd" }
    if (-not (Test-Path $exe)) { return @{ state = "failed"; detail = "launch error: executable not found: $exe" } }
    $argList = @("run", "--model", $AttemptModel, "--agent", "build", "--auto", "--archived", $Prompt)
    # Start-Process (PS 5.1) does not quote array elements, so quote by hand.
    $argString = ($argList | ForEach-Object {
        if ($_ -match '[\s"()*&|]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join " "
    $outFile = Join-Path $logDir "$Name-$stamp-$AttemptNo.out.tmp"
    $errFile = Join-Path $logDir "$Name-$stamp-$AttemptNo.err.tmp"
    # Give the engine an empty stdin so it never waits for input.
    $inFile = Join-Path $logDir "$Name-$stamp-$AttemptNo.in.tmp"
    New-Item -ItemType File -Force -Path $inFile | Out-Null
    Write-Log "launch opencode stage ${AttemptNo}: $AttemptModel"
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
        Write-Log "opencode exited code=$($p.ExitCode)"
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

$modelChain = @(@($Model) + @($FallbackModels -split '[;,]') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
Write-Log "start name=$Name models=$($modelChain -join ' -> ') timeout=${TimeoutMin}m"

$mutex = New-Object System.Threading.Mutex($false, "Local\kingsworksub-blog-x-jobs")
$held = $false
$final = $null
try {
    try { $held = $mutex.WaitOne([TimeSpan]::FromMinutes($LockWaitMin)) }
    catch [System.Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) { Write-Log "another job held the lock for ${LockWaitMin}m; skipping this run"; exit 0 }

    Set-Location $repo
    $env:PYTHONIOENCODING = "utf-8"
    # Generation must use the documented chain in scripts/model_chains.py. A stale
    # user-level override (OC_GENERATE_MODEL=...lite was left set) silently made every
    # post start on the weakest model; clear both escape hatches for scheduled runs.
    $env:OC_GENERATE_MODEL = ""
    $env:OC_GENERATE_MODEL_CHAIN = ""
    Publish-Status "started" ""

    $isPost = ($Name -eq "blog-post")
    $snap = Join-Path $logDir "$Name-$stamp.snap.json"
    Invoke-Py @("snapshot", $snap) | Out-Null
    if ($isPost) {
        $preCount = [int](Invoke-Py @("today-count"))
        $preHealth = [int](Invoke-Py @("health"))
    }

    $attemptLog = @()
    $published = $false
    for ($i = 1; $i -le $modelChain.Count; $i++) {
        $attemptModel = $modelChain[$i - 1]
        Write-Log "attempt $i/$($modelChain.Count) model=$attemptModel"
        $res = Invoke-OpenCode -AttemptModel $attemptModel -AttemptNo $i
        $final = $res
        $attemptLog += ("stage{0} {1}={2}: {3}" -f $i, $attemptModel, $res.state, $res.detail)

        $published = $false
        if ($isPost) {
            $published = [int](Invoke-Py @("today-count")) -gt $preCount
            $stale = [int](Invoke-Py @("count", "in_progress"))
            $postHealth = [int](Invoke-Py @("health"))
            if (-not $published -and ($res.state -ne "finished" -or $stale -gt 0 -or $postHealth -gt $preHealth)) {
                $recovered = Invoke-Py @("recover", "--snapshot", $snap, "--reason", "stage $i ($attemptModel) did not publish ($($res.state)); cleaned up")
                Write-Log "recover after stage ${i}: $recovered"
                $preHealth = [int](Invoke-Py @("health"))
            }
        }
        # A clean finish (including an intentional reject / daily-limit exit) is not retried.
        # A publish is success even when the agent's last turn failed (e.g. a per-minute
        # rate limit after topic_plan complete); the post is already live.
        if ($res.state -eq "finished" -or $published) {
            if ($published -and $res.state -ne "finished") {
                Write-Log "published during stage $i ($attemptModel) despite exit state=$($res.state); recording success"
                $final = @{ state = "finished"; detail = ($attemptLog -join " | ") }
            }
            break
        }
    }
    $final = @{ state = $final.state; detail = ($attemptLog -join " | ") }
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
