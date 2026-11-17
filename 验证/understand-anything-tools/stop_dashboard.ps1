$ErrorActionPreference = 'Stop'
$recordPath = Join-Path $PSScriptRoot 'dashboard-process.json'
if (-not (Test-Path -LiteralPath $recordPath -PathType Leaf)) { return }
$record = Get-Content -LiteralPath $recordPath -Raw -Encoding utf8 | ConvertFrom-Json
$dashboardPid = [int]$record.pid
$expectedEntry = Join-Path $PSScriptRoot 'start_dashboard.mjs'
$running = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $dashboardPid)
if ($null -eq $running) { return }
if (-not $running.CommandLine.Contains($expectedEntry, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'PID no longer belongs to this dashboard; no process was stopped.'
}
Stop-Process -Id $dashboardPid
Write-Output ('Stopped dashboard process ' + $dashboardPid)
