# 求职核心流程接口（PIPELINE-API）

这是工作台六段流程及其岗位自动化接口契约。接口服务于本机界面与同一运行环境中的功能模块，不作为公网服务使用。

- 服务地址：`http://127.0.0.1:8766`（仅本机）
- OfferPilot：作为工作台内部能力运行
- 数据模式：只有一个模式 `user`（本机真实数据）。`mode` 参数保留为兼容字段，其他取值一律按 `user` 处理，不报错。
- 传输：工作台同源 JSON；敏感配置只在本机运行时使用
- 版本：`1.0`

## 1. 六段流程

| 顺序 | key | 标题 | 归属 | 本地入口 |
| --- | --- | --- | --- | --- |
| 1 | `intake` | 岗位采集 | 本地工作台 | 岗位池：粘贴 JD / 导入静态 JSON |
| 2 | `screening` | AI 评分与筛选 | 本地规则 + 可选评分 | 岗位池：入队、硬性过滤、文档筛选规则 |
| 3 | `approval` | 人工确认 | 人工 | 审批队列：点击「通过」，发送前另有确认框 |
| 4 | `greeting` | 生成招呼语 | 本地工作台 | 岗位池：生成人工准备清单 |
| 5 | `send` | 发送 | 外部执行流程 / 本人 | 接收发送结果回报 |
| 6 | `monitor` | 监控 HR 回复 | 外部 Agent / 本地邮件解析 | 接收回复结果回报 |

`approved` 表示审批队列中的已确认状态，不等价于已发送或已投递；实际状态以执行结果为准。

## 2. 读取契约与状态

```http
GET /api/pipeline?mode=user
```

响应：

```json
{
  "ok": true,
  "mode": "user",
  "contract": {
    "version": "1.0",
    "flow": ["岗位采集", "AI 评分与筛选", "人工确认", "生成招呼语", "发送", "监控 HR 回复"],
    "stages": [
      {
        "key": "intake",
        "title": "岗位采集",
        "owner": "local",
        "owner_label": "本地工作台",
        "description": "优先读取可用的本机 OfferPilot 岗位池；也保留手动粘贴 JD 或导入静态 JSON。",
        "entry_panel": "jobs",
        "local_actions": ["parse-jd", "import-jobs"],
        "external_event_stage": null
      }
    ],
    "event_endpoint": "POST /api/pipeline/event",
    "event_schema": {
      "type": "object",
      "required": ["stage", "status"],
      "properties": {
        "mode": {"type": "string", "enum": ["user"], "default": "user"},
        "stage": {"type": "string", "enum": ["send", "monitor"]},
        "status": {"type": "string", "enum": ["started", "succeeded", "failed", "skipped"]},
        "job_id": {"type": "string", "description": "本地岗位 id（可选）"},
        "message": {"type": "string", "maxLength": 2000},
        "occurred_at": {"type": "string", "format": "date-time", "maxLength": 64}
      }
    },
    "offerpilot": {
      "base_url": "embedded://offerpilot",
      "agent_api_version": "v1",
      "loopback_only": true,
      "owns_credentials": true,
      "embedded": true,
      "separate_service_required": false,
      "runtime_dir": "web/data/user/offerpilot"
    },
    "guarantees": {
      "auto_submit": false,
      "auto_send": false,
      "platform_scraping": "内嵌 OfferPilot 采集器；仅本机、仅人工确认后投递",
      "external_api_calls": "AI 服务与招聘平台页面由内嵌 OfferPilot 发起；工作台不新增远程服务",
      "loopback_only": true,
      "human_confirmation_before_delivery": true,
      "configured_send_window_required": true,
      "event_is_record_only": true
    },
    "reserved_features": [
      {"key": "mock_interview", "title": "模拟面试", "panel": "interview", "status": "local_partial"},
      {"key": "push", "title": "信息推送", "panel": "push", "status": "dry_run_only"},
      {"key": "resume", "title": "定制简历", "panel": "resume", "status": "local_partial"}
    ],
    "document": "web/PIPELINE-API.md"
  },
  "status": {
    "version": "1.0",
    "flow": ["岗位采集", "AI 评分与筛选", "人工确认", "生成招呼语", "发送", "监控 HR 回复"],
    "stages": [
      {
        "key": "send",
        "title": "发送",
        "owner": "external",
        "owner_label": "外部 Agent",
        "count": 0,
        "unit": "条成功回报",
        "status": "waiting",
        "external": true
      }
    ],
    "external_events": [],
    "external_connected": false
  }
}
```

`status.stages[].status`：

- `ready`：本地能力可用
- `local`：本地能力可用，外部尚未接入
- `waiting`：外部阶段，尚无回报
- `connected`：已收到外部回报，或已连接到岗位自动化能力

`GET /api/state?mode=user` 的 `pipeline` 字段与上面的 `status` 相同，前端直接使用。内嵌后端状态也会出现在 `pipeline.offerpilot`；主工作台岗位 JSON 与 OfferPilot SQLite 岗位池始终分开。

### 2.1 只增字段（岗位、审批队列、发送额度）

以下字段是只读派生值，由 `GET /api/state` 返回，不写入任何本地文件：

- `jobs[].risk`：`{level: "low" | "verify" | "high", signals: [{code, severity, label, evidence}], blocks_queue: bool}`，来自 `tools/job_risk.py`。`level = "high"` 的岗位不能进入审批队列。
- `jobs[]` 另带只读匹配字段：`score_coverage`（0–1 的信息覆盖率，`null` 表示旧评分没有该值）、`mandatory_status`（`none` / `satisfied` / `pending` / `unsatisfied`）、`hiring_status`（`closed` / `not_closed` / `unknown`）、`mandatory_conditions`（`[{condition, status, evidence}]`）。`unsatisfied` 或 `closed` 的岗位移出默认推荐，不能一键入队；`pending`（待确认）不视为不满足。
- `POST /api/action` `parse-jd` 响应的 `job` 对象另带四组只读分析字段（`GET /api/state` 的 `jobs[]` 暂不返回这四组字段；如需展示，由维护者决定是否加入快照）。它们按请求派生，**不写入** `jobs.json`，缺数据时为 `null`，不猜测：
  - `standard`：`{title, location, responsibilities, must_have, nice_to_have, salary_and_start, hiring_status, source_platform, source_updated_at}`。`responsibilities` / `nice_to_have` 只来自 JD 原文分段；`must_have` 优先使用已评分的 `mandatory_conditions`，没有时回退到「任职要求」分段；`source_updated_at` 只取平台给出的时间：显式 `source_updated_at`，否则非岗位自动化导入行的 `posted_at`；岗位自动化导入行（带 `offerpilot_id`）没有平台日期时为 `null`，本地入库时间（`created_at` / `updated_at`）从不冒充来源更新时间。
  - `match`：`{fit_score, fit_confidence, risk_level}`，三者独立，不合并为单一分数。`fit_score` 沿用已有 0–100 匹配分，超出范围视为 `null` 而不换算；`fit_confidence` 为必备条件的证据加权均值（有证据且状态已定 1.0、待确认 0.5、其他状态 0.25、无证据 0），没有必备条件时回退 `score_coverage`；`risk_level`（`low` / `medium` / `high`）只由来源渠道与 `hiring_status` 推出。
  - `dossier`：`{analysis_card, resume_variant, greeting, checklist, recommended_action}`。`resume_variant` 只引用已保存的经历变体 id；`greeting` 优先复用岗位已有草稿，否则由 `tools/greeting.py` 按本地资料生成，含电话、邮箱、微信、QQ 或链接时置 `null`；`recommended_action` 为 `skip` / `hold` / `collect_more` / `generate_greeting` / `review_and_send` 之一。
  - `traceability`：`[{requirement, project_evidence, source}]`，每条必备条件映射到个人资料中共享领域词的项目/经历摘要，找不到时为 `null`；只引用资料原文，不新增事实。
- `queue[].plan`：`{today: bool, rank: int | null, reason: string}`，来自 `tools/quota_planner.py`。只对 `approved` 且尚未发送的行计算。
- `queue[].fit_confidence`：`number | null`，判断置信度（0–1），与 `jobs[].match.fit_confidence` 同一口径，来自 `tools/job_match.py`；队列行找不到对应岗位时为 `null`。队列旧字段 `high_confidence` 只是阈值标记，不参与入队、确认或投递判定，界面不再用它显示「置信」。
- `materials`：岗位定制材料包，来自内嵌运行时已生成的文本，只读返回，不写入 `jobs.json` 或 `approval-queue.json`。`jobs[]` 每条、队列行 `queue[].greeting` 每条与 `get_greetings` 返回值都带该键，没有生成过时为 `null`。形状固定为 `{mapping: [{requirement, evidence, source}], conditions: [{condition, status, evidence}], unknown_fields: [string], resume_suggestions: [{original, suggested, evidence, reason}], greetings: {concise, project, safe}, confirm_items: [string]}`；`status` 只取 `已满足` / `明确不满足` / `待确认`，档案没有的信息写 `未知`，不会标成已满足。`greetings.safe` 同时是该岗位 `greeting` 的默认草稿，`concise` / `project` 对应复核时可选的另外两版，仍走既有的 `greeting_selection`。适配分、判断置信度与风险不在材料包里重算，直接看 `jobs[].match`。生成或校验失败时该岗位保留原 `greeting`，材料包保持 `null`。`resume_suggestions[].original` 与 `suggested` 在返回前统一脱敏：电话、邮箱、微信替换为 `[联系方式已隐藏]`，其余字段原样透传。
- `pipeline.delivery.quota`：`{daily, remaining, planned_today}`。`daily` 为默认每日额度（30），仅用于排序提示；实际上限由内嵌发送器强制。

`POST /api/action` 的 `enqueue` 响应新增以下只增字段：

- `risk_blocked: string[]`：因高风险被拦截的岗位 id（即使带 `allow_low_score` 也会拦截）。
- `city_blocked: {id, reason}[]`：城市不在 `profile.json` 的 `job_intent.cities` 内的岗位，即使手动加入也拦截。`profile.json` 没有目标城市时，回退到 `tools/config.json` 的 `target_cities`。城市为空时放行并不猜测。
- `recent_duplicates: {id, company, title, reason}[]`：与审批队列或已发送记录中、30 天内相同（公司、岗位名、城市指纹一致，规则同 `tools/precheck.py`）的岗位，已跳过。已结束或放弃的记录不计入。

`allow_low_score: true`（手动加入未评分或按规则不推荐的岗位）时必须带 `override_reason`，且取值只能是下拉框的三项之一：`值得沟通，人工判断`、`有内推或熟人渠道`、`公司或岗位我已了解`。缺失或不在列表内返回 400，不改动任何数据。手动加入的队列行会写入 `override_reason` 与 `override_at`。

`POST /api/action` 的 `confirm` 响应同样新增 `recent_duplicates`：批准时若岗位在 30 天内已发送过，该行保持 `pending` 并列在此字段中。

`POST /api/action` 的 `delete-jobs`（body：`{ids: string[], mode}`，一次最多 100 条）对岗位池做软删除：仅标记 `deleted_at`，不物理删除记录，便于指纹去重防止重新导入复活；已 `approved` 或已出现在发送记录中的岗位会被跳过并在 `skipped: [{id, reason}]` 中列出原因，响应为 `{deleted: number, skipped: [...], message}`。

## 3.1 岗位自动化接口

```http
GET /api/offerpilot/state
GET /api/offerpilot/jobs
POST /api/offerpilot/tasks
POST /api/offerpilot/tasks/<task_id>/stop
```

网页「岗位池 → 岗位自动化」面板已接入这些接口：连接状态、能力与偏好快照、当前/最近任务、任务启动与停止、岗位表。启动请求必须明确确认并确认相关风险；读取始终来自本机内嵌运行时，不区分数据模式。

`/api/offerpilot/jobs` 是只读快照，不导入主工作台数据。启动任务请求必须同时带上 `confirm: true` 与 `risk_acknowledged: true`，并且 `mode` 只能是 `collect`、`monitor` 或 `full`：

```json
{"mode":"collect","confirm":true,"risk_acknowledged":true}
```

工作台不开放不受约束的任意任务入口；任务能力、发送配置和确认流程由当前功能实现及用户配置决定。`/api/offerpilot/jobs` 只返回界面所需字段，不返回敏感配置或凭据；自多平台采集起新增只读 `source_platform`（`boss` / `zhilian` / `51job` / `liepin`），导入岗位池时同时写入 `source_platform` 与对应的 `source_channel`。

匹配评分由程序按六个扁平维度、固定权重计算，模型只输出每个维度的系数（1.00 / 0.75 / 0.50 / 0.25 / 0.00 / 未知）和证据：核心职责匹配 30（行业与业务场景证据并入这一项）、项目/成果证据 25、技能与工具匹配 15、职级与工作复杂度 10、地点与工作安排 10、薪资与其他偏好 10。已知项匹配分 = Σ（权重 × 系数）÷ 可判断维度权重之和 × 100，结果四舍五入（恰为 .5 时向上取整）；信息覆盖率 = 可判断维度权重之和 ÷ 100。JD 明确必备条件若为「明确不满足」，或岗位已关闭 / 确认失效，则不进入推荐，也不能自动入队，只能手动加入并填写原因；「待确认」不作为不满足处理。文档没有定义数字通过线，因此入队不再比较分数：只要岗位已按文档评分（信息覆盖率大于 0）、不存在明确不满足的必备条件且未关闭，就进入审批队列。新写入的评分说明（trace）为 schema 4，`components` 直接包含六个维度；schema 3（旧四维加求职偏好三项）、schema 1 / 2 仍按原结构读取。

`full` 任务在运行时会完成采集与评分，然后由工作台自动导入岗位池、把符合文档筛选规则的岗位加入审批队列（城市、30 天重复、高风险、明确不满足的必备条件与已关闭岗位照旧拦截），并为已通过岗位生成招呼语，停在最终确认门。`GET /api/offerpilot/state` 新增只增字段 `pipeline`：`approved_count`、`awaiting_confirmation`、`auto_submit`，以及最近一次自动流程的导入/入队/招呼语摘要。自动流程也可通过统一动作入口重试（幂等：重复导入按指纹跳过，已入队与已生成招呼语的岗位不会重复处理）：

```json
POST /api/action
{"action":"offerpilot-automate","mode":"user","data_mode":"user","task_id":"<task-id>","ids":["<runtime-job-id>"]}
```

该动作只导入、入队和生成招呼语，不发送；发送仍需 `offerpilot-deliver` 的确认语与风险勾选。

### 3.1.1 HR 会话（只读列表 + 单条确认回复）

```http
GET /api/offerpilot/conversations?mode=user&platform=boss
GET /api/offerpilot/conversation?mode=user&platform=boss&id=<conversation-id>
POST /api/action
{"action":"offerpilot-reply","mode":"user","id":"<conversation-id>","text":"<回复>","confirm":"确认发送这条回复","risk_acknowledged":true}
```

`platform` 可选 `boss`、`zhilian`、`51job`、`liepin`、`all`，默认 `boss`（保持旧调用语义）；其他值返回 400。工作台 HR 回复页使用 `platform=all` 聚合四个平台，每个平台单独读取、单独失败。

- `GET /api/offerpilot/conversations` 打开对应平台的聊天列表并解析；为刷新本机缓存，会为签名变化或尚无正文的会话打开会话页（每次最多 5 条，只读），从不写入平台。返回 `{ok, available, platform, conversations, count}`；每条会话含 `id`（不可逆哈希，不含姓名）、`platform`、`company`、`title`、`hr_name`、`hr_title`、`last_message`、`last_message_at`、`unread`、`job_id`。`job_id` 用公司与 HR 名匹配主工作台岗位池，未命中为 `null`。
- `platform=all` 时另外返回 `platforms: [{platform, label, ok, available, count, error?}]` 与可选的 `errors: {platform: reason}`：某个平台未登录或页面不可读只让该平台为空并记录原因，其他平台照常返回；全部失败时 `available: false` 并在 `error` 汇总原因。会话按 `boss → zhilian → 51job → liepin` 顺序拼接，数目取并集。
- BOSS 复用监测模块的会话列表解析；智联读取 `i.zhaopin.com/im` 的会话 DOM；猎聘先打开 `www.liepin.com/zhaopin/` 搜索页（不带 query 参数），「我的沟通」抽屉（`#im-basic-contact`）若已默认展开则直接读取，未展开时才点击入口，再读取联系人（旧的 `c.liepin.com` 入口只显示首页，脚本保留但不再使用）；猎聘列表结果另带只读诊断字段 `drawer_branch`（`expanded` 抽屉已展开 / `clicked_entry` 点击了已知入口 / `clicked_text_entry` 点击了文字入口 / `null` 未找到入口）与 `matched`（会话行选择器命中的节点数），用于区分「页面确实没有会话」（`count = 0` 且 `matched = 0`）与「选择器没匹配」；前程无忧没有站内聊天，HR 沟通通过微信扫码完成（已人工验证，之后不再验证）；`51job` 会话接口固定返回 `available: false` 与「前程无忧没有站内聊天，HR 沟通通过微信扫码完成，工作台不读取其消息」，不打开 `chat.51job.com`，不猜测数据。
- `GET /api/offerpilot/conversation` 打开列表中的一条会话并按顺序读取消息，返回 `{ok, available, platform, conversation_id, company, title, messages: [{sender, text, platform}], stale, reply_allowed, reply_block_reason}`（读取失败但有旧正文时 `ok: false`、`stale: true`，并带脱敏后的 `error`）；`sender` 为 `hr` / `me` / `system`，单条文本截断到 500 字。`platform=all` 时按最近一次聚合列表中的平台打开该会话。非 BOSS 平台一律 `reply_allowed: false`。
- 工作台 HR 页按后端返回的 `reply_allowed` 控制回复入口：`reply_allowed: true` 时启用输入框与「发送」，点「发送」只打开确认框，点「确认发送这条回复」后才调用 `offerpilot-reply`；`reply_allowed: false` 时输入框与「发送」禁用，并显示后端返回的 `reply_block_reason`。界面不硬编码哪些平台可以回复。
- `offerpilot-reply` 只发送一条 BOSS 文本；非 BOSS 会话会被拒绝。依次校验：`mode=user`、文本非空且不超过 1000 字、`confirm` 精确等于「确认发送这条回复」、`risk_acknowledged` 为 `true`、处于 09:00–16:00 发送窗口、没有停止请求、没有监测或平台风险锁、`id` 出现在最近 10 分钟的会话列表内。全部通过后才复用监测模块的会话打开与输入框发送逻辑发送一次。
- 会话正文脱敏后写入本机 `web/data/<mode>/hr/conversations.json`（user 为 `web/data/user/hr/`，demo 为 `web/data/demo/hr/`，都在 gitignore 的 `web/data/` 下，不提交）；列表每次刷新，未变会话不重开。写入前统一脱敏，电话、邮箱、微信替换为 `[联系方式已隐藏]` 后才落盘；写入用同目录临时文件加 `os.replace` 原子替换，失败时保留上一版文件。列表刷新只替换该平台自己的记录，其他平台的文件内容不动；签名（`last_message_at` 与正文前 80 字的哈希）未变且已有正文的会话不再打开会话页，签名变化或尚无正文的会话才打开，每次刷新最多补读 5 条，新消息按 `(sender, text, time)` 计数去重合并、旧消息保留。读取失败保留旧正文并把该条标为 `stale`、记录脱敏后的原因，不清空；`stale` 正文只在单条会话里带 `stale: true` 返回，下次打开会重试平台。落盘只是缓存，不作为发送依据：`offerpilot-reply` 仍只接受最近 10 分钟内存会话列表里的 `id`，`reply_allowed` 也不会因落盘而放行。活动日志只记录动作「发送 HR 回复」与公司名，不记录正文或 HR 姓名。只读读取不截图、不点击「发送」或「回复」，返回结构不含电话、邮箱、微信。
- 只读路径不调用自动回复、跟进或简历投递流程；`auto_reply_hr_questions` 保持关闭。

### 3.1.2 岗位招呼语草稿（本地文本，只写 `greeting`）

```http
POST /api/action
{"action":"generate-job-greetings","mode":"user","ids":["<job-id>"]}
```

`ids` 可省略（默认处理全部 `status = "ready"` 且 `greeting` 为空的岗位），给出时只处理这些岗位。动作复用 `tools/greeting.py`，只用 `profile.json`（或本机 `workspace/resume.md`）与结构化 JD 字段中的专业事实生成不超过 150 字的草稿；不调用模型或 HTTP 接口、不打开浏览器、不发送任何消息。只写岗位记录的 `greeting` 字段（已有草稿跳过），不改其他字段，也不写 `approval-queue.json`；草稿若含电话、邮箱、微信或链接则跳过并列入 `skipped`。返回 `{ok, generated, skipped: [{id, reason}], message}`。

## 3. 回报流程事件

```http
POST /api/pipeline/event
Content-Type: application/json
```

请求体：

```json
{
  "mode": "user",
  "stage": "send",
  "status": "succeeded",
  "job_id": "jd-1a2b3c4d5e",
  "message": "已在平台完成人工发送",
  "occurred_at": "2026-11-14T10:30:00+08:00"
}
```

字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `mode` | 否 | 兼容字段；只有 `user`，其他取值按 `user` 处理 |
| `stage` | 是 | 只接受 `send` 或 `monitor` |
| `status` | 是 | `started` / `succeeded` / `failed` / `skipped` |
| `job_id` | 否 | 本地岗位 id，最长按安全 id 规则截断 |
| `message` | 否 | 简短说明，最多 2000 字符 |
| `occurred_at` | 否 | ISO 8601 时间，最长 64 字符 |

响应：

```json
{
  "ok": true,
  "event": {
    "received_at": "2026-11-14T10:31:02+08:00",
    "stage": "send",
    "status": "succeeded",
    "job_id": "jd-1a2b3c4d5e",
    "message": "已在平台完成人工发送",
    "occurred_at": "2026-11-14T10:30:00+08:00",
    "actor": "external_agent",
    "auto_submit": false
  },
  "message": "已记录外部 Agent 回报；没有触发发送、投递或平台请求"
}
```

错误：非 `send` / `monitor` 阶段或未知状态返回 `400`。

也可使用统一动作入口：

```json
POST /api/action
{"action": "pipeline-event", "mode": "user", "stage": "monitor", "status": "succeeded"}
```

## 4. 边界

- 事件只追加到 `web/data/user/pipeline-events.jsonl`，不改变岗位状态、不写审批队列、不触发超出当前任务的操作。
- 不接收敏感配置或凭据；本机运行时按用户配置读取所需会话和服务设置。
- 不接受任意 URL、脚本、HTML 或可执行内容；`message` 按纯文本保存与展示。
- 服务只绑定 `127.0.0.1`，校验 `Host` 与 `Origin` 均为本机。

## 5. 预留功能

模拟面试、信息推送、定制简历已在左侧面板预留位置，并复用本地题库、dry-run 载荷、经历变体与 ATS 预检。它们不属于六段核心流程，接入时请另开契约，不要复用 `send` / `monitor` 事件。
