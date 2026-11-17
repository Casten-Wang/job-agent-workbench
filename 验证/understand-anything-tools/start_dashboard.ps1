$ErrorActionPreference = 'Stop'
$toolRoot = $PSScriptRoot
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $toolRoot '..\..\outputs\understand-anything\itsdangerous-672971d66a2e\project'))
$graphPath = Join-Path $projectRoot '.ua\knowledge-graph.json'
if (-not (Test-Path -LiteralPath $graphPath -PathType Leaf)) {
    throw 'No knowledge graph found; finish schema/reference validation before starting the dashboard.'
}
$entry = Join-Path $toolRoot 'start_dashboard.mjs'
$nodeExecutable = (Get-Command node -CommandType Application | Select-Object -First 1).Source
$processInfo = Start-Process -FilePath $nodeExecutable -ArgumentList @(('"' + $entry + '"'), ('"' + $projectRoot + '"')) -WorkingDirectory $toolRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $toolRoot 'dashboard.stdout.log') -RedirectStandardError (Join-Path $toolRoot 'dashboard.stderr.log') -PassThru
$record = @{ pid = $processInfo.Id; project_root = $projectRoot; entry = $entry; host = '127.0.0.1'; port = 18745; started_at = (Get-Date).ToUniversalTime().ToString('o') }
$record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $toolRoot 'dashboard-process.json') -Encoding utf8
$record | ConvertTo-Json
