# 最终结果（主会话复核）

生成日期：2026-11-14。本文只记录当前项目目录里实际存在、且本轮重新跑过的产物；不把离线演示写成真实求职闭环成功。

## 一句话结论

本地离线工具层与网页工作台都已搭好并通过自动测试；端到端 demo 已实际生成 [demo/REPORT.md](demo/REPORT.md)，网页在 `127.0.0.1` 上完成桌面/移动端与主要交互验收。OfferPilot 已完整内嵌到同一服务（`vendor/offerpilot/`），只使用工作台自己的回环端口。真实平台投递、真实邮箱/飞书/日历同步、真实语音转写与 LLM 打分仍未接通，明确留作人工验证或未实现。

## 交付物

| 结果 | 路径 |
|---|---|
| 最终结果 | [FINAL-RESULT.md](FINAL-RESULT.md) |
| 使用说明与边界 | [README.md](README.md) |
| 架构与复用决定 | [PLAN.md](PLAN.md) |
| 阶段 0 版本与体检记录 | [VERSIONS.md](VERSIONS.md) |
| 离线端到端演示报告 | [demo/REPORT.md](demo/REPORT.md) |
| 简历截图人工转录 | [resume-source.md](resume-source.md) |
| 本机主简历 | `workspace/resume.md`（本地文件，不提交） |
| 可选的结构化资料备份 | `workspace/profile.yml`（本地文件，不提交；当前工作台不直接读取） |
| 简历未确认字段清单 | [prompts/TASK-02-待确认.md](prompts/TASK-02-待确认.md) |
| TASK-03/04/05/06/07 验收记录 | [prompts/TASK-03-验收.md](prompts/TASK-03-验收.md)、[TASK-04](prompts/TASK-04-验收.md)、[TASK-05](prompts/TASK-05-验收.md)、[TASK-06](prompts/TASK-06-验收.md)、[TASK-07](prompts/TASK-07-验收.md) |
| 离线模块与测试 | `tools/*.py`、`tools/tests/`、`tools/run_tests.sh` |
| 本地网页工作台 | [web/](web/)：`backend.py`、`server.py`、`offerpilot_runtime.py`、`static/index.html`、`static/styles.css`、`static/app.js`、`DESIGN.md` |
| 内嵌 OfferPilot 后端 | [vendor/offerpilot/](vendor/offerpilot/)（上游源码与 PolyForm Noncommercial `LICENSE`）、`requirements-offerpilot.txt`、`run_web.sh` |
| 网页设计约束 | [web/DESIGN.md](web/DESIGN.md)：左侧九入口（02 找岗位为采集/岗位池二级页签）、六段核心流程、9 状态工序带、offer_coming 视觉语言、浅/深/跟随系统、图表与数据表并存 |
| 外部 Agent 接口 | [web/PIPELINE-API.md](web/PIPELINE-API.md)：六段流程、`GET /api/pipeline`、`POST /api/pipeline/event`、只记录不发送的边界 |
| 可选外部增强适配器 | `tools/upcv_adapter.py`：只读 UPCV/ClawJob MCP 元数据与配置模板，不进入默认运行路径 |
| 细粒度子任务提示词 | `prompts/TASK-01-precheck.md` 至 `prompts/TASK-07-offerpilot-adapter.md` |

## 已自动验证

| 检查 | 实际结果 |
|---|---|
| 全量单元测试 | `sh tools/run_tests.sh`：`Ran 133 tests` / `OK`（不要求安装 OfferPilot 依赖，内嵌运行时被 mock） |
| 网页后端与 HTTP 层 | `tools/tests/test_web_backend.py`：demo 种子、27 个快照键、六段 pipeline 契约、外部事件只记录不发送、日期筛选、评分入队、精确确认语、状态机合法性、去重、PDF 保守判定、Host/Origin/路径穿越防护、无凭据字段、仅回环绑定 |
| 网页前端静态审计 | `app.js` 无 `innerHTML`/`outerHTML`/`insertAdjacentHTML`/`document.write`/`eval`；仅同源 `/api` 请求；无外部 URL、CDN、iframe、`@import` 或 `url(...)` |
| 网页浏览器实测 | 桌面端 1440×900 无横向溢出（本工作台按桌面使用设计，手机端不作为本轮目标）；左侧九入口导航、02 找岗位的「采集岗位 / 岗位池」页签、六段流程点击跳转、三态主题、筛选、9 状态工序带点击、JD 录入、JSON 导入、审批确认、邮件解析与 `.ics`、Mock 题单、逐字稿复盘、题库、经历变体、ATS 预检、运行测试、验收报告、JSON 导出、飞书 dry-run、重置 demo 均成功；`POST /api/pipeline/event` 回报后流程卡显示「已接入回报」；采集岗位向导实测 user 模式预填关键词/城市/页数、5 项环境检查通过（搜索参数、AI、浏览器运行时、Chrome 调试端口、BOSS 标签页）、只读 15 条结果、双勾选后启动按钮才解禁，demo 模式显示「演示只读」且启动、导入与全选均禁用；导入岗位池由单元测试覆盖，未在真实岗位池执行；个人资料页实测演示资料完整度 100%、编辑保存、动态增删项目、`GET /api/profile` 读取均成功；控制台无报错 |
| 外部 Agent 契约 | `GET /api/pipeline` 返回六段流程与 `POST /api/pipeline/event` 的 schema；事件只追加到 `pipeline-events.jsonl`，`auto_submit: false`、`auto_send: false`、`event_is_record_only: true`；文档见 [web/PIPELINE-API.md](web/PIPELINE-API.md) |
| 离线端到端 demo | `python3 -I -B tools/orchestrator.py demo`：`ok: true`、`steps: 7`、`warnings: []`、`auto_submit: false` |
| 报告结构 | `demo/REPORT.md` 共 9 个 `##` 分节；告警汇总为 `[]`；无 `approved` 或 `submitted` 状态 |
| 内嵌运行时导入 | `.venv/bin/python -I` 加载 `vendor/offerpilot/src` 下的 `offerpilot.web.server`，`AGENT_API_VERSION` 为 `v1` |
| 内嵌运行时目录 | 运行数据只落在 `web/data/<mode>/offerpilot/`；`web/data/` 整体被忽略 |
| 运行时边界 | Python AST 检查未发现 forbidden import 或 `submit/send/post/connectOverCDP/launch/click/system/exec/eval` 调用 |
| 代码静态扫描 | 运行时模块未发现 `requests`、`urllib`、`http.client`、`imaplib`、`smtplib`、`selenium`、`playwright`、`CDP`、`9222`、`8686`、Hook/MITM/检测绕过调用 |
| 凭据与 PII | `tools/`、`demo/` 中未发现凭据赋值；`demo/REPORT.md` 只有环境变量名和布尔存在标志，没有凭据值、真实手机号或真实邮箱 |
| 用户数据隔离 | 清理早期 demo 污染后，`tools/data/question-bank.json` 为空题库（0 题）；demo 隔离题库有 2 条虚构抽取题；重复运行 demo 不再写入用户题库 |
| 临时产物 | `.env` / `*.env.local` / `*.pyc` / `__pycache__` 已清理；测试脚本加 `-B` 避免再次生成字节码 |
| 事实边界 | `[[ILLEGIBLE]]`、`{{PHONE_4f3af209}}`、`{{EMAIL_4fa1edb4}}` 等占位符保留；未补造简历数字、经历或联系方式 |

自动化覆盖的模块链路：30 天去重、JD 标签录入、城市/排除词/薪资硬规则、SHA-256 指纹、ATS PDF 保守检查、经历变体、OfferPilot 静态手动导出、20 封标注邮件分类、Message-ID 去重、状态机、RFC 5545 `.ics`、飞书 dry-run、渠道 ROI/季度雷达、空题库提示、Mock 三段题单、ASR 适配器、逐字稿复盘、弱点统计、审批队列、150 字话术草稿、结构化降级日志、CLI 编排与 demo 报告。

## 网页工作台

启动方式（只监听本机回环地址；首次运行会创建 `.venv` 并安装内嵌后端依赖）：

```bash
./run_web.sh
```

打开 `http://127.0.0.1:8766/`。`demo` 与 `user` 数据完全隔离，分别落在 `web/data/demo/` 与 `web/data/user/`；内嵌 OfferPilot 运行时在 `web/data/<mode>/offerpilot/`。`web/data/`、`.venv/` 与旧的 `OfferPilot/` 克隆已被 `.gitignore` 忽略。页面使用同源 JSON API，CSP 为 `default-src 'self'`，不加载 CDN、外部字体、iframe 或第三方脚本。

左侧九个入口：**01 工作台**（六段核心流程、9 状态工序带、6 项 KPI、渠道/季度/弱点/邮件四张 SVG 图与数据表、最近动作，以及去采集/岗位池/审批队列的快捷入口）、**02 找岗位**（二级页签：**采集岗位**是「搜索表单 → 环境预检 → 只读结果 → 导入岗位池」三步向导，参数只作用于本次任务；**岗位池**是 JD 录入、岗位表格、状态流转与折叠的静态 JSON 导入）、**03 审批队列**（pending/approved、精确确认语「确认可人工投递」）、**04 HR 回复**（离线意图分类与 `.ics`）、**05 个人资料**（结构化事实源、完整度、动态经历卡片、简历导入）、**06 模拟面试**（Mock 题单、逐字稿复盘、题库、外部 Agent 预留）、**07 信息推送**（飞书 dry-run、外部推送 Agent 预留）、**08 定制简历**（ATS 静态 PDF 检查、经历变体、外部简历 Agent 预留）、**09 数据与设置**（运行测试、网页验收报告、JSON 导出、下载列表、运行边界、配置摘要、重置 demo）。

模块所有权与修改边界见 [CLAUDE.md](CLAUDE.md)：每个已暴露模块只改自己的 `#view-*` 区段、`app.js` 函数、`backend.py` 动作与对应测试，不改共享外壳或其他模块。

六段流程前四段在本机完成；发送只能走内嵌 OfferPilot 既有的人工确认流程，HR 回复监控没有工作台自己的发送路径，外部 Agent 通过 `POST /api/pipeline/event` 回报，界面显示「待接入 / 已接入回报」。视觉语言复用队友项目 offer_coming，但仍是零构建、零 CDN 的原生 HTML/CSS/JS。

`approved` 只表示「可人工投递」，页面没有自动提交按钮，也不会调用平台接口。

## 需人工验证

1. 10 份真实 JD 的评分、定制简历、单栏 ATS PDF 渲染、中文字体/分栏/关键词覆盖与事实数字溯源。
2. 用户手动补齐 `[[ILLEGIBLE]]`、联系方式占位符、目标岗位/薪资/城市偏好、`archetypes`、`narrative` 与 `modes/_profile.md` 后，重新人工核查 CV。
3. 人工复制话术、人工填表、人工上传 PDF、人工点击 Submit/Send/Apply；`approved` 仅表示「可人工投递」，不代表已投递。
4. 真实 IMAP 轮询、真实飞书 Bitable/日历 HTTP、真实系统日历导入、端到端 ≤5 分钟时效。
5. 真实 OfferPilot 手动导出字段、编码、嵌套结构、薪资单位与脱敏；当前只覆盖宽松别名映射。
6. 真实录音转写准确率、说话人分离、中文标点；真实 30 分钟互动式 Mock 面试质量。
7. 真实 JD active status、发布时间、HR 活跃度、`portals.yml` 20 家公司与同配置两次扫描一致性。
8. 用你自己的真实单栏 PDF 在网页里走一次 ATS 上传检查；自动测试只覆盖可提取文字层与保守失败路径，真实排版/字体/分栏仍需人工确认。
9. 用你自己的浏览器窗口再看一次网页的桌面与手机布局、深色主题和键盘焦点；本轮验收使用内置浏览器模拟视口，不等同于所有真实设备。

## 未实现 / 明确不接入

- 工作台自己实现的招聘平台采集器、新的反爬/验证码/登录态绕过、微信 Hook、MITM、社媒签名逆向；平台采集与浏览器自动化只由内嵌 `vendor/offerpilot/` 按上游既有实现执行。
- 无人确认的自动投递、自动发送招呼语、自动提交表单；工作台没有 `.submit()`、`.send()`、`.post()` 或浏览器点击路径，任务接口只接受 `collect` / `monitor` / `full`。
- 真实 IMAP 连接、真实飞书 HTTP 调用、自动轮询守护进程、自动写系统日历。
- 外部 LLM 调用与自动打分；demo 分数是显式测试输入，不是模型评估结果。
- `faster-whisper` 安装、模型下载、音频读取、真实转写与对话式 AI 面试官。
- 私域微信群截图 OCR、潮汐监控、第三方 PII 批量入库。
- UPCV/ClawJob MCP 未接入默认运行路径：它是 MIT 许可的云端服务，需要 `UPCV_API_KEY` 并访问外网；本项目只提供 `tools/upcv_adapter.py` 的状态查询与配置模板，不代填密钥、不发起请求。
- `LLM_Rewrite_Edited_Flag` 与 `PLAN.md` 的 `LLM_Edited_Flag` 字段名差异：保留为未确认，未擅自统一。
- `prompts/TASK-03-验收.md` 薪资格式行保留占位符 `15000-25000`；按占位符规则未替换为示例值。

## 本轮最终状态

- 用户层数据：`tools/data/question-bank.json` 为空题库；`tools/data/degrade.log` 与 `tools/data/status-log.jsonl` 未生成。
- demo 层数据：`demo/REPORT.md`、`demo/approval-queue-demo.json`、`demo/question-bank.json`、`demo/interviews/demo-transcript.md` 均为隔离测试数据。
- 网页 demo 数据已重置为 3 个虚构岗位、2 封虚构邮件、1 份虚构复盘、2 条待确认；`web/data/demo/downloads/` 与 `pipeline-events.jsonl` 的测试产物已清空；`web/data/user/` 未被测试写入。
- 个人资料只保存在本机 `workspace/`；本轮只新增/复核项目根目录下的 `tools/`、`demo/`、`prompts/` 与说明文档。
- 所有自动验证通过；真实接入与真实求职动作均没有冒称完成。

## 复现命令

```bash
sh tools/run_tests.sh
```

```bash
python3 -I -B tools/orchestrator.py demo
```

```bash
./run_web.sh
```
