# 求职核心流程接口（PIPELINE-API）

这是工作台六段流程及其岗位自动化接口契约。接口服务于本机界面与同一运行环境中的功能模块，不作为公网服务使用。

- 服务地址：`http://127.0.0.1:8766`（仅本机）
- OfferPilot：作为工作台内部能力运行
- 数据模式：`demo`（虚构演示，只读）或 `user`（本机真实数据）
- 传输：工作台同源 JSON；敏感配置只在本机运行时使用
- 版本：`1.0`

## 1. 六段流程

| 顺序 | key | 标题 | 归属 | 本地入口 |
| --- | --- | --- | --- | --- |
| 1 | `intake` | 岗位采集 | 本地工作台 | 岗位池：粘贴 JD / 导入静态 JSON |
| 2 | `screening` | AI 评分与筛选 | 本地规则 + 可选评分 | 岗位池：入队、硬性过滤、评分门 |
| 3 | `approval` | 人工确认 | 人工 | 审批队列：精确确认语 |
| 4 | `greeting` | 生成招呼语 | 本地工作台 | 岗位池：生成人工准备清单 |
| 5 | `send` | 发送 | 外部执行流程 / 本人 | 接收发送结果回报 |
| 6 | `monitor` | 监控 HR 回复 | 外部 Agent / 本地邮件解析 | 接收回复结果回报 |

`approved` 表示审批队列中的已确认状态，不等价于已发送或已投递；实际状态以执行结果为准。

## 2. 读取契约与状态

```http
GET /api/pipeline?mode=demo
```

响应：

```json
{
  "ok": true,
  "mode": "demo",
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
        "mode": {"type": "string", "enum": ["demo", "user"], "default": "user"},
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
      "runtime_dir": "web/data/<mode>/offerpilot"
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

`GET /api/state?mode=demo` 的 `pipeline` 字段与上面的 `status` 相同，前端直接使用。内嵌后端状态也会出现在 `pipeline.offerpilot`；主工作台岗位 JSON 与 OfferPilot SQLite 岗位池始终分开。

### 2.1 只增字段（岗位、审批队列、发送额度）

以下字段是只读派生值，由 `GET /api/state` 返回，不写入任何本地文件：

- `jobs[].risk`：`{level: "low" | "verify" | "high", signals: [{code, severity, label, evidence}], blocks_queue: bool}`，来自 `tools/job_risk.py`。`level = "high"` 的岗位不能进入审批队列。
- `queue[].plan`：`{today: bool, rank: int | null, reason: string}`，来自 `tools/quota_planner.py`。只对 `approved` 且尚未发送的行计算。
- `pipeline.delivery.quota`：`{daily, remaining, planned_today}`。`daily` 为默认每日额度（30），仅用于排序提示；实际上限由内嵌发送器强制。

`POST /api/action` 的 `enqueue` 响应新增 `risk_blocked: string[]`，列出因高风险被拦截的岗位 id（即使带 `allow_low_score` 也会拦截）。

## 3.1 岗位自动化接口

```http
GET /api/offerpilot/state
GET /api/offerpilot/jobs
POST /api/offerpilot/tasks
POST /api/offerpilot/tasks/<task_id>/stop
```

网页「岗位池 → 岗位自动化」面板已接入这些接口：连接状态、能力与偏好快照、当前/最近任务、任务启动与停止、岗位表。启动请求必须明确确认并确认相关风险；`demo` 模式返回虚构的只读状态与岗位，并拒绝启动任务。

`/api/offerpilot/jobs` 是只读快照，不导入主工作台数据。启动任务请求必须同时带上 `confirm: true` 与 `risk_acknowledged: true`，并且 `mode` 只能是 `collect`、`monitor` 或 `full`：

```json
{"mode":"collect","confirm":true,"risk_acknowledged":true}
```

工作台不开放不受约束的任意任务入口；任务能力、发送配置和确认流程由当前功能实现及用户配置决定。`/api/offerpilot/jobs` 只返回界面所需字段，不返回敏感配置或凭据。

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
| `mode` | 否 | `demo` 或 `user`，默认 `user` |
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

错误：非 `send` / `monitor` 阶段或未知状态返回 `400`；非法模式返回 `400`。

也可使用统一动作入口：

```json
POST /api/action
{"action": "pipeline-event", "mode": "user", "stage": "monitor", "status": "succeeded"}
```

## 4. 边界

- 事件只追加到 `web/data/<mode>/pipeline-events.jsonl`，不改变岗位状态、不写审批队列、不触发超出当前任务的操作。
- 不接收敏感配置或凭据；本机运行时按用户配置读取所需会话和服务设置。
- 不接受任意 URL、脚本、HTML 或可执行内容；`message` 按纯文本保存与展示。
- 服务只绑定 `127.0.0.1`，校验 `Host` 与 `Origin` 均为本机。

## 5. 预留功能

模拟面试、信息推送、定制简历已在左侧面板预留位置，并复用本地题库、dry-run 载荷、经历变体与 ATS 预检。它们不属于六段核心流程，接入时请另开契约，不要复用 `send` / `monitor` 事件。
