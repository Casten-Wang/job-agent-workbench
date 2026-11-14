# 内嵌 OfferPilot 后端

工作台把岗位自动化作为内嵌能力运行，不再需要独立服务。源码完整放在本仓库的 `vendor/offerpilot/`，由 `web/offerpilot_runtime.py` 在**同一个 Python 进程**里导入，和工作台的 `web/server.py` 一起启动，不占用额外端口。

## 来源与许可

- 内嵌运行时：OfferPilot v2.4.0（源码位于 `vendor/offerpilot/`，版权与来源记录见该目录的 `README.md` 与 `LICENSE`）。
- 许可：**PolyForm Noncommercial License 1.0.0**，原文保留在 `vendor/offerpilot/LICENSE`。本仓库是个人自用、非商用项目；不得删除版权声明，也不得把内嵌代码用于商业分发。
- 已移除自带的 `web/frontend`（工作台用自己的前端），未包含 `__pycache__`、`.pyc`、虚拟环境、凭据、数据库或任何个人数据。

## 运行时目录

| 模式 | 目录 | 内容 |
| --- | --- | --- |
| `demo` | `web/data/demo/offerpilot/` | 虚构演示；只读，不启动真实任务 |
| `user` | `web/data/user/offerpilot/` | 本机 `config.yaml`、`.config.credentials.yaml`（0600）、`data/offerpilot.db`、`data/resumes/` |

`web/data/` 已在 `.gitignore` 中忽略。运行时目录在首次启动时自动创建，不会从其他目录复制数据库、配置或简历。

## 依赖

```bash
python3 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r requirements-offerpilot.txt
```

或直接运行 `./run_web.sh`，首次会自动创建 `.venv` 并安装。测试套件不依赖这些包：`offerpilot_runtime` 使用懒加载，测试会 mock `get_state` / `start_task` / `stop_task`。

## 暴露面

| 接口 | 行为 |
| --- | --- |
| `GET /api/offerpilot/state` | 能力、偏好快照、当前/最近任务与 `resume`（是否已有评分简历、文件名、大小、上传时间）；不返回日志、密钥或凭据 |
| `GET /api/offerpilot/jobs` | 只读岗位白名单字段，最多 100 条 |
| `POST /api/offerpilot/preflight` | 只检查不启动：按 `mode` + `options` 返回搜索参数、浏览器运行时、Chrome 调试端口与 BOSS 标签页检查结果；若已有任务占用浏览器，返回 `browser_busy` 并提示先停止或等待 |
| `POST /api/offerpilot/tasks` | 仅 `collect` / `monitor` / `full`，必须同时带 `confirm: true` 与 `risk_acknowledged: true`；`demo` 模式拒绝；`collect` / `full` 可带 `options` |
| `POST /api/offerpilot/tasks/<id>/stop` | 请求停止内嵌运行时的既有任务 |
| `POST /api/action` `offerpilot-import` | 把只读结果中选中的岗位复制进工作台岗位池（仅 `user` 模式，最多 100 条） |
| `POST /api/action` `offerpilot-resume` | 上传评分简历（仅 `user` 模式；`.md` / `.docx` / `.pdf`，最大 5 MB），写入本机运行时 `data/resumes/` 并把 `profile.resume_path` 指向它 |
| `POST /api/action` `offerpilot-greet` | 为审批队列中 `approved` 且带 `offerpilot_id` 的岗位启动 `greet` 任务（仅 `user` 模式，最多 10 条）；只生成招呼语，不发送 |
| `POST /api/action` `offerpilot-deliver` | 发送已复核的招呼语（仅 `user` 模式，最多 10 条）：要求确认语「确认发送本批 N 条」与 `risk_acknowledged: true`；批次写入 `deliveries.json` |

`options` 只作用于本次任务，不写回 `config.yaml`：

```json
{
  "mode": "collect",
  "options": {
    "platform": "boss",
    "keywords": ["产品经理"],
    "cities": ["北京"],
    "max_pages": 1,
    "auto_score": false,
    "pace": "cautious"
  }
}
```

限制：平台固定为 `boss`；关键词最多 10 个、城市最多 5 个、页数 1–10；`pace` 只接受 `cautious` / `standard` / `fast`。`monitor` 不接受 `options`。`full` 只允许支持投递的平台，并强制 `auto_score`。

`pace` 决定每次翻页/读详情前的随机等待：稳健（默认）6–15 秒、标准 3–7.5 秒、快速 2–5 秒，对应内嵌运行时的 `collection_delay_multiplier`（3.0 / 1.5 / 1.0）。

导入时把内嵌运行时的 0–100 分换算为工作台的 0–5 分，以两套评分门对齐：71 分（内嵌运行时的审批阈值）对应 4.0，换算为 `min(5.0, round(raw * 4.0 / 71, 1))`，并保留 `score_raw` 与 `score_scale`；同一岗位按指纹去重，重复导入不会产生副本。任务完成后面板会自动调用一次导入（同一任务只导入一次，失败可重试）；导入只写岗位信息，不进入审批、不发送任何内容。

没有 `deliver` 路由，也没有自动 Submit/Send 路径。发送仍由内嵌 OfferPilot 自己的人工确认门、配置时间窗口和首次使用风险提示控制；工作台不绕过、不隐藏这些门禁。

## 实现要点

- `load_backend()` 把 `vendor/offerpilot/src` 加入 `sys.path`，导入 `offerpilot.web.server`，调用 `set_base_dir(web/data/user/offerpilot)` 后缓存。
- `get_state()` 直接读取配置与 `task_runner.status()`，不走 Bottle 的线程局部 `response`，因此能在工作台的 HTTP 线程里安全调用。
- `get_jobs()` 直接打开 SQLite 并调用内嵌运行时的 `query_jobs` / `serialize_job`，只保留白名单字段。
- `preflight()` 复用内嵌运行时的 `collect_preflight_checks`，只读检查配置、搜索参数与浏览器环境，不创建任务、不访问平台。
- `start_task()` 复用内嵌运行时的 `normalize_collection_options`、`platform_supports`、`collect_preflight_checks` 与 `WorkbenchTaskRunner`；搜索参数通过 `_collection_options` 传入内存配置。`collect` 的自动评分需要 AI 已配置且本机已有评分简历，前端在两者都满足时默认勾选；没有简历仍可采集，岗位以「未评分」导入。`full` 强制自动评分并保留发送前暂停。
- `save_resume()` 复用内嵌运行时的 `prepare_resume_content`、`write_resume_artifacts`、`resolve_active_resume_path` 与 `select_resume_markdown_filename`，与上游上传行为一致；简历只写入 `web/data/user/offerpilot/data/resumes/`，不进入仓库。
- `start_greet_task()` 只启动 `greet` 任务：要求 AI 已配置且本机有评分简历；在 `task_runner.start` 的 `before_start` 回调里把本批运行时岗位标记为 `ready`（否则状态为 `pending` 的岗位会被生成器过滤），并写一条 `workbench_greet` 历史。任务只生成文本，不访问平台、不发送。
- `get_greetings()` 只读返回白名单字段（公司、岗位、招呼语、来源、风格提示、是否可复核），最多 50 条；`snapshot` 只把它附加到 `approved` 队列行，供审批队列做只读预览。
- `start_deliver_task()` 只启动 `deliver` 任务：启动前检查发送窗口、平台风控锁、岗位状态、招呼语是否齐全且不在 `pending` 复核态；`before_start` 把本批岗位标记为 `approved` 并写 `workbench_deliver` 历史；配置固定带 `_workbench_skip_greeting=True`，发送的就是复核过的文本。运行时不传 `force`，窗口、日限、间隔、退避与风控锁全部沿用内嵌运行时。
- 批次结果写在 `web/data/<mode>/deliveries.json`：只存岗位、状态与原因码，不存招呼语正文。任务结束后 `_sync_deliveries()` 读取运行时岗位状态，把每条标记为 `sent` / `failed` / `deferred` / `blocked`，并为每条写一条 `send` 阶段的 pipeline 事件（`actor: embedded_runtime`）。`GET /api/state` 的 `pipeline.delivery` 返回最近批次，队列行附带 `delivery` 摘要。
- `import_offerpilot_jobs()` 只读 `get_jobs()` 的白名单字段，按岗位指纹去重后写入工作台 `jobs.json`；不写回内嵌运行时，也不改变审批状态。
- 依赖缺失或初始化失败时返回 `ok: false` 与本地安装提示，面板显示「未就绪」，服务本身继续运行。

## 验证

```bash
sh tools/run_tests.sh
```

`tools/tests/test_web_backend.py` 覆盖：状态脱敏、任务日志/凭据剥离、demo 只读、显式确认、内嵌启动/停止、搜索参数校验与传递、只检查不启动的预检、导入去重与分数换算、demo/未知 ID 拒绝、`vendor` 许可与前端排除、依赖清单与 `.venv` 忽略。
