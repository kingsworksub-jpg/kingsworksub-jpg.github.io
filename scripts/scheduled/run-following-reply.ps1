# Launches scripts/x-following-reply.py in --loop --publish mode and lets it run indefinitely,
# appending its output to its own log file. Same shape as run-x-auto-like.ps1.
#
# The Python script chooses a new random wait after every cycle (shorter in the daytime,
# longer late at night), so the posting times never fall on a fixed 45-minute grid. One
# process per day is enough; the task scheduler starts it at logon and once a day as a
# safety net (see scripts/schedule-following-reply.ps1).
#
# The script itself acquires "Local\kingsworksub-blog-x-jobs" per cycle (10s wait) and
# skips the cycle when blog-x-reply-task / blog-x-auto-like-task / blog-automation-task
# are using the shared data/x_user_data Chromium profile, so no wrapper mutex is needed.
#
# Uses --log-file (python opens it directly as UTF-8) rather than PowerShell's *>> redirect --
# *>> decodes the native process's output through the console codepage first, which mangles
# the Japanese text (same reason as run-x-auto-like.ps1, 2026-11-06).

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "x-following-reply.log"
& python scripts/x-following-reply.py --loop --publish --log-file $log
