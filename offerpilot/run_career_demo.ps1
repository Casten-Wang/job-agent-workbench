param([string]$EngineRoot = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = 'Stop'
$enginePath = (Resolve-Path -LiteralPath $EngineRoot).Path
$pythonPath = Join-Path $enginePath '.venv-interview\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'The interview Python environment was not found under EngineRoot.'
}
& $pythonPath -I -B (Join-Path $PSScriptRoot 'tools\run_career_demo.py') --engine-root $enginePath
exit $LASTEXITCODE
