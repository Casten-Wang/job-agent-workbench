# 受控投递设计（审批通过 → 受控发送 → 回报结果）

> **状态：P1 已实现，P2 及以后仍是提案。** 已实现的部分只有「为已确认岗位生成招呼语 + 只读预览」：审批队列可勾选 `approved` 岗位调用 `offerpilot-greet`，结果只显示在本页，不发送。**投递（`deliver`）仍未实现**：`web/offerpilot_runtime.py` 的通用任务入口只允许 `collect` / `monitor` / `full`，`full` 在发送前暂停；工作台的 `approved` 只表示「可人工投递」。本文其余部分描述的是后续实现方案。

## 1. 目标与非目标

**目标**

- 审批队列里已 `approved` 的岗位，在本机把「打招呼」这一步从逐条手工点击变成**受控批处理**，并把真实发送结果回写到工作台。
- 自动化只覆盖「打开岗位 → 发送已复核的招呼语 → 记录结果」，每一步都受平台与用户的双重门禁约束。
- 结果可追溯：每个岗位的成功 / 失败 / 延后都有原因码，`approved` 与 `sent` 分开记录。

**非目标**

- 不做无人值守海投：没有「一键全投」「定时无限批」；每批必须人工确认。
- 不绕过平台风控：不自动过验证码、不在发送窗口外发送、不关闭随机休息日、不提高日限。
- 不改变共享评分门与审批语义；`approved` 不会因为发送而变成别的审批状态。
- 不新增远程服务；所有平台访问仍由内嵌运行时在本机发起。

## 2. 现有能力与缺口

| 能力 | 现状 | 位置 |
| --- | --- | --- |
| 人工审批 | `confirm` 需要完整确认语，写入 `approved` | `tools/approval_queue.py` |
| 岗位映射 | 导入时保留 `offerpilot_id`，可反查内嵌运行时岗位 | `web/backend.py` `_import_offerpilot_records` |
| 招呼语生成 | 内嵌运行时 `greet` 任务，AI 生成后写入运行时数据库 | `vendor/offerpilot` `_execute_greet` |
| 发送执行 | 内嵌运行时 `deliver` 任务，`send_greetings` 含窗口、日限、间隔、退避、风控锁 | `vendor/offerpilot` `executor/sender.py` |
| 结果指标 | `send_report`：成功 / 失败 / 延后 / 额度 / 停止原因 | `_execute_deliver` |
| 停止任务 | `POST /api/offerpilot/tasks/<id>/stop` 已存在 | `web/server.py` |
| **缺口** | P1 已暴露 `greet`（只生成 + 预览）；`deliver`、批次记录、复核编辑与结果回报尚未实现 | — |

发送端的既有安全参数（默认值，来自内嵌运行时配置，工作台不得放宽）：

- 发送窗口 `09:00–16:00`；窗口外任务不启动或中途停止。
- 随机休息日概率 5%。
- 每日发送上限 30 条；间隔 60–180 秒随机；失败渐进退避。
- 平台访问全局上限 1100 页/日；风控锁默认 10 分钟。
- 连续错误、验证码、频率限制、账号被拦截都会触发安全停止。

## 3. 流程：两段式，生成与发送分离

一次点击不能同时「生成 + 发送」；必须经过复核。

```
审批队列 (approved)
      │  ① 勾选 → 生成招呼语（greet 任务，不发送）
      ▼
招呼语复核面板
      │  ② 逐条查看 / 编辑 / 选择原文或优化版
      │  ③ 输入确认语 + 勾选风险确认 → 发送（deliver 任务）
      ▼
内嵌运行时 send_greetings
      │  ④ 逐条发送，受窗口/日限/间隔/风控约束
      ▼
结果回报
      │  ⑤ 同步 send_report + 运行时岗位状态 → deliveries.json + pipeline send 事件
      ▼
审批队列显示 sent / failed / deferred / blocked
```

**为什么分两段**：内嵌运行时的原生流程也是「生成 → 复核选择 → 发送」。分两段让用户在发送前看到实际文本，避免「AI 生成后直接发出」；同时 `deliver` 以 `_workbench_skip_greeting=True` 启动，发送的正是复核过的那一版，任务中不会再改文本。

**审批如何传给运行时**：工作台审批与内嵌运行时数据库是两套状态。发送启动时，运行时包装层在 `task_runner.start` 的 `before_start` 回调里，把本批 `offerpilot_id` 对应的岗位标记为 `approved` 并写一条历史记录（`actor: workbench`），随后才登记任务。任务启动失败则不改任何岗位。该标记只对本次批次生效，不会提前批量改状态。

## 4. 门禁矩阵

| 编号 | 门禁 | 规则 | 失败表现 |
| --- | --- | --- | --- |
| G0 | 运行环境 | 仅 `user` 模式；仅本机；同一时间只允许一个浏览器任务 | 400 / 409，任务不启动 |
| G1 | 审批 | 每个 id 必须在审批队列中且状态为 `approved`，且岗位带 `offerpilot_id` | 列出不合格 id，整批拒绝 |
| G2 | 批次规模 | 每批 1–10 条，默认 5；超过拒绝 | 400 |
| G3 | 招呼语 | 必须已生成且不是 `pending` 复核态；空文本拒绝 | 提示先生成或先完成复核 |
| G4 | 人工确认 | 确认语 `确认发送本批 N 条`（N 为实际条数）+ `risk_acknowledged: true` | 400 |
| G5 | 平台窗口 | 窗口外不启动；发送中跨出窗口则停止，剩余标 `deferred` | 返回下一个窗口时间 |
| G6 | 幂等 | 运行时状态已是 `sent` / `replied` / `resume_sent` 等的岗位不得重发；同批 id 去重 | 409 |
| G7 | 风控熔断 | 验证码 / 频率限制 / 拦截 / 连续错误 → 立即停止并写平台锁；剩余标 `blocked` | 任务 `failed`，原因透出 |
| G8 | 停止 | 用户点停止 → 当前条完成后停止，剩余 `deferred` | 任务 `stopped` |

**永不提供**：`force` 参数、窗口外发送开关、自动解锁平台锁、自动重试风控失败、提高日限的快捷入口。这些只保留在内嵌运行时自己的配置与 CLI 中。

## 5. 状态模型

### 5.1 工作台投递状态（新字段，不改审批状态）

```
not_ready → greeting_ready → confirmed → sending → sent
                                            ├→ failed
                                            ├→ deferred   （额度/窗口/用户停止，可下次再发）
                                            ├→ blocked    （风控锁，需人工处理后重试）
                                            └→ skipped    （岗位关闭等单条跳过）
```

- `not_ready`：没有可发送的招呼语。
- `greeting_ready`：已生成并复核，等待用户确认。
- `confirmed`：已通过确认语与风险确认，任务已登记。
- `sending`：任务运行中。
- 终态记录在 `deliveries.json`；审批队列的 `status` 始终是 `pending` / `approved`，二者互不覆盖。

### 5.2 与内嵌运行时状态映射

| 运行时岗位状态 | 工作台投递状态 | 说明 |
| --- | --- | --- |
| `ready` / `approved` + 有招呼语 | `greeting_ready` | 可发送 |
| `sent` / `replied` / `resume_sent` / `needs_resume` / `follow_up_sent` | `sent` | 已完成，禁止重发 |
| `error` | `failed` | 最近一次发送失败，可人工重试 |
| 任务停止且未处理 | `deferred` / `blocked` | 依据 `stop_reason` 区分 |

## 6. 数据形状（只增字段）

### 6.1 `web/data/<mode>/deliveries.json`

只存元数据，**不存招呼语正文**（正文留在内嵌运行时数据库，复核面板按需只读读取）。

```json
{
  "version": 1,
  "batches": [
    {
      "batch_id": "dlv-20261115-001",
      "task_id": "…",
      "created_at": "2026-11-15T10:00:00+08:00",
      "finished_at": "2026-11-15T10:09:00+08:00",
      "status": "completed",
      "requested": 5,
      "sent": 3,
      "failed": 1,
      "deferred": 1,
      "blocked": 0,
      "stop_reason": "daily_limit",
      "items": [
        {
          "job_id": "job-20261115-001",
          "offerpilot_id": "boss-…",
          "company": "示例公司",
          "title": "示例岗位",
          "status": "sent",
          "error_code": null,
          "greeting_selection": "generated",
          "started_at": "2026-11-15T10:00:10+08:00",
          "finished_at": "2026-11-15T10:01:40+08:00"
        }
      ]
    }
  ]
}
```

### 6.2 接口字段（追加）

- `GET /api/state`：`queue` 行追加 `delivery`（最近一次投递的 `{status, batch_id, finished_at, error_code}`）；`offerpilot` 追加 `delivery` 摘要（当前批次、今日已发/日限、下一窗口）。
- `GET /api/offerpilot/state`：追加 `delivery` 摘要。
- `GET /api/offerpilot/jobs`：追加只读 `greeting_ready` 布尔值与 `vendor_status`。
- pipeline 事件 `actor` 增加 `embedded_runtime`（现有 `external_agent` 不变）。

## 7. 接口

| 接口 | 行为 |
| --- | --- |
| `GET /api/offerpilot/greetings?ids=a,b,c` | 只读预览：公司、岗位、招呼语、风格问题、是否已复核；最多 10 条；不返回简历或凭据 |
| `POST /api/action` `offerpilot-greet` | 对已审批岗位启动 `greet` 任务；`{ids, regenerate?: bool}`；demo 拒绝 |
| `POST /api/action` `offerpilot-deliver` | `{ids, confirm: "确认发送本批 N 条", risk_acknowledged: true}`；通过 G0–G4 后启动 `deliver` 任务（`_workbench_skip_greeting=True`） |
| `GET /api/offerpilot/deliveries` | 返回最近批次；若最近 `deliver` 任务已结束但尚未同步，先幂等同步一次 |
| `POST /api/offerpilot/tasks/<id>/stop` | 复用现有停止接口 |

`offerpilot-deliver` 的校验顺序：模式 → 数量 → 审批状态 → `offerpilot_id` → 运行时岗位状态 → 招呼语 → 确认语 → 风险确认 → 窗口 → 平台锁 → 登记任务。任一步失败都不改数据。

## 8. 界面（审批队列 `#view-queue`）

- 顶部批量栏：「生成招呼语」「复核并发送」；仅当选中项全部 `approved` 时可用。
- 已审批行显示投递徽标：`待生成 / 待发送 / 发送中 / 已发送 / 失败 / 延后 / 已阻止`。
- 复核面板（页面内展开，不弹原生窗口）：
  - 每条：公司｜岗位、招呼语文本框（可编辑）、风格提示、重新生成（单条）。
  - 底部：本批 N 条、预计耗时区间（N−1 次 60–180 秒间隔）、今日剩余额度、是否附简历（跟随运行时配置）、确认语输入框、风险勾选。
  - 「开始发送」在确认语正确且风险已勾选前保持禁用。
- 发送中：进度条、当前公司｜岗位、已发送/失败/延后计数、停止按钮。
- 结束后：按结果分组；失败项显示原因码与建议动作；`deferred` 项保留在「可再次发送」。
- 工作台 `send` 阶段计数改用真实 `succeeded` 事件，不再只依赖外部回报。

## 9. 失败与熔断

| 现象 | 原因码 | 处理 | 剩余岗位 |
| --- | --- | --- | --- |
| 验证码 | `captcha` | 立即停止，写平台锁（默认 10 分钟） | `blocked` |
| 频率限制 | `rate_limit` | 同上 | `blocked` |
| 账号/请求被拦截 | `blocked` | 同上，提示人工检查账号 | `blocked` |
| 连续错误超阈值 | `consecutive_errors` | 停止并写锁 | `blocked` |
| 登录失效 | `login_required` | 停止，提示在浏览器重新登录；不自动重试 | `deferred` |
| 岗位已关闭 | `job_closed` | 单条跳过，继续 | 继续 |
| 网络抖动 | `transient` | 计入连续错误，退避后继续；达阈值即停 | 视情况 |
| 今日额度用尽 | `daily_limit` | 停止，剩余留到次日 | `deferred` |
| 跨出窗口 | `outside_window` | 停止 | `deferred` |
| 用户停止 | `stopped` | 当前条完成后停止 | `deferred` |

**不自动重试** `captcha` / `rate_limit` / `blocked`；重试必须由用户在看到原因后手动发起，且从新的确认开始。

## 10. 测试计划

- 单元：门禁矩阵逐条拒绝（模式、数量、未审批、缺 `offerpilot_id`、无招呼语、确认语错误、未勾选风险、窗口外、平台锁）。
- 幂等：已发送岗位拒绝重发；同一批重复 id 去重；同步任务按 `task_id` 只写一次。
- 映射：运行时状态 → 工作台投递状态；`stop_reason` → `deferred` / `blocked`。
- 运行时包装：`start_delivery` 传给 `task_runner.start` 的模式、岗位 id、`_workbench_skip_greeting`、`before_start` 的审批标记；启动失败不落任何状态。
- HTTP：`offerpilot-greet` / `offerpilot-deliver` / `offerpilot-deliveries` 的 400/409/503 分支；demo 模式全拒绝。
- 回归：现有 136 项测试保持全绿；`/api/state` 顶层键不变。
- 界面：桌面与手机宽度各跑一次生成 → 复核 → 发送 → 结果展示。

## 11. 分阶段落地

| 阶段 | 内容 | 可验证结果 |
| --- | --- | --- |
| P1 | 只读招呼语预览 + `greet` 任务 | **已实现（2026-11-15）**：已审批岗位能生成招呼语并在审批队列查看，**不发送** |
| P2 | 复核面板 + `deliver` 任务 + 批次记录 | 小批量真实发送，结果与原因码可见 |
| P3 | 招呼语编辑/原文优化版选择、失败项重试、投递历史 | 全链路可追溯，失败可人工重来 |
| P4（可选） | 窗口内定时批次（仍须提前确认） | 到点自动开始已确认的批次 |

每阶段都必须先跑 `sh tools/run_tests.sh`，并在 user 模式做一次真实小批量（1 条）验证后再扩大。

## 12. 开放问题

1. **是否允许跳过复核直接发送**：本提案不允许。若以后要放开，必须作为独立开关并默认关闭。
2. **附简历**：是否随招呼语发送由运行时配置决定；复核面板只展示「将附简历 / 不附」，工作台不单独控制。
3. **多平台**：目前只有 Boss；其他平台需要运行时先提供 `deliver` 适配器。
4. **工作台与运行时审批状态的同步**：本提案只在发送启动时写一次 `approved`，不在审批通过时提前同步，避免工作台与运行时状态漂移。
5. **招呼语正文的存储**：工作台不落正文；若以后要做投递历史全文，需要单独评估隐私与体积。
