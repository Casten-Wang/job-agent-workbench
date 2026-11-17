# Python 编排迁移 v1.0

日期：2026-11-15。业务编排从 Node 手写状态机迁到 Python LangGraph，新增本机 FastAPI 接口，保留 Pi 为模型调用适配层。完整命令与边界见 [运行说明](./interview_agent/README.md)。

2026-11-16 更新：Pi 适配层已由 Python 直接模型调用替代，当前实现与验证见 [统一 Python 运行时 v1.1](./定制简历_统一Python运行时_v1.1.md)。本文保留此前阶段的验收范围。

## Pi 在这里的作用

Pi 执行模型任务：加载各阶段指令与 Schema，连接 Step 5，运行工具调用，返回结构化决策。每次模型决策使用独立短会话，只开放相应 submit 工具。Python 通过 JSONL 调用一个本机 Node 子进程，避免重写已经验证的模型适配。

业务状态由 LangGraph 掌握：什么时候出题、接受回答、暂停、修正职责、重试、结束。Python 校验引用和源码版本，并复用资料服务的存储、题目计划和复盘逻辑。Pi 不持有面试状态或业务数据库写入权限。

FastAPI 是接口入口；Pydantic 是输入校验；LangGraph 是流程和检查点；Pi 是模型执行器；Step 5 是模型；SQLite 分别保存运行检查点和不可变业务记录。Context7 继续提供开发文档查询，不在面试调用链中。

## 已迁移的行为

- 创建会话与冻结源码、材料、题目计划和模型来源。
- 意图识别、逐题评价和提示。
- 暂停／继续、跳过、辅助方式标记。
- 职责或版本修正后挂起结论。
- 评价失败保存原回答、意图节点失败恢复、重复事件幂等。
- 结束后保存结果、复盘及关联历史引用。
- 服务重启后通过 LangGraph 检查点恢复；显式导入旧 JSON，不改写旧文件或重放模型。

原业务资料、旧会话最终结果和原 Node 原型保留；新业务入口是 `python -m interview_agent`。不同模型的轮次保持各自来源，不能切换模型后冒充同一轮次恢复。

## 验证结果

11 项迁移和桥接测试、88 项既有回归测试通过。桥接测试实际经过 Python 子进程协议、Pi SDK 与确定性本机 HTTP 模型服务。

真实接口使用 `step-5-preview`，通过实际 loopback HTTP→FastAPI→LangGraph→Pi→模型，再保存一条合成回答的观察、最终结果与复盘。7 项检查通过，包括题目计划绑定、检查点落盘和服务退出。

产物：[真实接口记录](./outputs/interview-agent/live-verification.json)、[迁移测试日志](./outputs/interview-agent/migration-tests.log)、[依赖锁定](./interview_agent/requirements.lock.txt)。

## 未扩大的范围

未添加动态追问、历史正文检索、个人简历自动修改、真实能力总分、多用户登录或生产部署。当前是单进程本机 API，后续在这条状态图上逐步补齐产品流程。
