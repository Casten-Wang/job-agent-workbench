# 秋招规划师 · OfferPilot

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
| `tools/tests/` | 标注过的虚构测试数据和 `unittest` |
| `demo/` | 3 条虚构 JD、2 封虚构邮件、1 份虚构逐字稿及演示报告 |
| `demo/REPORT.md` | 由 `orchestrator.py demo` 实际生成的端到端结果 |
| `CLAUDE.md` | 项目规范：模块所有权、修改边界、共享外壳与接口稳定性；改动前先读 |
| `web/` | 本地网页工作台：`backend.py`、`server.py`、`offerpilot_runtime.py`、`static/`、`DESIGN.md` |
| `vendor/offerpilot/` | OfferPilot 岗位自动化运行时（内嵌组件） |
| `requirements-offerpilot.txt`、`run_web.sh` | 工作台启动所需的运行配置与脚本 |
| `web/data/demo/` | 明显虚构的演示数据；`web/data/user/` 是用户本地数据，均不提交；岗位自动化运行时在 `web/data/<mode>/offerpilot/` |
| `PLAN.md`、`VERSIONS.md` | 架构决策与阶段 0 版本记录 |

## 参与改动

先读 [CLAUDE.md](CLAUDE.md)。仓库按已暴露模块（工作台、岗位池、个人资料、模拟面试、信息推送、定制简历、数据与设置等）划分所有权；每个模块只改自己范围内的 `#view-*` 区段、`app.js` 函数、`backend.py` 动作与对应测试，不改共享外壳或其他模块的 DOM/字段/接口。接口契约变更只允许加字段，并同步更新 `web/PIPELINE-API.md`、`web/PROFILE-API.md` 与测试。

## 运行

运行需要 Python 3（建议 3.11+）。

```bash
sh tools/run_tests.sh
```

启动本机工作台：

```bash
./run_web.sh
```

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

然后打开 `http://127.0.0.1:8766/`。首次打开 demo 模式会自动生成明显虚构的演示数据；切换到 user 模式后只读写本地用户数据。`web/data/`、`.venv/` 与旧的本机 `OfferPilot/` 克隆均已在 `.gitignore` 中忽略。

网页左侧包含七个入口，核心流程是前两个：

| 入口 | 作用 |
| --- | --- |
| **01 工作台** | 今天做什么：六段流程状态、待办与快捷入口 |
| **02 求职主线** | 页内四个页签：采集岗位（Boss 搜索表单 → 环境预检 → 自动导入、入队与招呼语，停在发送确认）、岗位池挑选、审批队列（人工确认可投递）、HR 回复（识别面试与笔试） |
| **03 个人资料** | 专业事实源 |
| **04 模拟面试** | 题单与复盘 |
| **05 信息推送** | 通知预览 |
| **06 定制简历** | 经历变体与 ATS 检查 |
| **07 数据与设置** | 导出、测试、边界说明 |

**采集岗位**的固定流程：在 `02 求职主线 → 采集岗位` 填关键词、城市、页数、采集节奏（不写 `config.yaml`）→ 点「检查环境」→ 勾选确认后启动任务 → 任务完成后自动导入岗位池并跳到岗位表 → 岗位按评分自动通过（评分 ≥ 4.0）；默认任务类型是「完整流程」，采集后会继续自动入队并为已通过岗位生成招呼语，停在最终确认门，「仅采集」则只导入岗位池；评分不足的岗位可「手动加入」，手动加入时需在下拉框选择原因（三项之一，不需要打字）。城市不在个人资料目标城市内的岗位会被拦截；30 天内已入队或已发送过的同一岗位会被跳过。高风险岗位（收费、培训贷、押金、保就业承诺等，见 `tools/job_risk.py`）会被拦截、不进入队列。采集节奏可选稳健（每次随机等待 6–15 秒，默认）、标准（3–7.5 秒）或快速（2–5 秒）；等待由运行时在每次翻页/读详情前随机生成。采集只读取公开职位列表，不打招呼、不投递；导入只复制岗位信息，审批仍需人工确认。评分需要先在采集页上传简历（`.md` / `.docx` / `.pdf`，最大 5 MB，只保存在本机运行时目录）：简历是采集的前置条件：未上传时「开始采集」禁用，后端也会拒绝启动（仅「监控」模式不需要简历）；上传后采集一律自动评分。低于 4.0 评分门或未评分的岗位可点「手动加入」入队（标记 `manual_override`，直接为 `approved`），不会改变共享的评分门；不再需要输入确认语。审批队列的「今日安排」列由 `tools/quota_planner.py` 只读计算，按评分与风险排序，默认每日 30 条（`DEFAULT_DAILY_CONTACT_QUOTA`），超出额度的岗位顺延；这只是排序提示，实际发送上限仍由内嵌发送器强制。岗位列表每行带只读 `risk` 字段（`level`：low / verify / high），队列行带只读 `plan` 字段（`today`、`rank`、`reason`）；`pipeline.delivery.quota` 返回当日额度与剩余数。审批队列里已确认的岗位可以勾选后「生成招呼语」，结果在本页做只读预览；确认文本后可「复核并发送」，每批最多 10 条，风险勾选默认已勾选，点击后弹出确认框，确定后才发送，不需要输入文字。发送由内嵌运行时执行，沿用其发送窗口、每日上限、随机间隔与风控锁；工作台不提供 `force`，批次与逐条结果记录在本机 `web/data/<mode>/deliveries.json`。岗位池可勾选后「删除所选」（`delete-jobs`）：软删除，只标记 `deleted_at`，不物理删除，避免指纹去重失效导致下次导入复活；已 `approved` 或已出现在发送记录中的岗位会被跳过并在响应里列出原因。个人资料保存在本机 `web/data/<mode>/profile.json`；生成内容可读取相关专业事实，联系方式不进入生成草稿。user 模式下，若尚未保存过资料且本机有可读的 Markdown 简历（优先 `workspace/resume.md`，其次采集页上传的简历），进入「个人资料」页时会自动预填经历、项目、教育、技能与简介作为草稿，需核对后手动保存。接口见 [web/PROFILE-API.md](web/PROFILE-API.md)。

工作台同时提供 JD 录入、筛选与评分、审批队列、沟通草稿、HR 回复跟进、日历文件、模拟面试题单与复盘、经历变体、ATS 检查、信息推送、测试、验收报告、JSON 导出和下载管理。核心接口契约见 [web/PIPELINE-API.md](web/PIPELINE-API.md)；岗位自动化接口见 [web/OFFERPILOT-EMBEDDED.md](web/OFFERPILOT-EMBEDDED.md)。审批通过后的受控投递只有设计提案，尚未实现：[web/AUTO-DELIVERY-DESIGN.md](web/AUTO-DELIVERY-DESIGN.md)。

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
- 邮箱、信息推送、转写及其他外部服务按各自配置启用；未配置时保留本地数据和演示流程。
- 简历内容以用户确认的事实为准；不确定字段应先补充或标记，再生成相关材料。
- 生成内容只使用任务所需的专业事实，联系方式按模块规则处理。

## 使用范围

本项目面向用户本人授权的本机求职流程。自动化功能仅用于用户有权访问和操作的账号、资料及平台；用户自行确认平台规则、账号影响、隐私与外部服务的数据处理方式。不要将真实身份资料、账号凭据或个人浏览器数据提交到仓库。

凭据只从环境变量或本机运行时配置读取；`.env`、`workspace/` 下的个人资料、`web/data/`、`.venv/` 已在 [.gitignore](.gitignore) 中忽略。

## 验收文档

- [TASK-03 验收](prompts/TASK-03-验收.md)
- [TASK-04 验收](prompts/TASK-04-验收.md)
- [TASK-05 验收](prompts/TASK-05-验收.md)
- [TASK-06 验收](prompts/TASK-06-验收.md)
- [TASK-07 验收](prompts/TASK-07-验收.md)

这些文档说明各阶段的验收结果与未完成项；功能状态以当前代码和测试为准。
