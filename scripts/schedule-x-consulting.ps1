# Registers blog-x-consulting-task: daily X account analysis/report + auto rule tuning.
# Applies bounded rule changes from report and auto-rolls back degraded deployments.
#
# Keep this file ASCII-only (Windows PowerShell 5.1 reads BOM-less UTF-8 .ps1 as ANSI).
#
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/schedule-x-consulting.ps1

$ErrorActionPreference = "Stop"
$taskName = "blog-x-consulting-task"
$repo = "C:\Users\norio\my-github-blog"
$runner = Join-Path $repo "scripts\scheduled\run-x-consulting.ps1"
$user = "$env:USERDOMAIN\$env:USERNAME"

$triggerDaily = New-ScheduledTaskTrigger -Daily -At "07:10"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`" -LockWaitMin 15" `
    -WorkingDirectory $repo
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Trigger $triggerDaily -Action $action -Settings $settings `
    -Principal $principal `
    -Description "X: daily account analysis/report + auto rule tuning (bounded deploy + auto rollback)" `
    -Force | Out-Null

Write-Host "registered $taskName (daily 07:10)"
Get-ScheduledTask -TaskName $taskName | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime, LastTaskResult