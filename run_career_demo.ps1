# Windows 启动脚本：与 README「启动 › 完整启动」等价（工作台 8766 + 引擎 18747/18748）。
# 需要先在仓库根目录创建 .venv 并安装依赖（见 README「安装」）。注意不要给 python 加 -I。
param([string]$EngineRoot = $PSScriptRoot)

$ErrorActionPreference = 'Stop'
$enginePath = (Resolve-Path -LiteralPath $EngineRoot).Path
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "未找到 $pythonPath ；请先执行：python -m venv .venv，再按 README 安装依赖。"
}
$env:NO_PROXY = '127.0.0.1,localhost'
& $pythonPath -B (Join-Path $PSScriptRoot 'tools\run_career_demo.py') --engine-root $enginePath
exit $LASTEXITCODE
