# TASK-04 验收记录（主会话实现与复核）

本记录对应 `prompts/TASK-04-email-calendar-tracker.md` 与 `PLAN.md` 第 3 节 M11/M12/M17、第 4 节阶段 3。所有测试使用明显虚构的本地样例；没有真实邮箱、真实飞书、真实日历写入或网络请求。

## 产出文件

- `tools/config_task04.json`：轮询间隔 300 秒、同步时效目标 300 秒、状态机、时区、意图关键词、环境变量名（仅名称，不含值）。
- `tools/mail_classifier.py`：离线确定性意图分类；时间、会议链接、公司、岗位显式提取；指令样文本作为 `input_anomalies` 原样引用。
- `tools/state_machine.py`：合法跃迁追加到 JSONL；非法跃迁/未知状态拒绝且不写日志。
- `tools/calendar_ics.py`：RFC 5545 `.ics`；Asia/Shanghai 固定 UTC+08:00，输出 `DTSTART`/`DTEND` 为 UTC `Z` 时间，转义 TEXT、按 UTF-8 字节折行。
- `tools/feishu_adapter.py`：dry-run only；只检查环境变量是否存在，不读取/输出凭据值，无 HTTP 客户端。
- `tools/imap_watcher.py`：读取本地 `.eml`/JSON 样例，按 Message-ID 去重；真实 IMAP 仅留脱敏配置签名与 `not_implemented_offline_build`。
- `tools/analytics.py`：渠道 ROI、`Rejection_Reason` unknown 统计、季度雷达 JSON；不画图。
- `tools/tests/mail-samples.json`：20 封标注样例 + 1 封重复 Message-ID，全部测试数据。
- `tools/tests/test_task04.py`：15 个离线测试。

## 已自动验证

| 测试 | 对应 PLAN.md / 任务规格 |
|---|---|
| 20 封标注样例分类：20/20 = 100%，≥90% 门槛通过 | 阶段 3「20 封标注邮件分类准确率 ≥ 90%」 |
| `.eml` 解析、中文日期时间 `2026-11-20T14:30:00`、会议链接、公司/岗位、Message-ID | M11 邮件意图与实体提取 |
| 缺失实体为 `null`、指令文本为数据、UTC hint 转本地时间 | 不可信外部内容边界；不猜测 |
| 本地目录 20 封样例 + 重复 ID 去重为 20 条，禁用 socket | M11 本地离线监听与 Message-ID 去重 |
| 合法状态跃迁追加 JSONL；非法跃迁与未知状态不写日志 | M12 全局状态机 |
| `.ics` 本地 14:30 转 UTC 06:30、60 分钟结束、TEXT 转义、长行折行、UTC offset 输入、缺少/非法时间明确报错 | M12 日历；起止时间不编造 |
| 飞书 dry-run 输出不含环境变量值或额外字段；HTTP 未实现 | M12 冷热分离；凭据只经环境变量名 |
| 渠道投递数/面试数/Offer数/淘汰数/转化率、`Rejection_Reason` unknown、季度雷达聚合 | M17 渠道 ROI 与季度数据 |
| 状态日志事件按 job 去重计数，不把同一岗位三次跃迁计成三次投递 | M17 分析口径 |

## 需人工验证

- 真实 IMAP 到达后到看板/日历的「≤5 分钟」端到端时延：需要用户自己的邮箱、凭据、轮询进程与真实飞书/Bitable；离线样例只能验证同步 SLA 配置值为 300 秒。
- 真实飞书多维表格、飞书日历、OAuth/tenant token 与字段映射：未接入。
- 真实邮件里复杂 HTML、时区缩写、转发链、日历附件 `.ics`、反垃圾/编码变体：当前规则分类器未覆盖。
- 面试官改期、取消、多时间候选、跨日 UTC 转换：当前只抽第一个本地日期时间；需人工复核。
- 真实 PII 进入日志/表格的脱敏策略：本项目 dry-run payload 已限制字段，但真实接入适配器仍需用户自行审计。

## 未实现 / 未确认

- 未实现真实 IMAP 连接、真实 HTTP 飞书调用、自动轮询守护进程、自动写系统日历。
- 未实现 LLM 邮件分类 adapter；当前是确定性关键词规则，结果含 `engine`、`confidence` 与 `scores`。
- 未实现微信/IM Hook、MITM、招聘平台消息监听；专用邮箱转发属于人工流程。
- `Source_Channel`、`Rejection_Reason` 与 本地 tracker 的真实字段映射：**未确认**。
- `PLAN.md` M17 的 `LLM_Edited_Flag` 与 TASK-03/TASK-04 使用的 `LLM_Rewrite_Edited_Flag` 命名差异：**未确认**。
- 真实邮箱服务商的 IMAP 主机、端口、应用专用密码策略：**未确认**。

## 真实接入所需配置清单（不提问）

`JOB_AGENT_IMAP_HOST`、`JOB_AGENT_IMAP_USER`、`JOB_AGENT_IMAP_PASSWORD`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_TABLE_TOKEN`；另需用户提供真实 IMAP 轮询器与飞书 HTTP 适配器，并显式确认发起连接。

## 复核结论

离线链路全部通过自动测试；真实邮箱/飞书/日历端到端时延与真实邮件复杂度未验证，不记作已完成。代码中没有自动投递、抓取、检测绕过或凭据值写入路径。
