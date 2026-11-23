# Starts scripts/x_report_server.py, which serves the generated X report on TWO
# explicit addresses only: the physical LAN adapter (Wi-Fi/Ethernet) and the
# Tailscale adapter. Tailscale is a private tailnet (registered devices only),
# so this is NOT public exposure. Never binds 0.0.0.0 and no router port forward.
#
# Windows Firewall is currently disabled on this machine, so the explicit bind
# list is the only thing keeping the report off other interfaces. APIPA
# (169.254.*), Bluetooth and loopback adapters are skipped.
#
# Kept ASCII-only: Windows PowerShell 5.1 reads BOM-less UTF-8 .ps1 as ANSI and
# breaks on non-ASCII literals (see job-common.ps1).

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "x-report-server.log"

$all = Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notlike '169.254.*' -and
    $_.IPAddress -ne '127.0.0.1' -and
    $_.InterfaceAlias -notmatch 'Bluetooth'
}

# Physical LAN first (prefer Wi-Fi / Ethernet), then the private tailnet IP.
$lanIp = $all |
    Where-Object { $_.InterfaceAlias -notmatch 'Tailscale' } |
    Sort-Object { if ($_.InterfaceAlias -match 'Wi-Fi|Ethernet') { 0 } else { 1 } } |
    Select-Object -First 1 -ExpandProperty IPAddress
$tailscaleIp = $all |
    Where-Object { $_.InterfaceAlias -match 'Tailscale' } |
    Select-Object -First 1 -ExpandProperty IPAddress

$binds = @()
if ($lanIp) { $binds += $lanIp } else { $binds += "127.0.0.1" }
if ($tailscaleIp) { $binds += $tailscaleIp } else { Write-Host "WARNING: Tailscale adapter not found; LAN only" }
Write-Host "binding X report server to: $($binds -join ', ') (log: $log)"

$pyArgs = @("scripts/x_report_server.py", "--bind") + $binds + @("--port", "8765", "--log-file", $log)
$env:PYTHONIOENCODING = "utf-8"
& python @pyArgs
