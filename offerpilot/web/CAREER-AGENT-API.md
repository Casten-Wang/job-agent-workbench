# 公开项目核验接口 v0.1

当前阶段调整：优先完成定制简历，公开样例与模拟面试暂保留 API 和历史数据，页面不再启动或自动恢复面试。个人简历使用独立的 [直接生成流程](PERSONAL-CAREER-API.md)，无需先完成核验面试。

## Agent 层覆盖情况

`GET /api/agent/capabilities` 返回当前无凭据的能力地图。简历全文导入、GitHub 项目理解、面试问题计划、回答意图、逐题观察和提示共用 `interview_agent.model_adapter.ModelAdapter` 与 `step-5-preview`；有状态的面试由 LangGraph 保存检查点并驱动。定制简历版本、GitHub OAuth/下载、文件解析和 ATS 检查保持确定性，避免模型直接改写未确认事实或处理凭据。旧岗位采集评分、招呼语、题单选择和邮件分类仍是旧规则/上游链路，尚未迁移到统一 Agent 阶段。

## LangSmith 监控

启动时追加 `--langsmith`，会隐藏读取 `LANGSMITH_API_KEY`（已有环境变量则不再次询问），并将脱敏 Agent 阶段 trace 绑定到 `offerpilot-local-agent / production`；普通项目名仍默认为 `offerpilot-local`，可用 `--langsmith-project` 覆盖。Agent 阶段会记录名称、耗时、模型代次、输入/输出长度和 SHA-256；默认不发送简历正文、源码、回答或联系方式，也不打开 LangChain 自动 callback tracer，因此 LangGraph 状态对象不会被上传。只有明确设置 `LANGSMITH_CAPTURE_CONTENT=true` 才会上传输入输出正文，使用个人资料时应谨慎开启。未配置 key 或 LangSmith 不可用时，业务继续本地运行。

此接口将 OfferPilot 的定制简历与模拟面试页面连接到现有 Python / FastAPI / LangGraph 引擎。首期仅支持 `pallets/itsdangerous` 公开样例，固定 commit `672971d66a2ef9f85151e53283113f33d642dabd`。这是项目核验练习，不是用户经历或基于个人简历的正式模拟面试。

项目准备阶段复用了 ASu-skills 的求职表达原则：`prepare` 先根据目标岗位提炼通用工程支柱，再按“问题/演进 → 动作与机制 → 约束或边界 → 可核验证据”生成最多五条候选表述。每条同时返回岗位匹配理由、职责边界和待确认风险，方便用户筛选；支柱名和岗位定位帮助用户快速理解求职价值，源码证据与职责确认仍是写入简历的前置条件。

## 启动

在已安装本地面试服务依赖的 Python 3.11 环境中运行；OfferPilot 仓库本身不包含该引擎代码，需通过 `--engine-root` 指定包含 `interview_agent`、`interview_hub` 与 `github_source` 的目录。

```powershell
& 'D:\上海虹桥黑客松\.venv-interview\Scripts\python.exe' -I -B tools/run_career_demo.py --engine-root 'D:\上海虹桥黑客松' --key-stdin
```

当前 Windows 工作区也可直接运行 `./run_career_demo.ps1`，使用上级目录的 `.venv-interview` 环境；引擎在其他目录时传入 `-EngineRoot`。

密钥通过隐藏输入读入内存；也可事先在进程环境设置 `INTERVIEW_API_KEY`、`STEP_API_KEY` 或 `STEPFUN_API_KEY`。不将密钥写入源码、浏览器或启动参数。模型由引擎的 `interview_agent/provider.json` 配置，当前为 `step-5-preview`。

启动器运行两个本机端口：工作台 `127.0.0.1:8766`、独立样例引擎 `127.0.0.1:18747`。二者之间的随机 Bearer 令牌只保存在进程环境。Ctrl+C 停止两项服务；数据库保留，下次启动可恢复同一轮练习。

启动后访问工作台，在“我的 user → 定制简历”完成简历流程；模拟面试页面当前只显示接口预留说明。下方接口契约供后续接入，既有会话和复盘仍保留。

## 数据边界

- 只接受 `mode=demo`；user 模式在界面禁用，后端同样拒绝。不会读取 profile、岗位、个人简历或原先的面试数据库。
- 运行数据位于被 Git 忽略的 `web/data/demo/career-agent/`：`interview.db` 保存业务记录，`checkpoints.db` 保存运行状态。owner 固定为 `offerpilot-public-demo`。
- 固定样例材料在 `examples/career-agent/itsdangerous-material.json`。材料来源为已通过行级引用校验的本地公开样例，源码节选许可见同目录 LICENSE.txt；不自动联网读取所有仓库。
- 通过独立同源路由转发；上游固定为本机 18747，不接受 URL、端口、owner、自定义 material 或任意引擎路由。
- 回答会发送至已配置 Step 模型；页面提示勿输入个人信息。题目仅暴露引用位置，查看源码显式标记为查阅资料，提示保留为辅助作答。
- 核验结果与复盘均待确认，不写入个人简历，不更新岗位审批或投递状态。
- 现有 `/api/state` 仍为 27 个顶层键，`/api/pipeline/event` 仍只接收 send/monitor。

## 路由

所有路由使用同源 JSON HTTP；查询参数只允许 `mode=demo`。POST 也可带 `mode: "demo"`。

- `GET /api/resume-agent/materials`：返回固定公开材料的安全摘要。连接未配置时返回 503。
- `POST /api/interview-agent/sessions`：请求 `{ "session_id": "opdemo_<随机ID>" }`。服务端固定 `resume_readiness` 模式、材料、岗位方向；返回 201 和 `{ok, view, evidence}`。同一 ID 重试不会重建已初始化的计划；首次出题失败后可用相同 ID 重试初始化。
- `GET /api/interview-agent/sessions/{id}`：读取当前问题、状态、答题计数和复盘，不读取答案标准。返回 `{ok, view, evidence}`。
- `POST /api/interview-agent/sessions/{id}/turns`：请求 `{ "event_id": "evt_<随机ID>", "text": "回答", "command": null }`。回答限 1–12000 字；同 event_id 同载荷幂等，修改载荷返回 409。操作允许 request_hint、open_book、ai_assisted、skip、pause、resume、finish、retry、correct_contribution、correct_version。
- `GET /api/interview-agent/sessions/{id}/recap`：完成后读取 `{ok, recap}`，含待核实观察、未评估题目、简历处理建议和附源码的补强/复测任务。

会话 id 必须以 `opdemo_` 开头。读取、答题与复盘前检查计划与固定材料/源码绑定，其他材料的会话返回 403。错误只返回简短提示，不透传上游响应体、凭据或异常堆栈。

## 恢复与验证

浏览器只保存随机会话 ID，不把答案保存到 localStorage。暂停、刷新和服务重启均查询同一 session。网络操作失败时当前页面保留原事件 ID；刷新后依据 checkpoint 状态继续，不把未评估回答记成答错。

OfferPilot 自身的桥接测试使用标准库 unittest；父目录 `tests/test_offerpilot_integration.py` 用 FastAPI TestClient、真实 LangGraph/SQLite 和合成模型覆盖跨服务契约，不调用付费模型。

真实页面与模型验证应单独记录，使用公开样例及合成回答，不与用户能力评估混淆。正式个人简历面试、通用材料导入、GitHub 授权与简历版本仍待后续实现。

### 2026-11-16 验证结果

- OfferPilot 离线回归 236 项：235 通过，1 项因缺少本机个人简历文件跳过；在隔离副本执行。
- 本地引擎 20 项、数据源/Hub/跨服务集成 90 项，全部通过。
- 使用真实 `step-5-preview` 与合成回答，在实际 Edge 页面完成出题、提示、两题作答、源码查阅、一题跳过、复盘生成；暂停后刷新、完成后刷新及服务重启后均恢复成功。
- 复盘保留 hinted/open_book 辅助记录、未评估题目、补强与复测任务，未写入个人简历。桌面 1440px 和手机 390px 宽度无横向溢出，浏览器无脚本错误；user 模式及服务断开反馈也已验证。
- 真实出题曾因意图枚举不合法被拦截，已明确模型参数说明并保留严格校验；初始化失败后使用相同会话 ID 重试，不重复创建计划。
