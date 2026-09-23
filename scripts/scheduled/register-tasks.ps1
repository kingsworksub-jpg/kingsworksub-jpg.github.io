# Registers (or re-registers) the two recurring jobs in Windows Task Scheduler.
#   Blog-Drink : carbonated-drink article, every 60 min (at :15)
#   X-Jazz     : overseas jazz X post,      every 30 min (at :00/:30)
# Run as the interactive user: X posting needs the logged-in, unlocked desktop (pyautogui + Edge).

$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot "run-claude-task.ps1"
$user = "$env:USERDOMAIN\$env:USERNAME"

function Get-NextSlot([int]$intervalMin, [int]$offsetMin) {
    $now = Get-Date
    $t = $now.Date.AddHours($now.Hour).AddMinutes($offsetMin)
    while ($t -le $now.AddMinutes(1)) { $t = $t.AddMinutes($intervalMin) }
    return $t
}

function Register-Job($taskName, $jobName, $promptFile, $model, $intervalMin, $offsetMin, $timeoutMin, $lockWaitMin, $limitMin) {
    $prompt = "Read scripts/scheduled/prompts/$promptFile and carry it out exactly."
    $argStr = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`" -Name $jobName -Prompt `"$prompt`" -TimeoutMin $timeoutMin -LockWaitMin $lockWaitMin"
    if ($model) { $argStr += " -Model $model" }
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argStr
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-NextSlot $intervalMin $offsetMin) `
        -RepetitionInterval (New-TimeSpan -Minutes $intervalMin) -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes $limitMin)
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "registered $taskName"
}

Register-Job "KingsWork-Blog-Drink" "blog-drink" "blog-drink.md" ""       60 15 50 20 75
Register-Job "KingsWork-X-Jazz"     "x-jazz"     "x-jazz.md"     "sonnet" 30 0  20 20 45
