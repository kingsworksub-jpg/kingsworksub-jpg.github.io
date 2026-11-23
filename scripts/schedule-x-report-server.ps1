# Registers blog-x-report-server-task: serves xaccounting-reports.html on the
# local network only, via scripts/scheduled/serve-x-report.ps1.
#
# The server binds to the physical LAN adapter IP chosen by the runner (never
# 0.0.0.0), so the report is visible from other devices on the same LAN but not
# from Tailscale or other interfaces. Port 8765.
#
# AtLogOn restarts it after a reboot/crash; MultipleInstances=IgnoreNew prevents
# a duplicate process. ExecutionTimeLimit PT0S == run indefinitely.
#
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/schedule-x-report-server.ps1
#        Stop-ScheduledTask    -TaskName blog-x-report-server-task
#        Disable-ScheduledTask -TaskName blog-x-report-server-task

$taskName = "blog-x-report-server-task"
$repo = "C:\Users\norio\my-github-blog"
$runner = Join-Path $repo "scripts\scheduled\serve-x-report.ps1"

$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`"" `
    -WorkingDirectory $repo
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Trigger $trigger -Action $action -Settings $settings `
    -Principal $principal `
    -Description "Serve X accounting report on LAN only (http://<LAN-IP>:8765/)" `
    -Force | Out-Null

Start-ScheduledTask -TaskName $taskName
Write-Host "registered and started $taskName (LAN only, port 8765)"
Get-ScheduledTask -TaskName $taskName | Get-ScheduledTaskInfo | Select-Object TaskName, State, LastTaskResult
