param([switch]$StepPlan)
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$Host.UI.RawUI.WindowTitle = if ($StepPlan) { 'Pi 面试 Agent - 阶跃 Step Plan 配置' } else { 'Pi 面试 Agent - GPT Responses 配置' }
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot

Write-Host $(if ($StepPlan) { '配置阶跃 Step Plan：Chat Completions 协议' } else { '配置 GPT 中转：Responses 协议' }) -ForegroundColor Cyan
Write-Host '接口地址和模型 ID 将保存在本项目；密钥隐藏输入，仅供当前进程使用。'
Write-Host '随后只用公开项目与合成回答验证，不会评价你的个人能力。'

try {
    $configPath = Join-Path $projectRoot '.pi/interview-provider.json'
    if ($StepPlan) {
        $preset = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'stepfun-plan.json') -Raw | ConvertFrom-Json
        $endpoint = $preset.base_url
        $modelId = $preset.model
        $providerConfig = [ordered]@{ provider = $preset.provider; model = $modelId; api = $preset.api; base_url = $endpoint }
        Write-Host "接口：$endpoint"
        Write-Host "模型：$modelId（低推理强度）"
    } else {
    $previous = if (Test-Path -LiteralPath $configPath) { Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json } else { $null }
    $endpoint = Read-Host "接口根地址（例如 https://你的服务/v1；回车沿用 $($previous.base_url)）"
    if ([string]::IsNullOrWhiteSpace($endpoint)) { $endpoint = $previous.base_url }
    $uri = $null
    if (-not [Uri]::TryCreate($endpoint, [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
        throw '接口根地址必须是 HTTPS，并且不包含用户名、密码或查询参数。'
    }
    $modelId = Read-Host "准确模型 ID（回车沿用 $($previous.model)）"
    if ([string]::IsNullOrWhiteSpace($modelId)) { $modelId = $previous.model }
    if ([string]::IsNullOrWhiteSpace($modelId) -or $modelId.Length -gt 200) { throw '需要填写提供商支持的准确模型 ID。' }
    $providerConfig = [ordered]@{ provider = 'gpt-proxy'; model = $modelId; api = 'openai-responses'; base_url = $endpoint.TrimEnd('/') }
    }
    $providerConfig | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding utf8
    $secretInput = Read-Host $(if ($StepPlan) { '新生成的 Step API key（隐藏输入）' } else { '中转 API key（隐藏输入；不要粘贴到聊天）' }) -AsSecureString
    $env:PI_INTERVIEW_API_KEY = [Net.NetworkCredential]::new('', $secretInput).Password
    if ([string]::IsNullOrWhiteSpace($env:PI_INTERVIEW_API_KEY)) { throw '尚未输入访问凭据。' }
    $env:PI_INTERVIEW_PROVIDER = $providerConfig.provider
    $env:PI_INTERVIEW_MODEL = $modelId
    $env:PI_INTERVIEW_BASE_URL = $endpoint.TrimEnd('/')
    $env:PI_INTERVIEW_API = $providerConfig.api
    $env:NO_PROXY = if ($env:NO_PROXY) { "$($env:NO_PROXY),127.0.0.1,localhost" } else { '127.0.0.1,localhost' }
    if (-not $env:INTERVIEW_PYTHON) {
        $env:INTERVIEW_PYTHON = if (Test-Path -LiteralPath 'D:\miniconda3\python.exe') { 'D:\miniconda3\python.exe' } else { 'python' }
    }
    & node --use-env-proxy (Join-Path $PSScriptRoot 'live-check.mjs')
    if ($LASTEXITCODE -eq 0) {
        Write-Host '验证通过。输入 Y 可继续启动公开项目的交互核验；回车则结束。' -ForegroundColor Green
        $startInterview = Read-Host
        if ($startInterview -eq 'Y') { & node --use-env-proxy (Join-Path $PSScriptRoot 'cli.mjs') }
    } else { Write-Host '验证未通过，结果已保存，可核对配置后重试。' -ForegroundColor Yellow }
} catch {
    Write-Host '配置未完成。请核对接口根地址、模型 ID 和本机输入的访问凭据后重试。' -ForegroundColor Yellow
} finally {
    Remove-Item Env:PI_INTERVIEW_API_KEY -ErrorAction SilentlyContinue
    if ($secretInput) { $secretInput.Dispose() }
}
Read-Host '按回车关闭窗口'
