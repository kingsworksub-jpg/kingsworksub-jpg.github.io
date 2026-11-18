# Registers (or re-registers) the blog jobs in Windows Task Scheduler (2026-10-08 redesign:
# 8 runs/2h -> 6 fixed slots timed 30-60 min ahead of each traffic peak; see slots_for_date in
# topic_plan.py. 2026-10-11: the 20:00/23:00 slots swap channel on odd/even calendar days so
# github/hatena/ameba/note each get an equal 3-of-12 share over any 2-day window).
#   blog-automation-task : posting job, 6 runs a day (07:30 / 12:00 / 17:30 / 20:00 / 21:30 / 23:00),
#                           prompt blog-post.md. Each run asks topic_plan.py for the current slot and
#                           claims a topic matching that slot's channel/content preference.
#   blog-topic-planning  : weekly topic meeting, Sunday 03:00, refills the queue to 64 topics
#   blog-topic-topup     : daily 04:00, refills only when fewer than 16 approved topics remain
# All three share the mutex in run-claude-task.ps1, so they never run at the same time.
# Each job now uses a 4-stage model chain (-Model + -FallbackModels), like the X jobs:
#   blog-post      : gemini-3.5-flash#high -> gemini-3.5-flash-lite -> deepseek-free -> longcat-free
#   topic jobs     : big-pickle -> gemini-lite -> gemini-high -> deepseek-free
# big-pickle is stage 1 for planning only; it is never used to write article bodies.

$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot "run-claude-task.ps1"
$syncRunner = Join-Path $PSScriptRoot "run-platform-sync.ps1"
$user = "$env:USERDOMAIN\$env:USERNAME"

# Stage 1 is passed as -Model; stages 2-4 as a semicolon-separated -FallbackModels argument.
$postModels = @("google/gemini-3.5-flash#high", "google/gemini-3.5-flash-lite",
                "opencode/deepseek-v4.1-flash-free", "opencode/longcat-2.5-free")
$topicModels = @("opencode/big-pickle", "google/gemini-3.5-flash-lite",
                 "google/gemini-3.5-flash#high", "opencode/deepseek-v4.1-flash-free")

function Register-Job($taskName, $jobName, $prompt, $trigger, $timeoutMin, $lockWaitMin, $limitMin, $model, $fallbackModels) {
    $fallbackArg = $fallbackModels -join ";"
    $argStr = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`" -Name $jobName -Prompt `"$prompt`" -Model `"$model`" -FallbackModels `"$fallbackArg`" -TimeoutMin $timeoutMin -LockWaitMin $lockWaitMin"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argStr
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes $limitMin)
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "registered $taskName"
}

# Same shape as Register-Job, but points at run-platform-sync.ps1 (no Claude Code involved --
# see that script's header) and is registered Disabled: PPP reconciliation can delete live posts
# on Hatena/Ameba/note, so it must be started manually a few times with Start-ScheduledTask and
# its logs checked clean before the trigger is enabled for real (Enable-ScheduledTask).
function Register-SyncJob($taskName, $trigger, $lockWaitMin, $limitMin) {
    $argStr = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$syncRunner`" -LockWaitMin $lockWaitMin"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argStr
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes $limitMin) -Disable
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "registered $taskName (disabled -- enable manually after a clean Start-ScheduledTask test run)"
}

# Posting: 6 fixed times a day (30-60 min ahead of each traffic peak; see slots_for_date in topic_plan.py).
$postTimes = "07:30", "12:00", "17:30", "20:00", "21:30", "23:00"
$postTriggers = $postTimes | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
Register-Job "blog-automation-task" "blog-post" "Read scripts/scheduled/prompts/blog-post.md and carry it out exactly." $postTriggers 60 20 80 $postModels[0] $postModels[1..3]

$weekly = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "03:00"
Register-Job "blog-topic-planning" "topic-planning" "Read scripts/scheduled/prompts/topic-planning.md and carry it out exactly. Mode: weekly" $weekly 150 30 170 $topicModels[0] $topicModels[1..3]

$topup = New-ScheduledTaskTrigger -Daily -At "04:00"
Register-Job "blog-topic-topup" "topic-topup" "Read scripts/scheduled/prompts/topic-planning.md and carry it out exactly. Mode: topup" $topup 120 30 140 $topicModels[0] $topicModels[1..3]

# PPP reconciliation: applies platform changes requested from the netaManager app. Hourly (not
# 15-30 min) to keep mutex contention with the 6 daily posting slots low -- see run-platform-sync.ps1.
# The repetition duration must be a plain 10-year span: [TimeSpan]::MaxValue formats to
# P99999999DT23H59M59S, which Register-ScheduledTask rejects as out of range (HRESULT 0x80041318).
$pppSync = New-ScheduledTaskTrigger -Once -At "00:00" -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)
Register-SyncJob "blog-ppp-reconcile" $pppSync 10 30
