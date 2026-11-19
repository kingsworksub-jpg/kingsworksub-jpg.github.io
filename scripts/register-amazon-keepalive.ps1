# Register a Windows Scheduled Task that refreshes the Amazon Associates session.
#
# Usage (from the repository root):
#   powershell -ExecutionPolicy Bypass -File scripts\register-amazon-keepalive.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\register-amazon-keepalive.ps1 -IntervalMinutes 30
#   powershell -ExecutionPolicy Bypass -File scripts\register-amazon-keepalive.ps1 -Status
#   powershell -ExecutionPolicy Bypass -File scripts\register-amazon-keepalive.ps1 -Unregister
#
# NOTE: This file is intentionally ASCII-only. Windows PowerShell 5.1 reads
# BOM-less UTF-8 as ANSI, which breaks non-ASCII strings in .ps1 files.
# The task runs only while the user is logged on because gh stores its token
# with per-user DPAPI encryption. On session expiry the keepalive leaves the
# existing state and Secret untouched and only logs a warning.

param(
    [int]$IntervalMinutes = 20,
    [switch]$Unregister,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'

$TaskName = 'Blog-AmazonSessionKeepalive'
$Repo = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Repo 'scripts\amazon-session-keepalive.py'

if (-not (Test-Path -LiteralPath $Script)) {
    throw "Keepalive script not found: $Script"
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($Unregister) {
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "OK: task '$TaskName' removed."
    } else {
        Write-Host "SKIP: task '$TaskName' is not registered."
    }
    exit 0
}

if ($Status) {
    if (-not $existing) {
        Write-Host "SKIP: task '$TaskName' is not registered."
        exit 0
    }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "Task: $TaskName / State: $($existing.State)"
    Write-Host "Last run: $($info.LastRunTime) / Result: $($info.LastTaskResult)"
    Write-Host "Next run: $($info.NextRunTime)"
    exit 0
}

$python = (Get-Command python -ErrorAction Stop).Source
if ($python -like '*WindowsApps*') {
    throw "Python resolves to the Microsoft Store stub. Put python.org Python on PATH."
}

& $python -c "import playwright" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "playwright is missing: python -m pip install playwright"
}

$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $Script + '"') -WorkingDirectory $Repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Refresh Amazon Associates storage_state and update the GitHub Secret' -Force | Out-Null

Write-Host "OK: task '$TaskName' registered (every $IntervalMinutes minutes)."
Write-Host "    User: $env:USERNAME / Python: $python"
Write-Host "    Log: $Repo\data\amazon-keepalive.log"
Write-Host "    Status: $Repo\data\amazon_keepalive_status.json"
