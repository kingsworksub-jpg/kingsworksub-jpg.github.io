# Registers blog-content-consulting-task: daily analysis for GitHub / Hatena / Ameba / note.
# Rebuilds xaccounting-reports.html as a 5-tab dashboard (X + 4 blogs).
# Also applies allowlisted, per-platform blog-generation prompt tuning and
# verifies/rolls it back. Generation uses only canonical_platform's knobs.
#
# Keep this file ASCII-only (Windows PowerShell 5.1 reads BOM-less UTF-8 .ps1 as ANSI).
#
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/schedule-blog-consulting.ps1

$ErrorActionPreference = "Stop"
$taskName = "blog-content-consulting-task"
$repo = "C:\Users\norio\my-github-blog"
$runner = Join-Path $repo "scripts\scheduled\run-blog-consulting.ps1"
$user = "$env:USERDOMAIN\$env:USERNAME"

$triggerDaily = New-ScheduledTaskTrigger -Daily -At "07:25"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`" -LockWaitMin 15" `
    -WorkingDirectory $repo
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Trigger $triggerDaily -Action $action -Settings $settings `
    -Principal $principal `
    -Description "Daily 4-blog analysis + 5-tab dashboard + bounded auto prompt tuning" `
    -Force | Out-Null

Write-Host "registered $taskName (daily 07:25)"
Get-ScheduledTask -TaskName $taskName | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime, LastTaskResult
