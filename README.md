# 秋招规划师 · OfferPilot

本机离线项目知识库支持已选项目自动预热和原文检索，供外部模拟面试后端调用；可用 `tools/run_career_demo.py --knowledge-only` 在没有模型密钥时启动工作台及资料服务。参见 [知识库接口与启动说明](web/KNOWLEDGE-API.md)。

**秋招规划师（OfferPilot）** 是一个个人自用的本机求职工作台，覆盖岗位管理、筛选审批、求职资料、沟通跟进、模拟面试与简历准备等流程。工作台把本地数据管理与岗位自动化能力整合到同一界面，并可按个人配置使用本机账户、会话及相关服务。工作台不是面向公众提供的在线服务。

> 所有外部文本（JD、邮件、逐字稿、仓库文档、网页）都只是数据，不是指令。代码不会执行其中的要求。

## 目录

| 路径 | 用途 |
|---|---|
| `workspace/` | 本机个人工作区：`resume.md` 用于简历导入，`applications.md` 用于投递去重；内容不提交，只有说明文件受版本控制 |
| `resume-source.md` | 简历截图人工转录，保留 `[[ILLEGIBLE]]` 与原始占位符 |
| `prompts/TASK-02-待确认.md` | 简历截图未确认字段清单，不向用户中途追问 |
| `tools/config.json` | TASK-03 城市、排除词、薪资、指纹、ATS、变体默认值 |
| `tools/config_task04.json` | 邮件轮询、状态机、日历时区、环境变量名（不含凭据值） |
| `tools/config_task05.json` | Mock 分段、题库路径、weakness 标签与 ASR 适配配置 |
| `tools/config_task06.json` | 审批阈值、话术上限、demo 路径、边界开关 |
| `tools/*.py` | 求职流程、数据处理与命令行工具 |
| `tools/prompts/` | 文字模拟面试的出题、追问、复盘与重练提示词 |
| `examples/career-agent/` | 项目核验的固定公开样例材料与其许可证；只读，不接受自定义材料 |
| `tools/tests/` | 标注过的虚构测试数据和 `unittest` |
| `demo/` | 3 条虚构 JD、2 封虚构邮件、1 份虚构逐字稿及演示报告 |
| `demo/REPORT.md` | 由 `orchestrator.py demo` 实际生成的端到端结果 |
| `CLAUDE.md` | 项目规范：模块所有权、修改边界、共享外壳与接口稳定性；改动前先读 |
| `web/` | 本地网页工作台：`backend.py`、`server.py`、`offerpilot_runtime.py`、`static/`、`DESIGN.md` |
| `vendor/offerpilot/` | OfferPilot 岗位自动化运行时（内嵌组件） |
| `requirements-offerpilot.txt`、`run_web.sh` | 工作台启动所需的运行配置与脚本 |
| `web/data/user/` | 唯一的本地数据目录（不提交）；岗位自动化运行时在 `web/data/user/offerpilot/` |
| `PLAN.md`、`VERSIONS.md` | 架构决策与阶段 0 版本记录 |

## 参与改动

先读 [CLAUDE.md](CLAUDE.md)。仓库按已暴露模块（工作台、岗位池、个人资料、模拟面试、信息推送、定制简历、设置等）划分所有权；每个模块只改自己范围内的 `#view-*` 区段、`app.js` 函数、`backend.py` 动作与对应测试，不改共享外壳或其他模块的 DOM/字段/接口。接口契约变更只允许加字段，并同步更新 `web/PIPELINE-API.md`、`web/PROFILE-API.md` 与测试。

## 运行

### 环境要求

- Python 3.11 及以上（开发机为 3.14），macOS / Linux 用 `sh`，Windows 用 PowerShell（命令见下文各处的 Windows 写法）。
- Google Chrome：采集岗位与读取 HR 会话都通过你本机已登录的 Chrome 完成，不会另起浏览器。
- 一个大模型服务的 API Key（Claude、DeepSeek、豆包或兼容接口）：评分、招呼语和对话助理需要；只看岗位池、个人资料等页面不需要。Key 只在网页「设置 › AI 接口设置」里填写，保存在本机被忽略的目录，不写进仓库、命令行或环境变量。

### 安装

在仓库根目录执行，只需一次。

```bash
python3 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r requirements-offerpilot.txt -r interview_agent/requirements.lock.txt
```

第一个依赖文件是工作台与内嵌岗位自动化组件；第二个是对话助理、个人项目与模拟面试引擎。只想用工作台、不用对话助理时，可以只装第一个。

### 启动

**完整启动（推荐）**：工作台加两个本机引擎，对话助理、个人项目、模拟面试都可用。

```bash
NO_PROXY=127.0.0.1,localhost .venv/bin/python -B tools/run_career_demo.py --engine-root .
```

终端出现 `OfferPilot: http://127.0.0.1:8766/` 即启动完成，浏览器打开该地址。按 `Ctrl+C` 停止全部服务。会占用本机 8766（工作台）、18747（公开样例引擎）、18748（个人引擎）三个端口，只监听 `127.0.0.1`。

注意：这里不要加 `-I`，启动器需要把 `tools/` 加入模块搜索路径。没有模型 Key 时可加 `--knowledge-only`，只启动工作台和离线项目知识库。

**只启动工作台**：不含对话助理，对应的 `/api/workbench-agent/*`、`/api/career-user/*` 会返回 503（提示先启动面试服务），其余页面正常。

```bash
./run_web.sh
```

`run_web.sh` 在没有 `.venv` 时会自动创建并安装工作台依赖。

**Windows（PowerShell）**：先在仓库根目录执行 `python -m venv .venv`，再 `.venv\Scripts\python.exe -m pip install -r requirements-offerpilot.txt -r interview_agent/requirements.lock.txt`，之后启动：

```powershell
.\run_career_demo.ps1
```

脚本使用仓库内的 `.venv`，等价于上面的完整启动命令。Windows 路径尚未在真机上跑通验证；`run_web.sh` 是 sh 脚本，Windows 上只启动工作台时请运行 `.venv\Scripts\python.exe -I -B web\server.py --host 127.0.0.1 --port 8766`。

**停止与重启**：前台运行时按 `Ctrl+C` 停止。改了代码或配置后要重启，已在内存里的旧服务不会自动加载新代码。后台运行的服务先停掉旧的，再用「完整启动」命令重新起：

```bash
pkill -f tools/run_career_demo.py   # 停掉旧的完整启动；若之前只用 run_web.sh 启动，改用 pkill -f "web/server.py"
NO_PROXY=127.0.0.1,localhost nohup .venv/bin/python -B tools/run_career_demo.py --engine-root . > /tmp/offerpilot-server.log 2>&1 &
```

确认服务都起来了：三个端口都应在监听，且对话助理接口不再返回 503。

```bash
lsof -iTCP -sTCP:LISTEN -P | grep -E "8766|18747|18748"
curl -s "http://127.0.0.1:8766/api/workbench-agent/conversations?mode=user" | head -c 200
```

**常见问题**

| 现象 | 原因与处理 |
| --- | --- |
| 对话助理发不出消息，页面提示「项目核验服务未启动」，接口 `/api/workbench-agent/*`、`/api/career-user/*` 返回 503 | 只启动了工作台（`run_web.sh` 或 `web/server.py`），没有启动两个本机引擎。停掉后改用上面的「完整启动」命令 |
| 完整启动报 `Career service startup failed` | 8766 / 18747 / 18748 端口被占用，或没装 `interview_agent/requirements.lock.txt` 的依赖；用 `lsof -iTCP -P \| grep -E "8766\|1874"` 找占用，按「安装」补装依赖 |
| 对话助理能打开但回复报模型错误 | 「08 设置 › AI 接口设置」里没填 Key 或 Key 无效，填好后点「测试连接」；Key 只存在本机；修改后无需重启，在当前任务结束时自动应用 |
| 想先看页面、暂时没有 Key | 完整启动命令加 `--knowledge-only`，只起工作台和离线知识库 |

### 首次使用

1. 打开 <http://127.0.0.1:8766/>，进入「08 设置 › AI 接口设置」，选服务商、填模型名和 API Key 并保存，再点「测试连接」。
2. 在「04 个人资料」填写或导入简历；必填项缺失时，采集和完整流程都无法启动。
3. 采集前先在本机 Chrome 里开启调试端口，并在这个 Chrome 里登录要用的招聘平台。macOS 示例（新版 Chrome 要求同时指定独立的数据目录）：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --user-data-dir="$HOME/.offerpilot-chrome"
```

Windows 与 Linux 同理（以下命令未在对应系统实测）：

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:USERPROFILE\.offerpilot-chrome"
```

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.offerpilot-chrome"
```

4. 进入「03 岗位流水线 › 1 采集」，选任务类型和平台，点「检查环境」，全部通过后再开始。检查项里会明确写出缺什么。

### 采集支持的平台

| 平台 | 采集岗位 | 评分与招呼语 | 投递 | 监控回复 |
|---|---|---|---|---|
| Boss直聘 | 支持 | 支持 | 支持 | 支持 |
| 智联招聘 | 支持（需先在 Chrome 打开智联搜索页） | 支持 | 支持（点「立即投递」，平台把简历和它预置的招呼语一起发出，发不了工作台生成的招呼语；2026-11-18 真实验证过一次） | 暂未开放（回复可在「HR 回复」页发） |
| 前程无忧 | 支持 | 支持 | 暂未开放 | 暂未开放 |
| 猎聘 | 支持 | 支持 | 支持（在搜索页分栏点「聊一聊」，平台立刻发出它预置的招呼语，发不了工作台生成的招呼语；岗位页在后台标签里会被重定向，所以按关键词在搜索前 3 页里定位岗位；2026-11-18 真实验证过） | 暂未开放（回复可在「HR 回复」页发） |

- 采集页的「平台」四个都可选，「采集 + 打分 + 筛选」与「只采集」都不再锁定 Boss直聘；完整流程只做到采集、打分、按合格线（默认 60 分，可改，记在浏览器里）自动通过、生成招呼语，停在发送确认前。发送目前开放 Boss直聘、智联招聘和猎聘（智联、猎聘发出的是平台预置招呼语，不是工作台生成的那句）；前程无忧没有站内聊天，请自己发（工作台会拦下该平台岗位的发送）。
- 「岗位流水线 › 4 回复」页的 HR 会话读取覆盖 BOSS、智联、猎聘，读过的会话存本机、只有新消息才重读；Boss直聘、智联、猎聘都能在工作台里回复（每次需输入确认短语并勾选风险提示，用你已登录的 Chrome 页面发送一条）；智联走页面自带的 NIM 发送、猎聘走聊天抽屉的输入框，二者的真实发送还需你自己试发一条确认（见下）；前程无忧没有站内聊天，只读。读不到回复入口时页面给「去平台回复」直达按钮。
- 能力以内嵌组件 `vendor/offerpilot/src/offerpilot/collection/capabilities.py` 为准；上表没写「支持」的项目前不会执行。

### 测试

```bash
sh tools/run_tests.sh
```

脚本优先使用 `.venv`，依次跑三组测试：工作台（`tools/tests`）、对话与项目核验引擎（`tests`）、面试引擎（`interview_agent/tests`），任何一组失败整体即失败。测试只用虚构数据，不读取本机的 `web/data/`，在没有任何本机数据的全新克隆里也应全部通过。

命令行工具示例：

```bash
python3 -I tools/jd_intake.py --input demo/demo-job-001.md --out demo/job-001.json --id demo-job-001
```

```bash
python3 -I tools/orchestrator.py intake --input demo/demo-job-001.md --out demo/job-001.json --id demo-job-001
```

```bash
python3 -I tools/orchestrator.py approve --date 2026-11-14
```

```bash
python3 -I tools/orchestrator.py approve --date 2026-11-14 --confirm demo-job-001
```

```bash
python3 -I tools/orchestrator.py prepare --id demo-job-001 --date 2026-11-14
```

```bash
python3 -I tools/orchestrator.py status --id demo-job-001 --to 已过滤
```

```bash
python3 -I tools/orchestrator.py demo
```

`approve` 默认列出当日 pending 并写 Markdown 清单；显式 `--confirm <ids>` 才确认指定 ID。确认状态与实际执行结果分别记录。

## 网页工作台

网页工作台默认只在本机提供服务，用户数据保存在本机。OfferPilot 能力已整合到工作台；相关账户、会话和外部服务按个人配置运行。

```bash
sh run_web.sh
```

然后打开 `http://127.0.0.1:8766/`。工作台只有一种数据模式，直接读写本机 `web/data/user/` 下的用户数据。`web/data/`、`.venv/` 与旧的本机 `OfferPilot/` 克隆均已在 `.gitignore` 中忽略。

网页左侧包含七个入口，核心流程是前两个：

| 入口 | 作用 |
| --- | --- |
| **01 首页** | 今天要做的事：流程状态、待办与快捷入口 |
| **02 岗位流水线** | 页内四个页签：采集岗位（Boss 搜索表单 → 环境预检 → 自动导入、入队与招呼语，停在发送确认）、筛选（挑岗位）、已通过（确认并发送）、HR 回复（识别面试与笔试） |
| **03 个人资料** | 专业事实源 |
| **04 定制简历** | 经历变体与 ATS 检查 |
| **05 模拟面试** | 题单与复盘 |
| **06 信息推送** | 通知预览 |
| **08 设置** | 导出、测试、边界说明 |

**采集岗位**的固定流程：在 `02 岗位流水线 → 采集岗位` 填关键词、城市、页数、采集节奏（不写 `config.yaml`）→ 点「检查环境」→ 勾选确认后启动任务 → 任务完成后自动导入岗位池并跳到岗位表 → 岗位按文档筛选规则自动通过（已评分、不存在明确不满足的必备条件、岗位未关闭，不使用数字阈值）；默认任务类型是「完整流程」，采集后会继续自动入队并为已通过岗位生成招呼语，停在最终确认门，「仅采集」则只导入岗位池；未评分或按规则不推荐的岗位可「手动加入」，手动加入时需在下拉框选择原因（三项之一，不需要打字）。城市不在个人资料目标城市内的岗位会被拦截；30 天内已入队或已发送过的同一岗位会被跳过。高风险岗位（收费、培训贷、押金、保就业承诺等，见 `tools/job_risk.py`）会被拦截、不进入队列。采集节奏可选稳健（每次随机等待 6–15 秒，默认）、标准（3–7.5 秒）或快速（2–5 秒）；等待由运行时在每次翻页/读详情前随机生成。采集只读取公开职位列表，不打招呼、不投递；导入只复制岗位信息，审批仍需人工确认。评分需要先在采集页上传简历（`.md` / `.docx` / `.pdf`，最大 5 MB，只保存在本机运行时目录）：简历是采集的前置条件：未上传时「开始采集」禁用，后端也会拒绝启动（仅「监控」模式不需要简历）；上传后采集一律自动评分。匹配分由程序按固定权重计算（核心职责 30、项目/成果证据 25、技能与工具 15、职级与工作复杂度 10、地点与工作安排 10、薪资与其他偏好 10），模型只给每个维度的系数与证据；同时保存信息覆盖率。JD 明确必备条件为「明确不满足」或岗位已关闭 / 确认失效时，岗位移出默认推荐，不能自动入队，只能和低分岗位一样手动加入并填写原因；「待确认」不作为不满足处理。未评分（信息覆盖率 0）或按规则不推荐的岗位可点「手动加入」入队（标记 `manual_override`，直接为 `approved`），不会改变筛选规则；不再需要输入确认语。岗位与接口中的匹配分为文档的 0–100 整数，并附信息覆盖率 `score_coverage`；界面展示细节后续再补。审批队列的「今日安排」列由 `tools/quota_planner.py` 只读计算，按评分与风险排序，默认每日 30 条（`DEFAULT_DAILY_CONTACT_QUOTA`），超出额度的岗位顺延；这只是排序提示，实际发送上限仍由内嵌发送器强制。岗位列表每行带只读 `risk` 字段（`level`：low / verify / high），队列行带只读 `plan` 字段（`today`、`rank`、`reason`）；`pipeline.delivery.quota` 返回当日额度与剩余数。审批队列里已确认的岗位可以勾选后「生成招呼语」，结果在本页做只读预览；确认文本后可「复核并发送」，每批最多 10 条，风险勾选默认已勾选，点击后弹出确认框，确定后才发送，不需要输入文字。发送由内嵌运行时执行，沿用其每日上限、随机间隔与风控锁，全天可发送；工作台不提供 `force`，批次与逐条结果记录在本机 `web/data/<mode>/deliveries.json`。岗位池可勾选后「删除所选」（`delete-jobs`）：软删除，只标记 `deleted_at`，不物理删除，避免指纹去重失效导致下次导入复活；已 `approved` 或已出现在发送记录中的岗位会被跳过并在响应里列出原因（「已通过」页的「删除所选」带 `include_approved` 可删已通过 / 待确认的岗位，已有发送记录的仍受保护）；「筛选」页只列还没通过的岗位，已进入「已通过」的不再重复出现。个人资料保存在本机 `web/data/<mode>/profile.json`；生成内容可读取相关专业事实，联系方式不进入生成草稿。user 模式下，若尚未保存过资料且本机有可读的 Markdown 简历（优先 `workspace/resume.md`，其次采集页上传的简历），进入「个人资料」页时会自动预填经历、项目、教育、技能与简介作为草稿，需核对后手动保存。接口见 [web/PROFILE-API.md](web/PROFILE-API.md)。

工作台同时提供 JD 录入、筛选与评分、审批队列、沟通草稿、HR 回复跟进、日历文件、模拟面试题单与复盘、经历变体、ATS 检查、信息推送、测试、验收报告、JSON 导出和下载管理。核心接口契约见 [web/PIPELINE-API.md](web/PIPELINE-API.md)；岗位自动化接口见 [web/OFFERPILOT-EMBEDDED.md](web/OFFERPILOT-EMBEDDED.md)。

**Agent 后端**（本次接入，仅后端与路由，未改 `web/static/`）：文字模拟面试新增 `interview-start`、`interview-material-upload`、`interview-reply`、`interview-end`、`interview-drill` 五个动作与 `POST /api/interview/stream` SSE 出题；出题、追问、复盘和重练只在配置了模型后调用，失败不生成占位题目，复盘也不写入简历。项目核验桥接新增 `GET /api/resume-agent/materials`、`GET|POST /api/interview-agent/sessions...`，只转发到本机 `127.0.0.1:18747` 的外部引擎，需要 `OFFERPILOT_CAREER_AGENT_TOKEN`；另有 `GET /api/agent/capabilities` 返回无凭据的能力地图。项目核验的引擎源码不在本仓库。接口见 [web/INTERVIEW-TEXT-API.md](web/INTERVIEW-TEXT-API.md) 与 [web/CAREER-AGENT-API.md](web/CAREER-AGENT-API.md)。

采集窗口可选 BOSS 直聘、智联招聘、前程无忧与猎聘（`platform` 显式传给本次任务，不改 `config.yaml` 的 `enabled`）；`full` 投递全流程仍只接受 BOSS。HR 会话通过内嵌运行时只读读取：`GET /api/offerpilot/conversations?platform=...` 解析对应平台的聊天列表，`GET /api/offerpilot/conversation?platform=...` 读取单条会话的消息；`platform=all` 聚合四个平台，一个平台读取失败时其余平台照常返回并在 `platforms` / `errors` 里说明原因。BOSS、智联已在真实浏览器中验证可读；猎聘「我的沟通」抽屉与聊天窗口也已在真实页面读到、发过一条回复（猎聘点开联系人后，输入框与「发送」在独立的聊天窗口里，不在抽屉里）。前程无忧没有站内聊天，HR 沟通通过微信扫码完成，工作台不读取其消息，接口对 51job 返回不可用，之后不再验证。51job 的岗位采集不受此影响。回复走 `offerpilot-reply` 动作，支持 BOSS、智联、猎聘（智联、猎聘需要本次列表读取带到接口 id，否则提示先刷新会话列表；2026-11-18 已在真实账号上各发过一条并在对话里核对到），必须带确认短语、风险勾选，并满足停止状态、风险锁与「最近 10 分钟会话列表」检查后只发送一条（不设发送时间段）。会话正文脱敏后写入本机 `web/data/`（电话、邮箱、微信替换为占位），该目录不提交；列表每次刷新，未变会话不重开，读取失败保留旧正文并在会话上标 `stale`，落盘缓存不作为发送依据。HR 发来「要一份简历」的卡片时，回复页会显示卡片文字并给「同意 / 拒绝」按钮（`offerpilot-resume-request`，行内确认后在平台页面点卡片按钮，由平台发出你在该平台提交过的在线简历；智联「同意」已在真实账号验证，BOSS、猎聘点击尚未在真实卡片上验证，要「附件简历」的请求需在平台上传文件，工作台不自动处理）。活动日志只记动作与公司名。审批通过后的受控投递只有设计提案，尚未实现：[web/AUTO-DELIVERY-DESIGN.md](web/AUTO-DELIVERY-DESIGN.md)。

界面视觉语言参考项目 [offer_coming](https://github.com/lwt20000321-cmd/offer_coming)。

## 外部服务

如个人配置使用 UP 简历或 ClawJob MCP 等外部服务，其数据访问与密钥由用户配置及相应服务条款决定；这类服务不是工作台运行的必需项。

只看状态或打印不含密钥的 MCP 配置：

```bash
python3 -I -B tools/upcv_adapter.py --status
```

```bash
python3 -I -B tools/upcv_adapter.py --print-config
```

配置里的 `UPCV_API_KEY` 只是环境变量引用；密钥由你自己在 MCP 客户端环境中填写，不写入仓库。

## 配置与数据

- 岗位流程、沟通跟进、日历、面试与简历相关能力按页面入口和本机配置使用。
- 邮箱、信息推送、转写及其他外部服务按各自配置启用；未配置时保留本地数据与本地流程。
- 简历内容以用户确认的事实为准；不确定字段应先补充或标记，再生成相关材料。
- 生成内容只使用任务所需的专业事实，联系方式按模块规则处理。

## 公网展示部署（魔搭创空间 / 容器）

想让别人不装环境、点网址就能体验时，可以部署一个「展示版」。它和本机日常使用的工作台是两回事：

- 展示版**默认不限制功能**：访客可以自己登录自己的账号使用。需要锁死时设环境变量 `OFFERPILOT_DEPLOY_RESTRICT=1`，会拒绝平台自动化、测试、导出和 AI 设置写入。
- 平台自动化依赖运行服务的那台机器上有可用的 Chrome 浏览器；魔搭容器里没有，这类功能在线上会因找不到浏览器而失败，建议这类功能仍在本机使用。
- 模型密钥可由部署环境变量预置（访客也能在设置里改成自己的）；会调用模型的请求按来源限频（10 分钟 40 次，全站 600 次）。
- 所有访客共用同一份数据空间：别人填的 Key、简历、登录状态对下一个访客也可见，不要在公开的展示版里填真实个人资料。
- 真正带账号和简历的工作台仍只监听 `127.0.0.1`，不要部署到公网。

本机先模拟一次（用 `--deploy` 会监听 `0.0.0.0:$PORT`，默认 7860；它也会占用 18747/18748，需先停掉本机工作台）：

```bash
OFFERPILOT_DEPLOY=1 PORT=7860 .venv/bin/python -B tools/run_career_demo.py --deploy --engine-root .
```

部署到魔搭创空间（Docker 类型，端口 7860，需要先完成阿里云账号绑定与实名认证，见魔搭文档）：

1. 在魔搭网页新建创空间，类型选 Docker，记下 `用户名/创空间名`。
2. 在创空间「设置」里添加密钥变量 `OFFERPILOT_MODEL_API_KEY`，以及明文变量 `OFFERPILOT_MODEL_BASE_URL`、`OFFERPILOT_MODEL_NAME`（可选 `OFFERPILOT_MODEL_SERVICE`，默认 `custom`）。不配也能部署，只是模型功能显示未配置。
3. 在自己的终端里推送并触发部署（令牌在 <https://modelscope.cn/my/myaccesstoken> 获取，只放在终端环境变量里）：

```bash
export MODELSCOPE_API_KEY=你的令牌
sh tools/deploy_modelscope.sh 用户名/创空间名
```

**以后改了代码要更新**：先 `git commit`，再重新运行同一条 `sh tools/deploy_modelscope.sh 用户名/创空间名`。脚本只上传已提交且未被 `.gitignore` 忽略的文件，不会带上 `web/data/`、简历和凭据，更新后网址不变。`--no-deploy` 只推送、不触发重新构建。

## 使用范围

本项目面向用户本人授权的本机求职流程。自动化功能仅用于用户有权访问和操作的账号、资料及平台；用户自行确认平台规则、账号影响、隐私与外部服务的数据处理方式。不要将真实身份资料、账号凭据或个人浏览器数据提交到仓库。

凭据不进仓库：模型 API Key 只在网页「设置 › AI 接口设置」填写，保存在被忽略的 `web/data/user/offerpilot/` 下；GitHub 登录令牌保存在本机 user 目录（Windows 用当前用户 DPAPI 加密，POSIX 用仅所有者可读写的文件）。`.env`、`workspace/` 下的个人资料、`web/data/`、`.venv/` 已在 [.gitignore](.gitignore) 中忽略。

## 验收文档

- [TASK-03 验收](prompts/TASK-03-验收.md)
- [TASK-04 验收](prompts/TASK-04-验收.md)
- [TASK-05 验收](prompts/TASK-05-验收.md)
- [TASK-06 验收](prompts/TASK-06-验收.md)
- [TASK-07 验收](prompts/TASK-07-验收.md)

这些文档说明各阶段的验收结果与未完成项；功能状态以当前代码和测试为准。

## 全局 Agent 对话工作台

「02 对话助理」按求职目标保存会话（队友云端版的“流程总览”页签暂未接入）。Agent 可读取已有岗位与专业资料，推荐岗位，基于已确认材料生成、修改简历和招呼语草稿，展示差异与来源。修改确认事实或保存正式版本前需要核对具体结果；草稿修改使旧确认失效。招呼语目前提供复制并转到原发送复核，不会同步到发送器或自动发送。

启动方式见上文「运行 › 启动」，更新后需重启本机工作台和 Python 引擎。接口、停止/恢复、数据边界及回退开关见 [全局 Agent 接口](web/WORKBENCH-AGENT-API.md)。现有 `/api/state` 的 27 个顶层字段、业务页面和发送保护保持兼容。
