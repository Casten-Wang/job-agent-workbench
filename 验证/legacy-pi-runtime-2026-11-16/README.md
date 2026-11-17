# Pi 面试编排原型

当前业务编排已迁移至 [Python + FastAPI + LangGraph](../interview_agent/README.md)。本目录的 `agent.mjs` 和 `worker.mjs` 作为模型适配层继续使用；原 Node CLI／状态机保留用于兼容验证，新业务入口为 `python -m interview_agent`。

采用官方 `@earendil-works/pi-coding-agent@1.5.2`，在已有 Python Interview Hub 上增加提问、对话意图识别、逐题观察和提示四个模型调用阶段。普通程序负责状态转换、引用校验、持久化和最终结果提交。

Context7 已按 MCP 接入项目的 `.pi/mcp.json`。开发时查询公开库文档；面试项目事实来自 GitHub 固定提交、源码引用和 UA 材料。面试调用只开放当前阶段的 `submit_*` 决策工具，不加载开发用 MCP、文件写入、Shell、技能或其他项目扩展。

## 已实现

- Agent 依据固定资料生成最多三道问题，绑定 claim、证据、考察意图和选题理由；服务保存本轮不可变计划，原材料题目不被覆盖。
- 自然语言识别作答、提示、职责／版本修正、暂停、继续、跳过、结束及待澄清；明确命令可直接控制流程。
- 提问与评价使用独立的模型上下文；意图识别只接收当前题目、状态和最近话语，不接收评价依据。
- 提示、查阅源码和 AI 辅助保留标记。暂停时的技术内容不进入评价；修正职责／版本会挂起相关判断。
- 评估失败前先暂存原回答，支持重试和重启恢复；结束时调用既有结果与复盘接口。
- 模型反馈、职责修正和补强建议都待用户复核，不生成个人能力总分，不自动改简历。

## 安装与 Context7

在工作区根目录执行。已在当前机器完成本地安装和项目级信任；其他机器首次运行前执行前两项。

```powershell
npm --prefix pi_interview ci
npm --prefix pi_interview run setup:project
npm --prefix pi_interview run context7:list
npm --prefix pi_interview run context7:check
```

`setup:project` 只在本项目 `.pi/runtime/dev` 的独立 Pi 配置中信任当前目录。开发 CLI 入口是 `npm --prefix pi_interview run pi -- ...`，没有全局安装 Pi 或修改全局配置。

当前已实测匿名连接官方 `https://mcp.context7.com/mcp`，发现 `resolve-library-id`、`query-docs` 并取得 `/earendil-works/pi` SDK 文档。文档命中不保证和安装版本完全相同，接口实现同时核对了已锁定包的声明与示例。

如本机联网需要环境代理，可设置 `NODE_USE_ENV_PROXY=1`，并在 `NO_PROXY` 中保留 `127.0.0.1,localhost`。Context7 检查也可用 `node --use-env-proxy pi_interview/context7-check.mjs`。当前 Node 为 24.15.0。

Context7 key 为可选项；独立检查脚本可读 `CONTEXT7_API_KEY`。开发 Pi MCP 配置当前使用匿名连接；需要带 key 时在该 MCP 项添加 `headers: { "Authorization": "Bearer ${CONTEXT7_API_KEY}" }`，真实值仅放本机环境。不要把候选人回答、私有源码或凭据作为文档查询词。

## 阶跃 Step Plan（当前配置）

当前切换为阶跃星辰的 Step Plan，预设为 `step-5-preview`、Chat Completions 协议，根地址 `https://api.stepfun.com/step_plan/v1`。这是官方文档列出的套餐入口，平台的 `platform.stepfun.com/step-plan` 页面用于管理套餐。

运行 `pi_interview/配置阶跃StepPlan.ps1`，只需隐藏输入新生成的 Step API key。地址、模型和协议从 `stepfun-plan.json` 预设填入；仅将这些非凭据参数保存到本机配置，key 不写入项目文件。原 GPT 配置入口仍可用于单独配置 Responses 服务。

Pi 使用低推理强度和最多 8192 输出 tokens；此上限包含模型推理和决策输出所需的预算，不代表每次消耗量。兼容设置使用 `system` 角色和 `max_tokens`，支持阶跃流中的 `reasoning` 字段及后续工具结果回传。SDK 验证失败时只保留分类和 HTTP 状态，不保存供应商原始错误正文。

终端已有凭据环境时，也可以设置 `STEP_API_KEY` 或 `STEPFUN_API_KEY`，并运行 `npm --prefix pi_interview start`；`PI_INTERVIEW_API_KEY` 优先。套餐额度是否可用由实际请求确认，不自动切换到按量计费的标准 API。

2026-11-15 已完成 Step Plan 真实接口验证：出题、意图识别、逐题观察、最终结果与复盘均通过，落库后重读绑定一致。报告见 `outputs/pi-interview/live-verification.json`；样例包含两道生成题、一条合成回答和一项补强任务，不构成用户能力评估。原型的真实评价准确率尚未校准。

Step 5 Preview 的上下文规格按官方文档登记为 1M，单次输出预算仍限制为 8192 tokens。更换模型会创建新轮次；已有轮次保留原模型来源，不能用新模型冒充原轮次恢复。

当前 `step-5-preview` 已通过真实接口的出题、意图识别、逐题观察与复盘保存验证。七层职责、现有代码映射及未完成范围见 [Agent 七层架构 v0.9](../定制简历_Agent七层架构_v0.9.md)。

参考：[Step Plan 接入](https://platform.stepfun.com/docs/zh/step-plan/integrations/reasoning-api)、[Step 5 Preview](https://platform.stepfun.com/docs/zh/guides/models/step-5-preview)。

## 另选 GPT 中转：Responses

这个入口用于用户另行提供的 GPT 中转和 Responses 协议。接口根地址、准确模型 ID、凭据需要用户本机提供，没有猜测地址、型号或借用其他应用的登录信息。

运行 `pi_interview/配置GPT中转.ps1`。它会依次提示根地址、模型 ID 与隐藏输入的 key，把前两项和协议保存到 `.pi/interview-provider.json`，key 只进入当前进程环境。此本机配置已忽略提交；示例见 `.pi/interview-provider.example.json`。

该窗口自动用公开 `itsdangerous` 材料进行一次真实接口验证：生成问题 → 合成回答的意图识别与逐题观察 → 入库 → 复盘。余下问题标记为跳过。结果写入 `outputs/pi-interview/live-verification.json`。即使通过，也不代表已经验证真实用户能力或评价准确率。

也可在自己的终端配置，不把 key 写进命令历史：

```powershell
$env:INTERVIEW_PYTHON = 'D:\miniconda3\python.exe' # 或你的 Python 3.11+ 路径
$env:PI_INTERVIEW_PROVIDER = 'gpt-proxy'
$env:PI_INTERVIEW_MODEL = '提供商给出的准确模型ID'
$env:PI_INTERVIEW_BASE_URL = 'https://你的服务/v1'
$env:PI_INTERVIEW_API = 'openai-responses'
$secretInput = Read-Host '中转 API key' -AsSecureString
$env:PI_INTERVIEW_API_KEY = [Net.NetworkCredential]::new('', $secretInput).Password
npm --prefix pi_interview start
```

当本机配置文件已有地址、模型和协议时，只需设置 Python 和临时 key。程序默认自启临时 loopback Hub，启动参数不含 key，退出后关闭 Hub。原数据库与材料复用，默认选择最新材料；可通过 `--material` 指定。也支持用 `INTERVIEW_HUB_URL`／`INTERVIEW_HUB_TOKEN` 连接已运行的本机服务。

环境变量可覆盖本机配置。`PI_INTERVIEW_API` 支持 `openai-responses` 和 `openai-completions`，当前选择前者。中转支持的模型及工具调用能力需要用实际接口验证；别名不能直接当作官方型号性能或计费的保证。未知模型的费用元数据为占位值，不是实际费用。

## 交互与恢复

```powershell
npm --prefix pi_interview start -- --material mat_6c05373d57d03a107d49806c --role 初级后端开发
npm --prefix pi_interview start -- --session 终端显示的会话ID
```

自然语言和下列命令都可使用：`/hint`、`/open-book`、`/ai-assisted`、`/skip`、`/pause`、`/resume`、`/finish`、`/retry`、`/contribution 修正说明`、`/version 修正说明`。提示和辅助记录不会被后续普通回答清掉。

`/finish` 才会提交最终结果和生成复盘。中途退出保留已写入的本地进度；待评估回答通过 `/retry` 继续。完成的会话恢复已保存复盘。职责或版本修正后，本轮保持待复核；确认新材料并创建新轮次后再核验。

逐轮状态在 `outputs/pi-interview/sessions`；Hub 的计划、最终结果和复盘在 SQLite。当前是单机单用户原型，请勿并发操作同一会话的本地状态文件。

## 验证与边界

```powershell
$env:INTERVIEW_PYTHON = 'D:\miniconda3\python.exe'
npm --prefix pi_interview test
npm --prefix pi_interview run smoke
python -X utf8 -m unittest discover -s tests -q
```

自动化测试使用本机确定性 HTTP 模型服务，实际经过 Pi SDK 的工具调用和 HTTP 协议；它验证状态和接口，不验证模型理解准确率。`smoke` 在独立 SQLite 和合成回答上验证多轮历史引用、辅助标记、暂停、职责／版本修正、中断恢复、跳过与复盘草稿。

当前每轮在开始时一次生成问题并冻结，尚无轮内动态追加追问。历史目前提供会话创建时固定的复盘引用，尚未自动通读历轮复盘正文。公司／岗位是目标标签，真实 JD 和公司研究没有接入；不能由公司名推断偏好。正式 mock_interview 还要求已保存的简历版本，目前公开验证使用 resume_readiness。

样例仓库是 `pallets/itsdangerous` 的固定提交 `672971d66a2ef9f85151e53283113f33d642dabd`，不是用户经历。Agent 材料协议不限定 Python，当前联调样例是 Python，其他语言尚未作仓库联调。私库授权、多用户权限、语音、简历编辑采纳和真实能力校准不在本轮完成范围。

参考：[Context7 官方](https://github.com/upstash/context7)、[Pi SDK](https://docs.pi.dev/latest/sdk)、[Pi MCP](https://docs.pi.dev/latest/mcp)、[OpenAI 工具调用](https://developers.openai.com/api/docs/guides/function-calling)。
