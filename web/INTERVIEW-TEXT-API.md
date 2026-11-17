# 文字模拟面试接口 v0.1

本文件记录模拟面试模块新增的文字对话后端：`tools/interview_chat.py` 负责纯规则与校验，`web/backend.py` 负责会话落盘与动作，`web/server.py` 提供 SSE 路由。页面入口仍属于前端模块，本次未改动 `web/static/*`。

## 数据与前置条件

- 会话保存在本机唯一数据集：`web/data/user/interview-session.json`；材料列表在 `web/data/user/interview-materials.json`。两者都在被忽略的 `web/data/` 下。
- 开始面试要求个人资料里有实习或项目（`profile_has_internship_or_project`），并要求内嵌 OfferPilot 的 `ai` 配置可用；缺一项分别返回 400 与可读提示，不生成假题目。
- 模型调用只通过内嵌运行时的配置（`web/data/user/offerpilot/config.yaml` 的 `ai` 段）。测试通过替换 `_complete_interview_plan`、`_stream_interview_question`、`_complete_interview_debrief`、`_complete_interview_drill` 隔离，不访问付费接口。
- 提示词文件在 `tools/prompts/`：`interview-plan-system.txt`、`interview-chat-system.txt`、`interview-debrief-system.txt`、`interview-drill-system.txt`。
- 复盘写入 `debriefs` 列表，但不写入定制简历、变体或简历正文；`interview-end` 不会调用 `add-variant`。
- 模型失败不会把半句或占位题目记成完整问题；失败只返回提示，会话保留可重试状态。

## 动作（`POST /api/action`）

| action | 请求 | 返回 |
|---|---|---|
| `interview-start` | `round`（hr/business/tech/manager）、`duration_minutes`（20/30，缺省 30）、可选 `job_id`、`jd`、`material_ids` | 公开会话（`id`、`user_status`、`rules_text`、`remaining_seconds`、`discarded_in_progress` 等），隐藏 `blueprint` 等内部字段 |
| `interview-material-upload` | `kind`（jingyan/knowledge）、`body`（必填）、可选 `title` | `{ok, id, kind, jingyan_is_not_official, materials, message}` |
| `interview-reply` | `answer`（必填）、可选 `session_id` | 公开会话 + `need_next`、`end_available`、`time_up`、`remaining_seconds`、`message` |
| `interview-end` | 可选 `session_id` | `{ok, card, user_status:"debriefed", ...}`；仅 `ready_to_end` 可结束，否则 409 |
| `interview-drill` | `item_id`（必填）、可选 `answer` | `{ok, attempt, gap, prompt, recast?, user_status}`；需已生成复盘 |

错误：参数或状态不符分别返回 400 / 409；模型超时或不可用返回 503，提示文案在 `interview_chat.MSG_*`。空回答不计入 `turns`，半句问题保留 `incomplete` 标记并允许 `retry`。

## 流式出题（`POST /api/interview/stream`）

请求 `{ "intent": "first" | "next" | "retry", "session_id": "iv-..." }`，响应 `text/event-stream`，事件依次为：

- `meta`：`{session_id, move}`
- `token`：`{text}`（逐片）
- `done`：`{text, session_id}`；或
- `error`：`{message}`（半句会保留，可 `retry` 同一问）

校验失败时在发送 200 之前返回普通 JSON 错误（400/409）。SSE 响应设置 `no-store`、`X-Accel-Buffering: no` 并关闭连接。

## 复盘卡约束

`validate_debrief_card` 只在回答原文里找不到证据时把该项分数置空并标注「证据不足」，不因表达流畅补分；理由与建议里会去掉「会被录取 / 通过 / Offer」等结论性措辞，卡片固定带 `not_an_offer` 与 `evidence_note`；重练题最多 3 条。

## 测试

- `tools/tests/test_interview_chat.py`：开始面试、材料上传、通用岗位与选定岗位。
- `tools/tests/test_interview_stream.py`：出题流、追问上限、半句重试、超时与 HTTP SSE。
- `tools/tests/test_interview_debrief.py`：复盘证据校验、结束门禁、重练与不写简历。
- `tools/tests/test_career_agent.py`：项目核验桥接与能力地图路由。

全部测试使用临时数据目录或 mock，不读写真实 `web/data/`，不访问模型与平台。
