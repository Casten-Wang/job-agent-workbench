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
      "configured_send_window_required": false,
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
- `GET /api/state` 的 `jobs[]` 与 `POST /api/action` `parse-jd` 响应的 `job` 对象都带四组只读分析字段（快照里是只增字段，详情与核对面板读取它们）。它们按请求派生，**不写入** `jobs.json`，缺数据时为 `null`，不猜测；快照只用本机已有数据（个人资料、简历文本、已保存的经历变体），不触发任何外部请求：
  - `standard`：`{title, location, responsibilities, must_have, nice_to_have, salary_and_start, hiring_status, source_platform, source_updated_at}`。`responsibilities` / `nice_to_have` 只来自 JD 原文分段；`must_have` 优先使用已评分的 `mandatory_conditions`，没有时回退到「任职要求」分段；`source_updated_at` 只取平台给出的时间：显式 `source_updated_at`，否则非岗位自动化导入行的 `posted_at`；岗位自动化导入行（带 `offerpilot_id`）没有平台日期时为 `null`，本地入库时间（`created_at` / `updated_at`）从不冒充来源更新时间。
  - `match`：`{fit_score, fit_confidence, risk_level}`，三者独立，不合并为单一分数。`fit_score` 沿用已有 0–100 匹配分，超出范围视为 `null` 而不换算；`fit_confidence` 为必备条件的证据加权均值（有证据且状态已定 1.0、待确认 0.5、其他状态 0.25、无证据 0），没有必备条件时回退 `score_coverage`；`risk_level`（`low` / `medium` / `high`）只由来源渠道与 `hiring_status` 推出。
  - `dossier`：`{analysis_card, resume_variant, greeting, checklist, recommended_action}`。`resume_variant` 只引用已保存的经历变体 id；`greeting` 优先复用岗位已有草稿，否则由 `tools/greeting.py` 按本地资料生成，含电话、邮箱、微信、QQ 或链接时置 `null`；`recommended_action` 为 `skip` / `hold` / `collect_more` / `generate_greeting` / `review_and_send` 之一。
  - `traceability`：`[{requirement, project_evidence, source}]`，每条必备条件映射到个人资料中共享领域词的项目/经历摘要，找不到时为 `null`；只引用资料原文，不新增事实。
- `queue[].plan`：`{today: bool, rank: int | null, reason: string}`，来自 `tools/quota_planner.py`。只对 `approved` 且尚未发送的行计算。
- `queue[].fit_confidence`：`number | null`，判断置信度（0–1），与 `jobs[].match.fit_confidence` 同一口径，来自 `tools/job_match.py`；队列行找不到对应岗位时为 `null`。队列旧字段 `high_confidence` 只是阈值标记，不参与入队、确认或投递判定，界面不再用它显示「置信」。
- `materials`：岗位定制材料包，来自内嵌运行时已生成的文本，只读返回，不写入 `jobs.json` 或 `approval-queue.json`。`jobs[]` 每条、队列行 `queue[].greeting` 每条与 `get_greetings` 返回值都带该键，没有生成过时为 `null`。形状固定为 `{mapping: [{requirement, evidence, source}], conditions: [{condition, status, evidence}], unknown_fields: [string], resume_suggestions: [{original, suggested, evidence, reason}], greetings: {concise, project, safe}, confirm_items: [string]}`；`status` 只取 `已满足` / `明确不满足` / `待确认`，档案没有的信息写 `未知`，不会标成已满足。`greetings.safe` 同时是该岗位 `greeting` 的默认草稿，`concise` / `project` 对应复核时可选的另外两版，仍走既有的 `greeting_selection`。适配分、判断置信度与风险不在材料包里重算，直接看 `jobs[].match`。生成或校验失败时该岗位保留原 `greeting`，材料包保持 `null`。
- 材料 JSON 或字段校验失败时，按原有事实与格式规则最多纠正一次；不放宽原文引用、数字依据或联系方式校验。诊断只记录字段路径和固定原因，不记录被拒绝的模型原文。招呼语任务的 `metrics.greet_materials_failed` 表示材料失败数；零产出且存在生成失败时，任务为 `failed` 并在 `error` 中说明原因；部分生成或保留成功时保留已有内容，并在 `stop_reason` 中说明未完成的部分。
- `pipeline.delivery.quota`：`{daily, remaining, planned_today}`。`daily` 为默认每日额度（30），仅用于排序提示；实际上限由内嵌发送器强制。

`POST /api/action` 的 `enqueue` 响应新增以下只增字段：

- `risk_blocked: string[]`：因高风险被拦截的岗位 id（即使带 `allow_low_score` 也会拦截）。
- `city_blocked: {id, reason}[]`：城市不在 `profile.json` 的 `job_intent.cities` 内的岗位，即使手动加入也拦截。`profile.json` 没有目标城市时，回退到 `tools/config.json` 的 `target_cities`。城市为空时放行并不猜测。
- `recent_duplicates: {id, company, title, reason}[]`：与审批队列或已发送记录中、30 天内相同（公司、岗位名、城市指纹一致，规则同 `tools/precheck.py`）的岗位，已跳过。已结束或放弃的记录不计入。

`allow_low_score: true`（手动加入未评分或按规则不推荐的岗位）时必须带 `override_reason`，且取值只能是下拉框的三项之一：`值得沟通，人工判断`、`有内推或熟人渠道`、`公司或岗位我已了解`。缺失或不在列表内返回 400，不改动任何数据。手动加入的队列行会写入 `override_reason` 与 `override_at`。

`POST /api/action` 的 `confirm` 响应同样新增 `recent_duplicates`：批准时若岗位在 30 天内已发送过，该行保持 `pending` 并列在此字段中。

`POST /api/action` 的 `delete-jobs`（body：`{ids: string[], mode}`，一次最多 100 条）对岗位池做软删除：仅标记 `deleted_at`，不物理删除记录，便于指纹去重防止重新导入复活；已 `approved` 或已出现在发送记录中的岗位会被跳过并在 `skipped: [{id, reason}]` 中列出原因；只增参数 `include_approved: true`（工作台「已通过」页的「删除所选」使用）允许删除 `approved` / `pending` 的岗位并同时移出审批队列，已有发送记录的岗位仍然受保护，响应为 `{deleted: number, skipped: [...], message}`。

### 2.2 定制简历：经历变体与主稿对比（只读）

```http
POST /api/action
{"action":"compare-variant","mode":"user","variant_id":"<variant-id>"}
```

把一条已保存的经历变体与主稿按段落对比，返回新增、删除与改写的段落原文。动作只读：不写入 `variants.json`、活动日志或任何文件，不修改主稿，不发送、不投递，也不生成或改写任何文字。

请求字段（均可省略，但至少要能定位一条变体，或提供 `text`）：

- `variant_id`：按记录 id 定位，最长 200 字。
- `job_id`：按岗位关联定位；同一岗位有多条时取 `created_at` 最新的一条。
- `project`：按项目名定位（忽略大小写、全半角与空白差异），同样取最新一条。
- `text`：行内经历原文，最长 20,000 字。提供时以它作为对比文本（即使同时命中某条记录）；没有命中记录但有 `text` 时，直接对比这段文本。
- `master_text`：可选的母版原文，最长 200,000 字，用于调用方自带主稿。
- 定位优先级为 `variant_id` → `job_id` → `project`。

主稿来源：提供 `master_text` 时返回 `master_source: "请求提供"`；否则读取本机 `workspace/resume.md`（`master_source: "workspace/resume.md"`），不存在时回退到采集页已上传的 Markdown 简历（`master_source: "采集页已上传的 Markdown 简历"`）。没有可读主稿返回 404「未找到可对比的母版简历：workspace/resume.md 不存在，也没有已上传的 Markdown 简历」；主稿存在但无法按 UTF-8 文本读取返回 400。既没有命中变体也没有 `text` 时返回 404「未找到可对比的经历变体：请提供 variant_id、job_id，或 project 与 text」。

响应为 `{ok, variant_id, project, job_id, master_source, identical, summary, segments}`：

- `summary`：`{added, removed, changed, unchanged}`，单位为段落数。
- `segments`：只列差异，按文档顺序。新增为 `{kind: "added", text}`，删除为 `{kind: "removed", text}`，改写为 `{kind: "changed", before, after}`。所有字符串都取自两条输入的原文，不改写、不润色。
- 段落按空行切分；比较时忽略空白与全半角差异，但输出仍是原文。两段文本逐段一致时 `identical: true` 且 `segments` 为空数组。

该动作不在六段流程中产生事件，也不代表任何投递或发送状态；定制简历页的「与主稿对比」入口只展示上述返回值。

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

只增字段 `min_score`（0–100 的数字，缺省不设合格线）：`offerpilot-automate` 与 `enqueue` 都接受它。评分低于合格线的岗位不会自动入队，响应新增 `below_min_score: [{id, score, reason}]` 与回显的 `min_score`；它们仍可带 `allow_low_score` 与原因手动加入。非法值返回 400。工作台采集页的「合格线」默认 60，记在本机浏览器里，只有「采集 + 打分 + 筛选」才会带上它。

完整流程不再限定 Boss直聘：所选平台只需支持采集、评分与招呼语（Boss直聘、智联招聘、前程无忧、猎聘都满足），预检的浏览器检查也按所选平台进行。`offerpilot-deliver` 对来自智联、前程无忧、猎聘的岗位一律返回 409（这些平台暂不支持在工作台发送），不会创建发送批次。

### 3.1.1 HR 会话（只读列表 + 单条确认回复）

```http
GET  /api/offerpilot/conversations?mode=user&platform=all
GET  /api/offerpilot/conversations/summary?mode=user
POST /api/offerpilot/conversations/sync
{"platform":"all"}
GET  /api/offerpilot/conversation?mode=user&platform=boss&id=<conversation-id>
POST /api/action
{"action":"offerpilot-reply","mode":"user","id":"<conversation-id>","text":"<回复>","confirm":"确认发送这条回复","risk_acknowledged":true}
```

`platform` 可选 `boss`、`zhilian`、`51job`、`liepin`、`all`，默认 `boss`（保持旧调用语义）；其他值返回 400。工作台 HR 回复页使用 `platform=all`。

- `GET /api/offerpilot/conversations` **只读本机存储**，不打开页面、不请求平台，立即返回 `{ok, available, platform, conversations, count, syncing, syncing_platform, last_synced_at}`；页面先显示已有内容，再由 `POST /api/offerpilot/conversations/sync` 在后台增量刷新。每条会话统一为 `{id, platform, company, title, hr_name, hr_title, last_message, last_message_at, unread, unread_count, last_direction, has_reply, job_id, source, has_body, stale}`：`id` 为不可逆哈希（不含姓名）；`unread` 保持布尔兼容，`unread_count` 为未读条数（DOM 只知有未读时记 1）；`source` 为 `api` / `dom`；`has_body` 表示本地已有正文或已确认空会话。`job_id` 用公司与 HR 名匹配主工作台岗位池，未命中为 `null`。
- `GET /api/offerpilot/conversations/summary` 同样只读本地存储，供首页与导航红点轮询：`{ok, total, unread_total, by_platform: {boss: {count, unread, source, last_synced_at, error?}, zhilian: {...}, liepin: {...}}, last_synced_at, syncing}`。
- `POST /api/offerpilot/conversations/sync` 只读同步：body `{platform: "all"|"boss"|"zhilian"|"liepin"}`，立刻返回 `202 {ok, started, syncing, platform, queued, skipped?, reason?}`。每个平台一个后台工作线程，**跨平台并行、同一平台串行**（同一平台排队/执行期间不重复入队），各平台频率限制按自身计算；`all` 同时启动 BOSS、智联、猎聘，前程无忧没有站内聊天故不排队。刚成功同步过的平台（30 秒内，`HR_SYNC_MIN_INTERVAL_SECONDS`）直接跳过，返回 `skipped: ["..."]` 与 `reason: "刚刚同步过，请稍后再刷新"`，不打开页面、不请求平台；上次同步失败的平台不受冷却限制，会立即重试。每个平台结束后把 `last_synced_at`、`source` 或脱敏后的 `error` 写入本机 `web/data/<mode>/hr/sync.json`，摘要据此显示；同步期间摘要 `syncing` 为 true。同步不发送、不回复、不点击「发送」。
- 增量读取顺序：先写列表元信息，再补正文。打开 HR 页时 `GET conversations` 立即返回旧缓存（列表旧正文照常显示），随后 `POST sync` 才在后台更新；首次冷启动不会等正文读完才出列表。
- 统一读取层（每平台一个 reader，结果形状一致）：
  - BOSS 优先在用户已打开的聊天标签页里用同源 `fetch` 读取列表 `GET /wapi/zprelation/friend/getGeekFriendList.json?page=1` 与正文 `GET /wapi/zpchat/geek/historyMsg?...`（只这两个固定相对路径，会话标识由列表响应提供并经 `encodeURIComponent`；`credentials:'include'`，不读取、不返回、不记录 cookie/token/请求头）。已有聊天标签页直接复用且永不关闭；没有时才后台新建，读完只关闭自己新建的。接口失败（HTTP 非 200、`code != 0`、字段缺失）回退到同一标签页的会话 DOM，结果标 `source: "dom"`；接口成功标 `source: "api"`。加密会话标识只存在进程内存，不返回、不落盘。
  - 智联优先在已登录的 `i.zhaopin.com/im` 页内同源 `GET https://cgate.zhaopin.com/imapi/imV2/getTalkList?pageNo=1&pageSize=50` 读取会话列表（`data[].staffName/companyName/jobTitle/unreadCount/text/sendTime/peerPartnerId`），成功标 `source: "api"`；`lastSentence` 以「我：」/「我:」开头时最后一条判为我方（`last_direction: "me"`），否则为对方。历史消息没有 HTTP 接口，改调页面自身的 NIM SDK `window.imEngine.instance.getHistoryMsgs({scene:'p2p', to, limit:100, asc:false})`，发送者按 `flow`（`out`=我，`in`=对方），自定义卡片只取 `fallbackText` / `lastMessage` 文本，消息 id 用 `idServer`。不调用 `clearUnread` / `markSessionAck` / `sendMsgReceipt`。
  - 猎聘复用用户已打开的猎聘标签页（没有时才后台新建），打开 `www.liepin.com/zhaopin/` 搜索页（不带 query 参数），「我的沟通」抽屉（`#im-basic-contact`）若已默认展开则直接读取，未展开时才点击入口。2026-11 的 www 版本没有抽屉 store，联系人数据与聊天读取函数都在 React 组件 props 里，且节点键是 `__reactInternalInstance$…`（其值是 fiber），不是 `__reactFiber$…`；读取同时兼容两种键。会话列表优先读页面已加载的 contact 对象（字段与 `contact.get-contact-list` 响应一致：`name/company/title/unReadCnt/oppositeImId/latestMsgTime/direction/lastPayload`），旧版本若暴露带 `getContactList` 与 `options.imId` 的 store 则改用该 store 方法；直接手拼 `contact.get-contact-list` 表单请求经真实页面探测返回非成功 `flag`（缺页面请求拦截器补的 `imId`），因此不再使用，也不读取 storage/cookie。方向 `"0"`=我方、`"1"`=对方；`oppositeImId` 只存进程内存供历史读取，不返回、不落盘。历史消息调用页面传给聊天面板的只读 `getChatList('', oppositeImId, false)`（内部即 `chat.chat-list`），旧版本回退到 store 的同名方法，消息 id 用 `msgId`；不调用 `openChat` / `refreshChat`、不调用 `readed-msg`、不点击联系人行。接口成功标 `source: "api"`（结果另带 `via: "props"|"store"`），回退 DOM 时标 `source: "dom"`，并带只读诊断字段 `drawer_branch`、`matched`、`drawer_found`、`wrap_count`、`fallback_matched`、`selector_mismatch`：`matched=0` 且 `fallback_matched>0` 表示行选择器失配，两者都为 0 表示抽屉里确实没有会话。
  - 两个平台的接口不可用（NIM 未就绪、抽屉 store 未找到、HTTP 失败）时都回退到同一标签页或后台标签页的 DOM 读取，结果标 `source: "dom"`。前程无忧没有站内聊天，HR 沟通通过微信扫码完成；`51job` 会话接口固定返回 `available: false` 与「前程无忧没有站内聊天，HR 沟通通过微信扫码完成，工作台不读取其消息」。
  - 全程不抢前台焦点：读取路径只以后台方式建页（`background=True`），发送回复是用户主动动作，仍可在前台完成。后台增量刷新只读列表接口，接口不可用时返回 `available: false` 与「接口暂不可用，打开该会话时再读取」，**不会为了正文在后台打开会话页**；DOM 回退只在用户点开单条会话时允许一次。平台返回登录失效、验证码或频繁限制时抛风控停止，不重试、不反复回退 DOM。
- `GET /api/offerpilot/conversation` 另接受只增参数 `force=1`：跳过本地已存正文、强制打开一次重读（界面的「刷新这个会话」使用）。智联、猎聘读不到正文（空）而列表里有最新一条时，响应的 `messages` 带一条 `preview: true` 的摘要消息并附 `preview_only: true`，不会写入存储；本地存下的「空正文」在 5 分钟后下次点开时会重试一次。Boss直聘走接口，空历史仍返回空。`GET /api/offerpilot/conversation` 打开列表中的一条会话并按顺序读取消息，返回 `{ok, available, platform, conversation_id, company, title, messages: [{sender, text, time, mid?, platform}], stale, reply_allowed, reply_block_reason}`（读取失败但有旧正文时 `ok: false`、`stale: true`，并带脱敏后的 `error`）；`sender` 为 `hr` / `me` / `system`，单条文本截断到 500 字；`mid` 仅在平台提供消息 id 时出现。先查本地缓存：已存正文的签名与当前列表签名一致且未标 `stale` 时直接返回、不打开页面；否则打开一次（用户主动打开时才允许 DOM 回退），只把比本地最大 `mid` 更新的消息追加进去，旧消息保留，随后把正文签名更新为当前列表签名。`platform=all` 时按本地记录的平台打开该会话。BOSS、智联、猎聘在通过停止状态、风险锁检查后给出 `reply_allowed: true`（智联还要求内存里有该会话的接口 id，否则 `reply_block_reason` 提示「请先刷新会话列表，再回复该会话」）；前程无忧与 DOM 回退/摘要消息读到的会话一律 `false`。
- 工作台 HR 页按后端返回的 `reply_allowed` 控制回复入口：`reply_allowed: true` 时启用输入框与「发送」，点「发送」只打开确认框，点「确认发送这条回复」后才调用 `offerpilot-reply`；`reply_allowed: false` 时输入框与「发送」禁用，并显示后端返回的 `reply_block_reason`。界面不硬编码哪些平台可以回复。
- `offerpilot-reply` 只发送一条文本，支持 BOSS、智联、猎聘（前程无忧会话被拒绝）。BOSS 复用监测模块的会话打开与输入框发送；智联在用户已打开的 `i.zhaopin.com/im` 页面里用页面自带 NIM 的 `sendText` 发给列表接口带来的对端 id（id 只留内存）；猎聘在聊天抽屉里点开唯一匹配的联系人，在随后弹出的独立聊天窗口里确认对方姓名、写入输入框并点发送，以输入框被清空或页面历史里出现这句话作为平台确认，否则按「发送未被平台确认」报错。智联、猎聘已于 2026-11-18 在真实账号上各发过一条并在对话里核对到。依次校验：`mode=user`、文本非空且不超过 1000 字、`confirm` 精确等于「确认发送这条回复」、`risk_acknowledged` 为 `true`、没有停止请求、没有监测或平台风险锁、`id` 出现在最近 10 分钟的会话列表内。全部通过后才发送一次。
- **简历请求卡片**（只增字段与动作）：HR 在会话里发来「想要一份你的简历，你是否同意？」这类卡片时，`GET /api/offerpilot/conversation` 的对应消息带 `card: {kind: "resume_request", attach: boolean, pending: boolean}`，并显示卡片上的真实文字（不再是「卡片消息，工作台不支持预览」）。`card` 只在读取时由消息文本推出，不落盘；`pending` 只有最新一条未被我方回应的请求为 `true`；`attach: true` 表示对方要的是「附件简历」，需要在平台里上传文件，工作台不自动处理，界面只提示不给按钮。
- `offerpilot-resume-request`：`{"action":"offerpilot-resume-request","mode":"user","id":"<conversation-id>","choice":"agree"|"refuse","confirm":"确认同意发送简历"|"确认拒绝发送简历","risk_acknowledged":true}`。本质是在平台页面里点卡片上的「同意 / 拒绝」按钮，由平台把你已在该平台提交过的在线简历发给 HR，工作台不拼装、不上传任何简历文件。校验与 `offerpilot-reply` 相同（停止状态、风险锁、无后台任务、`id` 在最近 10 分钟的会话列表内）。点击后必须看到平台响应才报成功，否则返回 400 并提示去平台核实，避免重复点击。智联已在真实账号上验证过「同意」（平台记录「在线简历已发送」）；BOSS 与猎聘按页面卡片按钮的通用点击实现，**尚未在真实卡片上验证**。活动日志只记「同意/拒绝发送简历」与公司名。
- 会话正文脱敏后写入本机 `web/data/<mode>/hr/conversations.json`（`user` 为 `web/data/user/hr/`，在 gitignore 的 `web/data/` 下，不提交）。写入前统一脱敏，电话、邮箱、微信替换为 `[联系方式已隐藏]` 后才落盘；写入用同目录临时文件加 `os.replace` 原子替换，失败时保留上一版文件。列表刷新只替换该平台自己的记录，其他平台的文件内容不动。刷新时先整批写入该平台最新列表元信息（正文仍是旧值），再决定补读：接口来源只补读「列表签名变化且有未读 / 最后一条不是我方」的会话，每次最多 30 条，且只走接口（`allow_dom=False`），不会为正文在后台打开会话页；DOM 列表来源只为最多 3 条未读会话预读，其余会话等用户点开时懒加载。签名（`last_message_at` 与正文前 80 字的哈希）未变且已有正文或已确认空的会话不再读取；已存正文另有 `body_signature` 记录它对应的列表签名，与当前签名不一致时在列表标 `stale: true`（正文保留），点开后只追加新消息。正文读取共用列表的同一次总时限（60 秒），超时即停。新消息优先按平台 `mid` 去重（只接收大于已存最大 `mid` 的消息），没有 `mid` 时按 `(sender, text, time)` 计数合并、旧消息保留；读取成功但消息为空的会话写入 `body_read: true`，下次不再重读。读取失败保留旧正文并把该条标为 `stale`、记录脱敏后的原因，不清空；`stale` 在列表与单条会话里都如实返回，下次打开会重试平台。落盘只是缓存，不作为发送依据：`offerpilot-reply` 仍只接受最近 10 分钟内存会话列表里的 `id`，`reply_allowed` 也不会因落盘而放行。活动日志只记录动作「发送 HR 回复」与公司名，不记录正文或 HR 姓名。只读读取不截图、不点击「发送」或「回复」，返回结构不含电话、邮箱、微信。
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

「05 定制简历」支持确认项目材料后直接生成与保存版本，不要求面试；「06 模拟面试」既有 API 和历史会话保留；不影响六段投递流程。

个人项目链路现在通过独立 `/api/career-user/...` 接入 GitHub 授权、核验、简历版本和正式面试，使用 user 引擎与独立数据库。该链路不写入 send/monitor，详见 [PERSONAL-CAREER-API](PERSONAL-CAREER-API.md)。

模拟面试、信息推送、定制简历已在左侧面板预留位置，并复用本地题库、dry-run 载荷、经历变体与 ATS 预检。它们不属于六段核心流程，接入时请另开契约，不要复用 `send` / `monitor` 事件。

全局 Agent 工作台使用独立 `/api/workbench-agent/...` 会话与事件，不复用六段投递事件。岗位推荐不改变审批状态，生成的招呼语不自动同步到发送器；用户仍通过原发送复核执行外部动作。`/api/state` 字段保持兼容，详见 [WORKBENCH-AGENT-API](WORKBENCH-AGENT-API.md)。

2026-11-16：定制简历与模拟面试页面新增公开项目核验，使用独立同源路由接入 Python 服务。该接口不改动六段状态、审批或发送记录；接口见 [CAREER-AGENT-API](CAREER-AGENT-API.md)。原有题单与逐字稿工具继续保留，正式简历面试仍待简历版本链路完成。
