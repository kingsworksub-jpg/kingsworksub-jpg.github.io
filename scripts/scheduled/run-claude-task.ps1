param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Prompt,
    [string]$Model = "",
    [int]$TimeoutMin = 50,
    [int]$LockWaitMin = 20
)

# Windows Task Scheduler entry point. Runs one headless Claude Code turn in the blog repo.
# A machine-wide mutex serialises jobs: X posting drives the real Edge window via
# pyautogui/clipboard, so two jobs must never post at the same time.

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir "$Name-$stamp.log"

function Write-Log($msg) { "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg | Out-File -FilePath $log -Append -Encoding utf8 }

# Keep only the newest 200 logs.
Get-ChildItem $logDir -Filter *.log | Sort-Object LastWriteTime -Descending | Select-Object -Skip 200 | Remove-Item -Force -ErrorAction SilentlyContinue

Write-Log "start name=$Name model=$Model timeout=${TimeoutMin}m"

$mutex = New-Object System.Threading.Mutex($false, "Local\kingsworksub-blog-x-jobs")
$held = $false
try {
    try { $held = $mutex.WaitOne([TimeSpan]::FromMinutes($LockWaitMin)) }
    catch [System.Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) { Write-Log "another job held the lock for ${LockWaitMin}m; skipping this run"; exit 0 }

    Set-Location $repo
    $claude = "C:\Users\norio\AppData\Local\Microsoft\WinGet\Links\claude.exe"
    $allowed = @(
        "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "Agent",
        "Bash(hugo:*)", "Bash(git:*)", "Bash(gh:*)", "Bash(curl:*)", "Bash(ls:*)", "Bash(mkdir:*)",
        "Bash(bash scripts/*)",
        "Bash(cd /c/Users/norio/Projects/kingsworksub-jpg.github.io/scripts/x-autopost && .venv/Scripts/python.exe *)"
    )
    $argList = @("-p", $Prompt, "--permission-mode", "auto", "--no-session-persistence", "--allowedTools") + $allowed
    if ($Model) { $argList += @("--model", $Model) }
    # Start-Process (PS 5.1) does not quote array elements, so quote by hand.
    $argString = ($argList | ForEach-Object {
        if ($_ -match '[\s"()*&|]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join " "

    $outFile = Join-Path $logDir "$Name-$stamp.out.tmp"
    $errFile = Join-Path $logDir "$Name-$stamp.err.tmp"
    $p = Start-Process -FilePath $claude -ArgumentList $argString -WorkingDirectory $repo -NoNewWindow -PassThru `
        -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    $null = $p.Handle
    if (-not $p.WaitForExit($TimeoutMin * 60 * 1000)) {
        Write-Log "TIMEOUT after ${TimeoutMin}m; killing process tree"
        & taskkill /PID $p.Id /T /F | Out-Null
    } else {
        $p.WaitForExit()
        Write-Log "claude exited code=$($p.ExitCode)"
    }
    Write-Log "--- stdout ---"
    if (Test-Path $outFile) { Get-Content $outFile -Encoding utf8 | Out-File -FilePath $log -Append -Encoding utf8 }
    Write-Log "--- stderr ---"
    if (Test-Path $errFile) { Get-Content $errFile -Encoding utf8 | Out-File -FilePath $log -Append -Encoding utf8 }
    Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
}
finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
    Write-Log "end"
}
