# Registers (or re-registers) the blog jobs in Windows Task Scheduler (2026-10-01 redesign).
#   blog-automation-task : posting job, 8 runs a day (07:15-21:15 every 2h), prompt blog-post.md
#   blog-topic-planning  : weekly topic meeting, Sunday 03:00, refills the queue to 64 topics
#   blog-topic-topup     : daily 04:00, refills only when fewer than 16 approved topics remain
# All three share the mutex in run-claude-task.ps1, so they never run at the same time.
# The engine (Claude Code / opencode big-pickle) alternates daily inside run-claude-task.ps1.

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

# Posting: daily at 07:15, repeated every 2 hours for 14h15m -> 07:15, 09:15, ... 21:15 (8 runs).
$post = New-ScheduledTaskTrigger -Daily -At "07:15"
$post.Repetition = (New-ScheduledTaskTrigger -Once -At "07:15" -RepetitionInterval (New-TimeSpan -Hours 2) -RepetitionDuration (New-TimeSpan -Hours 14 -Minutes 15)).Repetition
Register-Job "blog-automation-task" "blog-post" "Read scripts/scheduled/prompts/blog-post.md and carry it out exactly." $post 60 20 80

$weekly = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "03:00"
Register-Job "blog-topic-planning" "topic-planning" "Read scripts/scheduled/prompts/topic-planning.md and carry it out exactly. Mode: weekly" $weekly 150 30 170

$topup = New-ScheduledTaskTrigger -Daily -At "04:00"
Register-Job "blog-topic-topup" "topic-topup" "Read scripts/scheduled/prompts/topic-planning.md and carry it out exactly. Mode: topup" $topup 120 30 140
