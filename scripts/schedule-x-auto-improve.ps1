# Registers blog-x-auto-improve-task: daily auto-improvement post from X consulting.
# Runs after consulting so it can use the latest proposal/rule changes.
#
# Keep this file ASCII-only (Windows PowerShell 5.1 reads BOM-less UTF-8 .ps1 as ANSI).
#
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/schedule-x-auto-improve.ps1

$ErrorActionPreference = "Stop"
$taskName = "blog-x-auto-improve-task"
$repo = "C:\Users\norio\my-github-blog"
$runner = Join-Path $repo "scripts\scheduled\run-x-auto-improve.ps1"
$user = "$env:USERDOMAIN\$env:USERNAME"

$triggerDaily = New-ScheduledTaskTrigger -Daily -At "07:45"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`" -LockWaitMin 15" `
    -WorkingDirectory $repo
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Trigger $triggerDaily -Action $action -Settings $settings `
    -Principal $principal `
    -Description "X: daily auto-improvement post from consulting next actions (LLM + optional link)" `
    -Force | Out-Null

Write-Host "registered $taskName (daily 07:45)"
Get-ScheduledTask -TaskName $taskName | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime, LastTaskResult
