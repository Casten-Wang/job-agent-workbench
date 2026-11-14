# TASK-06 验收记录（主会话实现与复核）

本记录对应 `prompts/TASK-06-orchestration.md` 与 `PLAN.md` 第 4、5 节。CLI 只用显式本地输入、虚构 demo 数据与 Python 3 标准库；不联网、不读取真实邮箱/飞书、不提交申请。

## 调研结论

主会话直接读取了 `tools/` 下已有模块与测试，确认存在：`precheck.py`、`filters.py`、`jd_intake.py`、`ats_check.py`、`variants.py`、`mail_classifier.py`、`state_machine.py`、`calendar_ics.py`、`feishu_adapter.py`、`imap_watcher.py`、`analytics.py`、`mock_interview.py`、`asr_adapter.py`、`interview_debrief.py`、`interview_analytics.py`、`offerpilot_adapter.py`。未发现缺失的必需模块；所有可选模块均通过 `degrade.load_module_safely` 带结构化告警降级。

## 产出文件

- `tools/config_task06.json`：评分阈值、审批规则、话术上限、demo 路径、边界开关。
- `tools/orchestrator.py`：`intake`、`approve`、`prepare`、`status`、`demo` 五个子命令。
- `tools/greeting.py`：≤150 字破冰话术草稿；只用 JD 公司/岗位与本地 `resume.md` 中逐字存在的技能词。
- `tools/approval_queue.py`：本地 JSON 队列，按日聚合、去重、显式 confirm。
- `tools/degrade.py`：模块加载失败写 append-only `tools/data/degrade.log`，返回 `module_unavailable`。
- `demo/`：3 条虚构 JD、2 封虚构邮件、1 份虚构逐字稿、隔离审批队列/题库/复盘产物与 `REPORT.md`。
- `README.md`：项目结构、CLI、测试命令、手动步骤与边界。
- `tools/tests/test_task06.py`：9 个离线测试。

## 已自动验证

| 测试 / demo 结果 | 对应 PLAN.md 验收条目 |
|---|---|
| `>=4.5` 与 `4.0–4.4` 都进入队列但保持 `pending`；`--confirm` 才改 `approved`，`auto_submit: false` | 第 0 节人工确认；TASK-06 每日一批审批 |
| `<4.0` 丢弃；重复 ID 不入队 | M5 阈值与全局去重 |
| 话术 ≤150 字、只用 CV 技能词、无虚构数字；超长输入截断并 warning；含数字的公司/岗位不引入 | M10 破冰话术；全局事实边界 |
| `approve --date` 只生成 Markdown 清单，不改队列状态 | M9 投递确认 |
| 模块缺失写结构化 degrade 日志，不静默吞异常 | 容错要求 |
| `intake` 输出标准 JSON；非法状态跃迁拒绝 | M2/M12 编排 |
| `demo` 实际生成 `demo/REPORT.md`，含 7 个链路步骤和告警汇总；演示队列两条均为 `pending`，未出现 `approved` | 阶段 1–4 离线端到端串联 |
| `git status --porcelain` 无输出 | 不修改个人文件 |

## 需人工验证

- 用 10 份真实 JD 运行工作台的评估、定制、PDF 与 fact gate；生成简历中每个数字是否在 `resume.md` 有出处。
- 用真实 PDF 阅读器/ATS 解析器检查中文字体、分栏顺序、表格、图片与关键词覆盖。
- 人工将话术复制到招聘平台并点击发送；人工点击表单 Submit/Apply。
- 真实 IMAP/飞书/日历 5 分钟时延、真实录音转写、真实候选人复盘质量。
- `resume.md` 中 `[[ILLEGIBLE]]`、联系方式占位符与未确认字段需要用户后续补齐后人工复核。

## 未实现 / 未确认

- 未实现无人确认的自动投递、自动发送招呼语、自动提交表单、招聘平台抓取、反爬绕过、微信 Hook/MITM、浏览器 CDP 接管。
- 未实现真实 IMAP 轮询、真实飞书 HTTP、真实系统日历写入、真实 ASR 运行、外部 LLM 调用。
- 未实现 `portals.yml` 20 家公司配置与公开 ATS 扫描；未配置岗位画像、`archetypes` 与 `narrative` 字段。
- 未实现私域微信群截图 OCR、潮汐监控、HR 活跃状态解析。
- 字段名 `LLM_Rewrite_Edited_Flag` 与 `PLAN.md` 的 `LLM_Edited_Flag` 差异：**未确认**。
- 分数来源：demo 分数为显式测试输入；真实岗位仍需要 workspace/LLM 评估，当前 CLI 不自动打分。

## 明确边界

`orchestrator.py` 与所有新增模块只读写本地文件；`prepare` 生成的是待办清单、话术草稿、去重结果和表单字段清单，`status` 只追加本地状态日志，`demo` 只写报告。没有 `.submit()`、`.send()`、Playwright `click(Submit)`、HTTP POST 或平台登录态读取路径。

## 复核结论

编排层与离线演示已完成并通过全量测试；需人工/外部凭据的真实求职动作均明确留给人执行，不把 dry-run 或测试输入写成真实闭环成功。
