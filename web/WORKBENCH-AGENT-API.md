# 全局 Agent 对话工作台 v1

工作台默认显示 Agent 对话，另一个页签保留原流程总览。会话按求职目标准备，读取已有岗位和已确认材料；不会自行采集岗位或发送消息。

## 运行与恢复

沿用 `tools/run_career_demo.py`（Windows 可用 `run_career_demo.ps1`）和仓库内的 `interview_agent` 引擎，不新增产品服务端口。变更后需重启该启动器，已在内存中的旧服务不会自动加载新路由。8766 为工作台，18747/18748 为隔离的 demo/user 引擎。

新增模块位于引擎的 `interview_agent/workbench.py`、`workbench_contracts.py`、`workbench_api.py`，同源桥接在 `web/workbench_agent_runtime.py`，页面资产为独立的 `workbench-agent.js/css`。引擎源码位于本仓库的 `interview_agent/`。

会话记录使用各 owner 业务数据库里的 `wb_conversation` 记录类型，包含消息、事件、执行状态、草稿修订和待确认动作；LangGraph 的 thread_id 包含 owner、会话编号和执行编号，与旧面试 checkpoint 分离。停止会取消当前模型请求，正式提交开始后等待真实写入结果，不把取消 HTTP 等同于撤销写入。重启不自动重放已执行工具；未完成任务保留结果并等待继续。

回退：设置 `OFFERPILOT_WORKBENCH_AGENT_DISABLED=1` 并重启，工作台回到流程总览。新增记录保留，不需要回滚历史材料或简历。首次实施备份保存在上级 `outputs/workbench-agent-backup/20261117-173158/`。

## 同源接口

以下路径均以 `/api/workbench-agent` 开头，必须显式带 `?mode=user` 或 `?mode=demo`。浏览器不能提交 owner、source 或模式覆盖字段；桥接按模式选固定的引擎及令牌。

- `GET /conversations`：会话列表，以及当前用户可选的已确认 `materials`。新会话不必先发送一条消息即可选择已有材料。
- `POST /conversations`：`{title?}`，创建目标会话，返回 201。
- `GET /conversations/{id}`：权威会话快照。
- `POST /conversations/{id}/messages`：`{event_id,text,job_id?,material_id?}`，返回 202 与 run_id。空字符串移除所选上下文；相同 event_id 重试不重跑，改写原事件返回冲突。
- `GET /conversations/{id}/events?after=游标`：增量事件及当前快照。刷新恢复使用 GET，不重发消息。
- `GET /conversations/{id}/stream?after=游标`：同源 SSE，直接转发当前用户引擎的事件流，不轮询或缓存整段回复。`snapshot` 携带业务事件与权威快照，`id` 为业务游标，支持 `Last-Event-ID`；`text_delta` 携带正在生成的正文增量，`text_reset` 开始或替换一段临时正文，`settled` 表示任务已结束。连接失败时页面回退到原事件查询，恢复后继续读取同一任务，不重发模型请求。
  - `text_delta` 字段为 `{id,run_id,offset,delta}`，offset 按 Unicode 码点计算。页面只接受当前消息与位置匹配的增量；位置不连续时重取快照。快照的 `streaming_message` 包含已收到的临时正文，断线或刷新可直接恢复，不重复追加。
  - 对话回复、推荐理由、简历要点与经历整理使用模型真实 SSE 输出。只提取可供用户阅读的正文，不展示推理、工具参数、引用编号或原始 JSON。生成中的内容有明确标记；完整结构、来源与语义校验仍在完成后执行，通过后才进入正式草稿或人工确认区。
  - 临时正文不按 token 写入数据库。停止或失败时保存已收到的部分，并标记未完成；后续模型决策不把未完成的回复当成有效历史。
- `POST /conversations/{id}/attachments`：`{event_id,kind,name,role,text,model_consent:true}`，kind 为 profile 或 experience。也可用 filename/content_base64 替代 text；支持 TXT/Markdown/PDF/DOCX，文件最多 5 MB，提取后最多 20000 字符。只在 user 模式开放。
  - experience 还可用 `material_id` 替代 text，重新整理同一用户的已有已确认材料。三种来源互斥；不接受其他用户、未确认材料或从项目材料推断整份个人资料。原材料不改动，新预览需要逐条确认；确认后的材料记录保留 `source_material_id` 与原材料快照哈希。
  - 页面优先使用新原文或文件；两者为空时使用下拉框选中的已确认材料。连接失败保留表单，同一会话和相同输入重试复用 event_id，不重复启动模型整理。执行中、失败与待确认状态按真实事件显示。
- `POST /conversations/{id}/approvals`：`{approval_id,approved,claim_ids?}`，人工批准或拒绝具体提案。claim_ids 只供用户确认所选经历表述。
- `POST /conversations/{id}/stop`：`{}`，停止执行并保留已完成产物。
- `POST /conversations/{id}/retry-material`：`{event_id,run_id}`，仅 user 模式，对失败或停止的材料整理发起重试；沿用本机会话保存的已授权原文，不能由浏览器替换原文或 owner。同一事件重试幂等，过期 run_id 返回冲突。有待确认的保存动作时应复核原提案，不重新启动整理。

会话快照新增 `material_run`（旧记录可能为空），包含材料名称、目标岗位、run_id、真实阶段、阶段说明及失败时的安全错误代码。成功的项目预览保留 `project_overview`、`summary`、`positioning`、`claims` 和对应 `evidence`；确认或拒绝后仍可重新打开。原文重试输入只留在本机内部记录，不随快照暴露。材料结果自动打开到结果区，贡献默认不勾选，须本人逐条选择。确认保存进入经历库；生成具体岗位简历与招呼语仍是后续步骤。

私有的 `/internal/profile` 是审批提交节点使用的固定回调，需要当前 user 引擎 Bearer 令牌；不注册为模型工具，浏览器无权调用。其回执在 user 数据目录持久化，重复提交同一批准编号返回原结果。

状态包括 idle、queued、running、committing、waiting_input、waiting_approval、completed、failed、stopping、stopped。业务事件与正文增量均来自真实执行过程，前端不使用计时器模拟吐字。

界面按 Desktop Agent UI 规范拆分会话、对话、工具过程和独立结果区。新收到的回复使用 Open Claude UI 手册中的 Grapheme Blur Reveal，并按用户反馈放缓：6px 模糊消解持续 420ms，每组约 3 个字，以 24ms 步进错峰，单次增量的最大视觉延后为 192ms。SSE 接收和任务状态即时更新，不等待动画；历史恢复不重播，已显示文本不重建。用户回看历史时停止自动跟随，可点“新回复”返回底部。支持浅深色、减弱动效、自适应输入框与选词后单次 Enter 守卫。样式仅在 Agent 工作台生效；流程总览及其他模块沿用原有外观。

## 业务与安全边界

- 新工作台阶段使用 Step Chat Completions 的 `response_format=json_schema` 严格输出；每种决策的参数以 action 区分，不能把岗位查询参数混入草稿工具。模型一次只提交一种受限决策，本地继续校验结构及工具参数；未知字段、工具、类型或引用不自动放行。每轮最多 12 次业务工具调用。旧面试与项目整理阶段继续使用原函数工具协议。
- 全局工具只读工作区摘要、岗位、专业资料、材料、版本、HR/面试与任务记录，以及准备/修改草稿和提出保存请求；没有发送、采集、任意 HTTP、SQL 或 Shell 工具。
- 输入到模型的上下文排除 private_profile/basic/凭据字段，并对自由文本中的联系方式及已知凭据形式脱敏。简历姓名与联系方式由确定性服务在本机拼入成品，不发送给改写模型。
- 已有岗位最多加载 200 条，单次推荐候选最多 30 条，最终最多 3 条；工具返回覆盖范围，不宣称检索了所有岗位或进行了新的客观评分。
- 简历要点与招呼语绑定已确认 claim_id；数字、职责升级及联系方式先由代码检查，再经独立模型阶段检查语义支持。该检查不是事实证明，仍须本人核对。
- 草稿修订不可变，修改不会覆盖旧稿。正式保存绑定具体修订、岗位/JD、材料、个人资料和模型来源；来源改变使旧确认失效。
- 简历保存复用 CareerService，版本包含原始来源、改写 source_map 和语义检查范围；关联的面试材料使用本次目标岗位快照，旧版本保持不变。
- Agent 招呼语当前不写入内嵌发送器。跳转发送复核时明确显示“未同步、未发送”，提供复制，沿用原审批和发送确认。

## 验收命令与限制

根测试统一用 `sh tools/run_tests.sh`（工作台、`tests`、`interview_agent/tests` 三组）。引擎与 Agent 测试使用仓库 `.venv` 的 Python：`.venv/bin/python -X utf8 -m unittest discover -s interview_agent/tests -q`（Windows 为 `.venv\Scripts\python.exe`）。Windows Python 3.11 的 `-I` 子进程会忽略编码环境变量，部分旧 CLI 测试在该解释器下有 GBK/UTF-8 冲突；这不通过修改断言掩盖。

（历史验收记录：以下 `验证/` 脚本与 `outputs/` 目录在作者本机的上级工作区，不在本仓库中。）

上级 `验证/workbench_agent_smoke.py --verify` 使用真实 localhost HTTP、隔离数据库与协议测试模型完成主链。`--live --verify` 则使用已有 DPAPI 配置的 Step 密钥和同样的合成资料进行真实模型验收；不会记录密钥，也不使用真实 user 资料。验收结果与页面证据保存在上级 `outputs/workbench-agent/`。

`live-http.json` 保留完整通过的记录，`latest-live-check.json` 记录最近一次真实模型复测，失败同样写入，不能把历史通过误认为最近一次结果。当前真实 Step 主链曾完整通过；后续复测中，修订招呼语把“Python 输入校验”扩写为“Python 服务”经历，语义检查拒绝了该修订并保留原稿。协议模型测试不能当成真实模型质量证明；模型语义支持也不能替代用户职责核对。真实 Windows 输入法候选词选词仍需单独人工验收，页面已设置 composition/选词后保护。

流式专项使用上级 `验证/workbench_agent_smoke.py --stream-fixture --port 8772` 启动隔离的本机 SSE 模型，再运行 `验证/workbench_stream_verify.py`。专项覆盖模型结束前出字、中文与 emoji、断线续接、停止保留部分输出，以及整理完成后仍等待人工确认。`--live --port 8773` 启动真实模型的合成资料环境，使用 `workbench_stream_verify.py --live --port 8773` 记录首段正文与完整响应的时间。结果在上级 `outputs/workbench-token-stream/`，与旧主链报告分开保留。
