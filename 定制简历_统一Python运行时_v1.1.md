# 统一 Python 运行时 v1.1

日期：2026-11-16。产品运行链路已移除 Pi SDK、Node 子进程与 JSONL 桥接，统一为 Python + FastAPI + LangGraph，继续使用阶跃 Step Plan 的 `step-5-preview`。

## 当前实现

客户端 → FastAPI → LangGraph → Python HTTPX → Step 5 → Pydantic 输出校验 → 源码／版本业务校验 → 检查点、结果与复盘。

- [model_adapter.py](./interview_agent/model_adapter.py)：异步请求、工具参数解析、总超时、有限重试及安全化错误分类。
- [decisions.py](./interview_agent/decisions.py)：原四类任务的提示词和严格 Pydantic 输出定义。
- [provider.json](./interview_agent/provider.json)：模型和 Step Plan 根地址，不含密钥。
- [api.py](./interview_agent/api.py)、[graph.py](./interview_agent/graph.py)：复用 FastAPI 业务入口与 LangGraph 状态图。
- [运行说明](./interview_agent/README.md)：安装、启动、调用、恢复和验证命令。

保留出题、自然语言意图识别、提示、逐题观察、暂停恢复、辅助作答标记、职责／版本修正、失败重试、重复事件幂等、最终结果和复盘。原有资料与结果不改写，模型来源绑定保持原结构，旧问题 ID 继续作为数据关联键。

## 供应商协议适配

本次最小真实请求对比中，强制指定具名工具的 tool_choice 得到普通文本，而 auto 得到正确工具调用。因此只暴露当前阶段一个工具并采用 auto；程序仍要求恰好一次该工具调用，普通文本、其他工具、多次调用、非法字段与重复 JSON 字段均不能触发业务动作。

首次响应结构不符时允许一次安全化格式修正；网络失败和 429／部分 5xx 最多重试一次，总时限 120 秒。HTTP 401 等访问错误直接返回分类，原始供应商错误正文和密钥不进入报告。当前保留 low 推理强度、8192 输出 tokens 上限。

模型调用在取得合格结构化决策后结束，不再请求额外的完成确认文本。运行状态始终由 LangGraph 掌握。

## 验证结果

- 19 项直接调用／工作流测试通过，覆盖四类 Schema、参数、格式修正、限流、超时、重定向拒绝、暂停恢复、修正、幂等与本地 HTTP 全流程。
- 原有 88 项回归测试通过。
- 真实 loopback HTTP → FastAPI → LangGraph → Python HTTPX → Step 5 联调通过，10 项检查全部通过，实际覆盖出题、提示、意图、评价与复盘保存。
- 提示后的回答保存 hinted 标记；未回答题目保持跳过／未评估，能力结论为空，简历未自动改写。
- 实际恢复上一版 Pi 适配时期的 Python 检查点，已完成轮次不调用模型即可恢复相同复盘。
- 活跃产品 Python 模块未导入 Pi 适配或 subprocess，根目录不再存在 pi_interview 运行目录；依赖检查通过。

记录：[汇总](./outputs/interview-agent/pure-python-summary.json)、[测试日志](./outputs/interview-agent/pure-python-tests.log)、[真实接口记录](./outputs/interview-agent/live-verification.json)、[运行时迁移检查](./outputs/interview-agent/runtime-migration-checks.json)。真实验证仍使用公开项目和合成回答，不构成真实用户能力校准。

## 归档与兼容

旧 Pi 原型保存在 [验证归档](./验证/legacy-pi-runtime-2026-11-16/README.md)，不由产品启动，也不要求安装其依赖。历史设计文档和结果保留此前阶段的验证范围。

新模型配置位于 interview_agent/provider.json；凭据使用 INTERVIEW_API_KEY、STEP_API_KEY 或 STEPFUN_API_KEY 本机环境变量。产品不再读取 `.pi` 配置或 PI_INTERVIEW_*。开发用 Context7 文档查询与产品运行时独立。

动态追问、历史复盘正文检索、补强后的复测、多用户权限和生产并发仍未扩展；本轮只迁移并验证现有能力。
