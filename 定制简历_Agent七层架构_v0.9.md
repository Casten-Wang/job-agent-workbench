# 定制简历 Agent 七层架构 v0.9

日期：2026-11-15。基于当前工作区代码核对。七层是职责视角，当前没有把它们拆成七个服务。

后续状态机已迁移至 Python，最新组件关系与验收见 [Python 编排迁移 v1.0](./定制简历_Python编排迁移_v1.0.md)。本文保留迁移前的七层分析记录。

当前实现可概括为：有状态工作流，调用四类模型决策，经过程序校验后执行；项目证据、逐轮状态、最终结果与复盘分别保存。

## 模型与验证状态

默认模型已切换为 `step-5-preview`，使用 Step Plan 的 `https://api.stepfun.com/step_plan/v1` 和 Chat Completions 协议。Pi 登记上下文为 1M，当前仅传入文本证据包；单次输出预算仍限制为 8192 tokens，推理强度 low。

本轮 8 项 Node/Pi 自动化测试通过；真实接口完成 plan、intent、observation 三个阶段与结果、复盘入库。实际生成 3 道问题，对一条合成回答生成观察，其余题目跳过。SQLite 重读确认会话完成、问题计划和源码版本绑定、评价数量及复盘内容一致。此前的 Flash 验证保留在对应运行目录，没有当作 Step 5 验证使用。提示阶段已有协议测试，尚未单独进行本轮真实模型验证。

来源：[Step 5 Preview 官方说明](https://platform.stepfun.com/docs/zh/guides/models/step-5-preview)、[当前预设](./验证/legacy-pi-runtime-2026-11-16/stepfun-plan.json)、[真实接口验证](./outputs/pi-interview/live-verification.json)、[本轮测试日志](./outputs/pi-interview/step5-node-tests.log)。

## 1. 模式层：以什么方式完成什么业务

业务上，当前真实跑通的是简历生成前的项目理解核验。资料服务有 `resume_readiness`、`mock_interview` 两种模式；正式模拟面试要求已经保存的简历版本，公开样例没有该版本，因此不能冒充正式个人面试。复盘通过独立接口产生。

执行方式是受控工作流加结构化工具调用：开始时形成题目计划，每次话语识别意图，技术回答进入逐题观察，明确结束后汇总。当前每轮一次生成最多三题，按顺序执行。

待补：根据回答动态追加追问、真实简历版本的正式模拟面试、目标岗位和公司研究驱动的问法调整。

代码：[模式约束](./interview_hub/server.py)、[编排入口](./验证/legacy-pi-runtime-2026-11-16/interview.mjs)、[CLI](./验证/legacy-pi-runtime-2026-11-16/cli.mjs)。

## 2. 编排层：由谁决定执行次序与允许动作

`Interview` 类负责会话、当前问题、回答、辅助方式和状态转换。它调用 `createDecisionAgent().decide(stage, input, validate)`，但具体保存、推进、暂停与结束由普通程序执行。

顺序为：创建并冻结会话 → 取资料 → plan 出题 → 验证并保存问题计划 → 接收话语 → intent → 状态校验 → observation 或提示／暂停／修正等动作 → 保存最终结果 → 生成复盘。

状态包括 active、paused、held、ready_to_finish、finalizing、completed；pending 记录尚未评价完成的回答。暂停时不接收技术评价；职责／版本修正会挂起相关观察；恢复需要相同资料、源码、题目计划和模型。

待补：动态追问的追加记录、并发会话事件处理、面向网页或模拟面试前端的 Pi 编排 API。当前 Pi 入口是本机 CLI，现有 HTTP 接口主要提供资料、结果和复盘。

代码：[状态机](./验证/legacy-pi-runtime-2026-11-16/interview.mjs)、[Hub 客户端与本机启动](./验证/legacy-pi-runtime-2026-11-16/hub-client.mjs)。

## 3. 组件层：具体由什么构件组成

- 模型运行时：官方 Pi SDK 1.5.2、Step Plan 适配、`step-5-preview`。
- 四类模型决策：plan、intent、observation、hint；每次决策创建独立短会话，避免把评价依据混进意图识别输入。
- 资料与复盘服务：Python Interview Hub，通过 loopback HTTP 提供材料、问题计划、结果、历史和复盘。
- 数据组件：SQLite 存不可变材料、会话、问题计划、结果、复盘；JSON 存编排进行中的状态与事件。
- 项目资料：GitHub 公库固定快照、源码行引用、UA 解读产物与引用验证。Graphify 是已有静态索引验证工具，未作为当前面试运行时的实时工具接入。
- 开发文档：Context7 MCP 连接开发用 Pi；候选人面试运行时只加载当次决策工具。

待补：GitHub App／私库授权同步、运行时按需检索源码、公司／JD／面经资料整合。现有项目解读是提取原型与验证产物，尚未形成授权后自动通读所有仓库的完整流水线。

代码：[Pi 模型与工具](./验证/legacy-pi-runtime-2026-11-16/agent.mjs)、[资料服务](./interview_hub/server.py)、[存储](./interview_hub/store.py)、[GitHub 提取](./github_source/ingest.py)、[UA 引用验证](./github_source/understand.py)、[Context7 MCP 配置](./.pi/mcp.json)。

## 4. 安全层：限制输入、权限与输出影响

每个阶段只暴露一个 `submit_*` 工具，使用 TypeBox 校验结构；宿主和资料服务继续检查问题、声明、证据、源码提交和计划版本。面试 SDK 关闭自动扩展、技能和上下文文件发现，未开放 Shell 或文件写入工具。代码和回答作为材料，提示中明确区分材料与指令。

Hub 只绑定 127.0.0.1，并校验服务令牌。凭据在本机进程中使用，不进入模型提示或验证报告。最终结果和问题计划不能覆盖。职责存疑保持未知，缺答保持未评估；反馈和简历建议待确认，程序不自动删除或改写简历。

待补：真实多用户身份、细分角色权限、专门的提示注入对抗验证、操作系统级隔离。当前限制工具不等于进程已在 OS 沙箱中。人工确认目前主要体现为数据状态，采纳／驳回界面尚未实现。

代码：[决策工具边界](./验证/legacy-pi-runtime-2026-11-16/agent.mjs)、[引用与计划校验](./interview_hub/plans.py)、[鉴权与版本校验](./interview_hub/server.py)、[结果约束](./interview_hub/recap.py)。

## 5. 工程层：如何运行、恢复、测试与定位问题

Node/Python 组件在本机通过 HTTP 连接，依赖锁定在项目内。进行中的状态用临时文件再替换保存，回答先暂存再请求评价；失败后可重试。SQLite 的最终结果写入与完成标记处于事务内，重复提交幂等，历史记录保持原版本。

已有自动化测试、确定性 HTTP 模型服务、真实接口验证脚本、阶段状态记录和安全化 HTTP 错误分类。本轮 Node/Pi 8 项测试通过；Python 88 项是前一轮相同后端代码的验证记录，本轮没有重复执行。

待补：生产部署、并发状态锁、队列、持续集成、Prompt 版本记录、统一请求追踪、阶段耗时、token 用量与预算监控。当前未知模型的费用元数据是占位值，不能用于真实计费判断。

代码：[依赖与命令](./验证/legacy-pi-runtime-2026-11-16/package.json)、[真实验证入口](./验证/legacy-pi-runtime-2026-11-16/live-check.mjs)、[自动化测试](./验证/legacy-pi-runtime-2026-11-16/test/agent.test.mjs)、[本机模型输入](./验证/legacy-pi-runtime-2026-11-16/配置阶跃StepPlan.ps1)。

## 6. 机制层：决策闭环如何实际生效

决策闭环是：获取上下文 → 模型提交结构化决策 → 程序验证 → 执行动作 → 保存反馈。plan 依赖已绑定证据；intent 结合当前题目、状态和最近话语；observation 独立取得本题原文与评价草稿，按语义产生待复核观察。

记忆有三个实际范围：最近话语、当前会话 JSON、SQLite 中的历轮最终结果与复盘。当前只把创建会话时冻结的既有复盘引用传入新轮次，并未自动通读历史复盘正文，也没有向量语义检索。

补强机制目前到“观察 → 任务草稿”，任务带材料、行动、完成条件和复测提示。后续的执行补强、复测通过、更新准备状态，以及生成新简历版本尚未闭环。辅助作答不等于独立掌握。

代码：[逐题循环与恢复](./验证/legacy-pi-runtime-2026-11-16/interview.mjs)、[历史引用](./interview_hub/server.py)、[补强与复测草稿](./interview_hub/recap.py)。

## 7. 定义层：目标、角色、对象与验收标准

目标是帮助候选人判断某一条项目陈述是否具有材料和表达支撑，并找到需要补强的部分。Agent 的角色是核验与准备辅助，个人职责仍需本人确认。

核心对象是项目快照、源码证据、经历声明、题目计划、会话、回答、观察、复盘和补强任务。核心关联是 source_commit、project_snapshot_id、claim_id、evidence_id、question_plan_id、resume_version_id。

验收标准包括：问题绑定真实资料；模型输出通过结构与引用校验；回答与复盘属于同一轮次和版本；未知与缺答被保留；结束后的结果可恢复；补强建议不会被自动当作掌握证明或简历修改授权。

待补：不同岗位的准备标准、公司与面试轮次的评价要求、可验证的个人贡献与指标规则，以及真实用户样本下的语义评价校准。

代码：[决策 Schema 与指令](./验证/legacy-pi-runtime-2026-11-16/agent.mjs)、[问题计划 Schema](./interview_hub/plans.py)、[结果与草稿定义](./interview_hub/recap.py)。

## 层与层的关系

定义层给出目标和标准，模式层选择业务与执行方式，编排层安排步骤，组件层提供执行能力。安全层限制行为边界，工程层保障运行和可追踪性，机制层把上下文、决策、动作与记忆连成循环。后面三者贯穿执行链，并非请求需要依次穿过的三个额外服务。

现阶段优先补齐：逐题动态追问、真正读取历轮复盘正文、补强后的复测与准备状态更新。这三项直接决定服务能否持续依据候选人的材料与表现调整下一步。
