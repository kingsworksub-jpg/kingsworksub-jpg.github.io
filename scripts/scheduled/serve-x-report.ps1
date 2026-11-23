# Starts scripts/x_report_server.py, which serves the generated X report on ONE
# LAN IPv4 address only. Same shape as the other run-*.ps1 scripts.
#
# IMPORTANT: never bind 0.0.0.0. Windows Firewall is currently disabled on this
# machine, so the chosen bind address is the only thing keeping the report off
# Tailscale / public interfaces. We deliberately skip Tailscale, Bluetooth and
# APIPA (169.254.*) adapters and prefer the physical Wi-Fi / Ethernet adapter.
#
# Kept ASCII-only: Windows PowerShell 5.1 reads BOM-less UTF-8 .ps1 as ANSI and
# breaks on non-ASCII literals (see job-common.ps1).

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "x-report-server.log"

$ip = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.InterfaceAlias -notmatch 'Tailscale|Bluetooth|Loopback' -and
        $_.IPAddress -notlike '169.254.*' -and
        $_.IPAddress -ne '127.0.0.1'
    } |
    Sort-Object { if ($_.InterfaceAlias -match 'Wi-Fi|Ethernet') { 0 } else { 1 } } |
    Select-Object -First 1 -ExpandProperty IPAddress

# If no LAN adapter is up, fall back to loopback (local machine only).
if (-not $ip) { $ip = "127.0.0.1" }
Write-Host "binding X report server to $ip (LAN only), log: $log"

$env:PYTHONIOENCODING = "utf-8"
& python scripts/x_report_server.py --bind $ip --port 8765 --log-file $log
