# Python 面试运行时

单条面经匿名收藏、更新订阅、应用内消息和自检见 [面经订阅说明](../web/NOTE-SUBSCRIPTIONS.md)。该能力接入完整个人 Agent；需要用户提供明确链接，不提供关键词搜索或批量抓取。

本机离线项目知识库可与个人资料服务共同运行，也可通过 `python -m interview_agent.knowledge_api` 独立启动，无需模型凭据。启动、Web 自动预热、固定版本检索及对外接口见 [知识库接口文档](../web/KNOWLEDGE-API.md)。该模块只提供项目资料，不新增面试交互。

当前业务入口统一为 Python + FastAPI + LangGraph。HTTPX 直接连接阶跃 Step Plan，默认 `step-5-preview`，产品启动和运行不需要 Node、Pi SDK 或子进程桥接。

请求链：客户端 HTTP → FastAPI → LangGraph 节点 → Python ModelAdapter → Step 5 → Pydantic 输出校验 → 业务引用校验与状态更新。

四类决策的提示词与输出 Schema 位于 `decisions.py`；`model_adapter.py` 负责模型请求、工具参数解析、有限重试和安全化错误分类。每次只接受本阶段一个结构化决策，普通文本、无关工具、重复 JSON 字段和不合 Schema 的输出不会触发业务动作。LangGraph 调度 bootstrap、wait、classify、act、hint、evaluate、finalize 节点。wait 使用 `interrupt()` 等待输入，后续用同一 owner/session 对应的 thread ID 恢复。

## 环境与启动

需要 Python 3.11+。使用仓库根目录的 `.venv`（与工作台共用，安装见根目录 README）；下面的命令以 Windows 为例，macOS / Linux 把 `.venv/Scripts/python.exe` 换成 `.venv/bin/python`。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r interview_agent/requirements.lock.txt
```

工作区根目录启动：

```powershell
$env:INTERVIEW_AGENT_TOKEN = .venv/Scripts/python.exe -c "import secrets;print(secrets.token_urlsafe(32))"
$secretInput = Read-Host 'Step API key' -AsSecureString
$env:STEP_API_KEY = [Net.NetworkCredential]::new('', $secretInput).Password
$env:NO_PROXY = '127.0.0.1,localhost'
.venv/Scripts/python.exe -m interview_agent
```

默认监听 `http://127.0.0.1:18747`，单 worker。使用原业务数据库 `outputs/interview-hub/interview.db`，运行检查点单独在 `outputs/interview-agent/checkpoints.db`；可用 `--db`、`--checkpoints`、`--owner`、`--port` 指定。模型非凭据配置位于 `interview_agent/provider.json`，环境变量 `INTERVIEW_PROVIDER`、`INTERVIEW_MODEL`、`INTERVIEW_BASE_URL` 可覆盖。访问凭据按 `INTERVIEW_API_KEY`、`STEP_API_KEY`、`STEPFUN_API_KEY` 的顺序读取；不再读取 `PI_INTERVIEW_*` 或 `.pi` 配置。

模型沿用 Chat Completions 协议、low 推理强度与 8192 输出 tokens 上限。请求和工具参数解析在 Python 内完成；无效结构最多补一次格式修正请求，网络故障或 429/部分 5xx 最多重试一次，总时限 120 秒。401/403 等访问错误直接返回分类，不保存原始错误正文。模型判断通过后直接交给 LangGraph，不额外请求一句完成确认。

`INTERVIEW_AGENT_TOKEN` 是本机服务调用令牌，所有业务接口需要 `Authorization: Bearer <该令牌>`，与模型 key 不同。该接口面向可信本机调用方；当前没有多用户登录或生产角色权限。原材料服务默认 18746 可继续单独使用，本服务直接复用 Python 存储模块，无需同时启动它。

## HTTP 接口

- `GET /health`：运行状态、编排器与模型来源。
- `GET /v1/materials`：列出当前 owner 的资料摘要。
- `POST /v1/interviews`：创建／恢复本运行时的会话，正文含 material_id、可选 session_id、mode、target。
- `GET /v1/interviews/{id}`：读取当前问题、状态和已完成数量；不返回评价依据或原始事件历史。
- `POST /v1/interviews/{id}/turns`：提交 `{event_id, text, command?}`。event_id 由调用方生成；相同内容重试不会再次推进，改写同一 ID 返回 409。
- `GET /v1/sessions/{id}/question-plan`、`results`、`recap`：可信后端读取已保存记录。
- `GET /v1/history?claim_id=...&limit=20&offset=0`：查询当前 owner 的历轮记录。

示例：

```json
{"session_id":"python_demo_1","material_id":"mat_6c05373d57d03a107d49806c","mode":"resume_readiness","target":{"role":"初级后端"}}
```

```json
{"event_id":"answer_1","text":"我的回答"}
```

command 支持 `request_hint`、`open_book`、`ai_assisted`、`skip`、`pause`、`resume`、`finish`、`retry`、`correct_contribution`、`correct_version`；省略时由模型识别自然语言意图。HTTP 层与模型输出使用 Pydantic 校验；源码绑定和结果另行做业务校验。

评价失败会返回当前状态，`pending_evaluation=true` 且保留原回答，可提交新的 event_id 和 command=retry；若意图识别或初始化节点失败，接口返回 502，同样可 retry。重启后读取同一会话可恢复检查点。明确 finish 后才写最终结果并生成复盘；缺答、跳过、辅助作答和职责／版本修正保留既有约束。

LangGraph 检查点是进行中状态的唯一写入来源，业务 SQLite 继续保存不可变资料、会话元数据、题目计划、最终结果和复盘。结果落库是幂等操作，避免图恢复造成重复结果。外部 LangSmith tracing 在服务入口关闭；报告不保存模型 key 或供应商错误正文。

## 旧 Pi JSON 会话迁移

新会话和进行中的 Python 检查点均使用直接模型调用。原 Node/Pi 原型已归档至 `验证/legacy-pi-runtime-2026-11-16`，不再是产品运行入口。

显式导入某个旧 JSON，指定它原来的业务数据库。导入会核对源码、材料、问题计划、模型和待评价回答；保留原文件，不重新出题、不重新评价。

```powershell
.venv/Scripts/python.exe -m interview_agent --db outputs/interview-hub/interview.db --import-legacy outputs/pi-interview/sessions/旧会话ID.json
```

导入要求当前模型与原会话一致；模型不同请先切回原模型或创建新轮次。已有 Python 检查点不能被导入覆盖。完成会话恢复原复盘；进行中会话在等待点继续。JSON 导入只提供本机命令，没有开放任意文件路径的 HTTP 接口。原问题 ID（如 pi_q1）是历史数据关联键，继续保留，不代表需要 Pi。原模型来源和已经保存的总结文本保持原样。

## 验证

```powershell
.venv/Scripts/python.exe -X utf8 -m unittest discover -s interview_agent/tests -v
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q
.venv/Scripts/python.exe -X utf8 -m interview_agent.verify --key-stdin
```

最后一个命令使用隐藏输入的模型 key，启动真实临时 localhost FastAPI 服务，通过 HTTP 请求运行 LangGraph→Python HTTPX→Step 5，再保存公开样例的合成回答与复盘；结束后关闭服务，报告位于 `outputs/interview-agent/live-verification.json`。报告中的 runtime 必须为 python-httpx，旧 Pi 联调结果不作为本轮直接调用的验证依据。

本轮直接调用与工作流测试覆盖四类输出、非法工具、格式修正、限流重试、超时、鉴权错误、真实本机 HTTP、关闭并重开检查点、重复事件、模型失败、引用不符、辅助标记与旧 JSON 导入。最新测试与真实联调状态见 `outputs/interview-agent/pure-python-summary.json`；确定性协议测试与真实模型结果分别记录。

## 当前边界

这是原有状态机的迁移：仍在每轮开始生成题目，未增加动态追问、历史复盘正文检索或任务完成后的复测。当前单 worker 并串行处理会话写入，AsyncSqliteSaver 用于本机原型；生产并发需要持久化后端及跨进程协调。没有引入新的队列、向量数据库或另一个模型框架。

参考：[LangGraph 中断恢复](https://docs.langchain.com/oss/python/langgraph/interrupts)、[检查点](https://docs.langchain.com/oss/python/langgraph/checkpointers)、[FastAPI 生命周期](https://fastapi.tiangolo.com/advanced/events/)、[HTTPX 异步调用](https://www.python-httpx.org/async/)、[Step 5 Preview](https://platform.stepfun.com/docs/zh/guides/models/step-5-preview)。
