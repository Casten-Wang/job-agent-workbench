# 公开项目核验接口 v0.1

本文件记录工作台接入的公开项目核验桥接（`web/career_agent_runtime.py`）。**本次只接入后端与路由**：页面、启动脚本与面试引擎本身不在本仓库内，工作台也没有对应前端入口。

## Agent 层覆盖情况

`GET /api/agent/capabilities` 返回当前无凭据的能力地图（`web/agent_capabilities.py`）。地图把本仓库内直接调用模型的文字面试阶段（出题计划、逐题追问、复盘、重练）与由外部引擎承担的阶段分开列出，并标注 `external_engine.in_repo = false`：项目核验引擎通过本机 18747 端口接入，仓库不内嵌 `interview_agent` / `interview_hub` / `github_source` 的源码。定制简历版本、ATS/PDF 检查保持确定性，避免模型直接改写未确认事实。

文字面试本体的接口见 [INTERVIEW-TEXT-API.md](INTERVIEW-TEXT-API.md)。

## 数据边界

- 桥接只暴露固定公开样例：材料 `mat_6c05373d57d03a107d49806c`、固定源码 commit `672971d66a2ef9f85151e53283113f33d642dabd`。不接受 URL、端口、owner、自定义 material 或任意引擎路由。
- 工作台只有一个本机数据集（`mode` 仅为兼容字段）。桥接只接受缺省或 `mode=user`；其他值一律 400。查询参数只允许 `mode`。
- 固定样例材料在 `examples/career-agent/itsdangerous-material.json`，源码节选许可见同目录 `LICENSE.txt`；桥接会校验 `material_id`、`source_commit`、`is_demo` 与 `resume_version_id`，不匹配返回 503。
- 会话数据由外部引擎自己保存在本机（不受本仓库管理）；桥接本身不写工作台数据目录，也不读写个人资料、岗位、审批或投递状态。
- 上游固定为本机 `127.0.0.1:18747`，随机 Bearer 令牌只来自进程环境变量 `OFFERPILOT_CAREER_AGENT_TOKEN`（少于 20 字符视为未启动，返回 503）。错误只返回简短提示，不透传上游响应体、凭据或异常堆栈。
- 现有 `/api/state` 仍为 27 个顶层键，`/api/pipeline/event` 仍只接收 send/monitor。

## 启动

1. 在本机另行启动项目核验引擎（含 `interview_agent`、`interview_hub`、`github_source`；引擎源码不在本仓库），监听 `127.0.0.1:18747`。
2. 在同一个进程环境里设置随机的 `OFFERPILOT_CAREER_AGENT_TOKEN`（至少 20 字符），再启动工作台。

```bash
export OFFERPILOT_CAREER_AGENT_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
sh run_web.sh
```

密钥不写入源码、浏览器或启动参数。未配置令牌时，桥接路由返回 503，消息提示先在本机启动面试服务。

## 路由

所有路由使用同源 JSON HTTP；查询参数只允许 `mode`（缺省或 `user`）。POST 也可带 `mode: "user"`。

- `GET /api/resume-agent/materials`：返回固定公开材料的安全摘要。服务未配置时返回 503。
- `POST /api/interview-agent/sessions`：请求 `{ "session_id": "opdemo_<随机ID>" }`。服务端固定 `resume_readiness` 模式、材料、岗位方向；返回 201 和 `{ok, view, evidence}`。同一 ID 重试不会重建已初始化的计划；首次出题失败后可用相同 ID 重试初始化。
- `GET /api/interview-agent/sessions/{id}`：读取当前问题、状态、答题计数和复盘，不读取答案标准。返回 `{ok, view, evidence}`。
- `POST /api/interview-agent/sessions/{id}/turns`：请求 `{ "event_id": "evt_<随机ID>", "text": "回答", "command": null }`。回答限 1–12000 字；同 event_id 同载荷幂等，修改载荷返回 409。操作允许 request_hint、open_book、ai_assisted、skip、pause、resume、finish、retry、correct_contribution、correct_version。
- `GET /api/interview-agent/sessions/{id}/recap`：完成后读取 `{ok, recap}`，含待核实观察、未评估题目、简历处理建议和附源码的补强/复测任务。

会话 id 必须以 `opdemo_` 开头。读取、答题与复盘前检查计划与固定材料/源码绑定，其他材料的会话返回 403。

## 恢复与验证

浏览器（接入页面时）只保存随机会话 ID，不把答案保存到 localStorage。暂停、刷新和服务重启均查询同一 session。网络操作失败时保留原事件 ID；刷新后依据引擎侧的 checkpoint 状态继续，不把未评估回答记成答错。

桥接测试使用标准库 unittest，只覆盖同源校验、参数白名单、固定材料过滤与错误信息；不启动引擎、不调用模型。真实页面与模型验证需单独记录，使用公开样例及合成回答，不与用户能力评估混淆。
