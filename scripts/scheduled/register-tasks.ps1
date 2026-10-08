# Registers (or re-registers) the blog jobs in Windows Task Scheduler (2026-10-08 redesign:
# 8 runs/2h -> 6 fixed slots timed 30-60 min ahead of each traffic peak; see SLOTS in topic_plan.py).
#   blog-automation-task : posting job, 6 runs a day (07:30 / 12:00 / 17:30 / 20:00 / 21:30 / 23:00),
#                           prompt blog-post.md. Each run asks topic_plan.py for the current slot and
#                           claims a topic matching that slot's channel/content preference.
#   blog-topic-planning  : weekly topic meeting, Sunday 03:00, refills the queue to 64 topics
#   blog-topic-topup     : daily 04:00, refills only when fewer than 16 approved topics remain
# All three share the mutex in run-claude-task.ps1, so they never run at the same time.
# All jobs run on Claude Code (run-claude-task.ps1).

$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot "run-claude-task.ps1"
$user = "$env:USERDOMAIN\$env:USERNAME"

function Register-Job($taskName, $jobName, $prompt, $trigger, $timeoutMin, $lockWaitMin, $limitMin) {
    $argStr = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`" -Name $jobName -Prompt `"$prompt`" -TimeoutMin $timeoutMin -LockWaitMin $lockWaitMin"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argStr
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes $limitMin)
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "registered $taskName"
}

# Posting: 6 fixed times a day (30-60 min ahead of each traffic peak; see SLOTS in topic_plan.py).
$postTimes = "07:30", "12:00", "17:30", "20:00", "21:30", "23:00"
$postTriggers = $postTimes | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
Register-Job "blog-automation-task" "blog-post" "Read scripts/scheduled/prompts/blog-post.md and carry it out exactly." $postTriggers 60 20 80

$weekly = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "03:00"
Register-Job "blog-topic-planning" "topic-planning" "Read scripts/scheduled/prompts/topic-planning.md and carry it out exactly. Mode: weekly" $weekly 150 30 170

$topup = New-ScheduledTaskTrigger -Daily -At "04:00"
Register-Job "blog-topic-topup" "topic-topup" "Read scripts/scheduled/prompts/topic-planning.md and carry it out exactly. Mode: topup" $topup 120 30 140
