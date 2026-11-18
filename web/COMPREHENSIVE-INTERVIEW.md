# 综合模拟面试室

「模拟面试」页的主入口，页面标签为「1v1 综合模拟面试室」，默认打开。同一页还有两个标签：「项目源码核验」（归对话助理模块）和「题单与本地题库」（四张卡片：模拟面试、Mock 题单、面试复盘、题库与面经，需求见 `docs/PRD.md`）。标签切换在 `workbench.js` 的 `setInterviewMode`。

本文只描述代码里已有的行为。文中没有写到的能力，一律按未实现处理。

## 用户流程

1. 在 `#ci-setup-form` 选择：岗位族（工程研发、算法、产品业务、通用）、轮次（一面、二面、主管终面、HR、全流程）、时长（20、30、45、60 分钟）、冷启动方式、目标岗位、简历版本，可贴 JD，可填上一场的场次编号接着追问。
2. 点「开始这场面试」。服务端先冻结一份面试简报，再生成内部考纲。页面不展示考纲。
3. 面试官的话逐字流式出现。用户可以回答，也可以发控制指令：暂停、继续、要提示、跳过、强制跳过、标记翻了资料、标记借助了 AI、澄清需求边界、更正贡献、更正版本、提前结束、结束。
4. 结束后生成复盘，可导出 Markdown，并可对复盘里选出的题做单缺口重练。

## 面试简报

`brief_assembler.py` 在开场前把下列内容冻结成不可变的 `InterviewBrief`，面试过程中不再变化：

- 个人资料快照、简历版本（`immutable_version`、`profile_fallback`、`warmup_only` 三种绑定方式之一）、技能、履历。
- 项目与其知识库覆盖情况、项目陈述（claims）及证据编号。
- 目标岗位快照、同目标的面经与岗位知识（`company_official`、`company_jingyan`、`similar_role_other_company`、`web_supplement` 四种来源范围）。
- 简历、项目档案与个人资料之间的口径冲突（指标不一致、角色或概述不一致）。
- 上一场复盘遗留的待复测议题。

网页入口 `career_user_runtime._enrich_comprehensive_start` 在服务端补齐画像、岗位快照和本机面经，浏览器传来的同名字段只作补充，不能替代。

来自面经、笔记、JD 的文本一律包成不可信数据（`wrap_untrusted_data`），其中的指令不执行。

## 考纲与出题

- 考纲由「岗位族 × 轮次」的模板给出板块和权重（`comprehensive_policy.py` 的 `_MATRIX_SECTIONS`、`_ROUND_FALLBACKS`），再由模型只填每道题的具体考察点（`BlueprintDraft`）。板块、配比、题型、来源引用和主备顺序由服务端保留。
- 题型包括开场、基础追问、写代码或排障、简历深挖、仓库核验、JD 场景、案例、压力追问、历史复测、候选人反问、备选。
- 另备 2 到 4 道备选题，主线题答完或被跳过且时间充足时启用。
- 模型生成考纲超时或结构校验失败时，退回确定性的保底考纲，不会卡住开场。

## 计时

只计候选人的有效作答时间。模型生成、知识检索、暂停、重试期间冻结计时。时长 45 分钟及以上预留 5 分钟给候选人反问，更短的预留 3 分钟。有效时间耗尽后，当前问题答完即不再出新题。

## 防卡死

- 追问有熔断：单题追问次数按板块上限（默认 2，最大 3）。
- 第一次说「不会」或跳过：给一次降维提示，停在当前题。
- 第二次跳过或强制跳过：记为中性跳过，切到下一道主线题。
- 主线题用尽且时间充足：启用备选题。
- 否则进入候选人反问，再到结束门。

## 复盘

`ComprehensiveDebrief` 的约束由 `comprehensive_policy.sanitize_debrief` 在服务端核验：

- 准备度四档：`ready`、`almost_ready`、`needs_practice`、`insufficient_evidence`，附一句理由。
- 维度分数 1 到 5，带权重和原文证据引用。没有证据的维度标记 `evidence_insufficient`，不补分。
- 红线与加分信号、最优先修正项、反问环节小结、跨轮补强任务、可重练题编号（最多 3 道）。
- 简历修改建议只是草稿，状态固定为待用户确认，`applied_to_resume` 恒为 `false`，不会写入定制简历。
- `not_an_offer` 恒为 `true`。出现 Offer 承诺或通过率预测的文字会被拦截。

单缺口重练（drill）每次针对一个缺口，重答后给出新增证据和仍缺的内容。数字类说法会与候选人原话比对，防止捏造指标。

## 接口

网页入口（需 `mode=user`，由 `career_user_runtime.py` 转发到本机引擎 18748）：

| 方法与路径 | 作用 |
| --- | --- |
| `POST /api/career-user/comprehensive-interviews` | 开始一场，返回会话视图 |
| `GET /api/career-user/comprehensive-interviews/{id}` | 读取会话 |
| `POST .../{id}/stream` | SSE 逐字获取面试官下一句，`intent` 为 `first`、`next`、`retry` |
| `POST .../{id}/turns` | 提交回答或控制指令，需要 `event_id` |
| `POST .../{id}/finish` | 结束，可带 `{"early": true}` |
| `GET .../{id}/recap` | 读取复盘 |
| `GET .../{id}/export?format=json\|markdown` | 导出复盘 |
| `POST .../{id}/drill` | 单缺口重练 |

引擎侧路径是 `/v1/comprehensive-interviews*`，路由注册在 `interview_agent/comprehensive_api.py`，请求体契约在 `comprehensive_contracts.py`（严格模型，多余字段会被拒绝）。会话标识只允许字母、数字、下划线和连字符，最长 100 位。

## 模型配置

综合面试走 `interview_agent` 的 `ModelAdapter`，由 `tools/workbench_services.py` 的 `ModelSettings` 提供。`ModelSettings` 每 5 秒左右读取一次「08 设置 › AI 接口设置」保存的服务商、模型、地址和密钥，当前任务结束后自动应用，不读取进程环境里的 `INTERVIEW_*`、`STEP_*` 变量。

「题单与本地题库」里的文字面试（`tools/interview_chat.py`，调用点在 `backend.py` 的 `_complete_interview_plan`、`_complete_interview_json`）走 vendor 的 `call_anthropic_text`。它先读 vendor 的 `config.yaml`，其中没有密钥时，才取 `offerpilot_runtime.effective_ai_config` 里挂接的设置页配置。这个挂接（`offerpilot_runtime.workbench_model`）只在用 `tools/run_career_demo.py` 完整启动时建立；只用 `run_web.sh` 或 `web/server.py` 启动时它为空，文字面试就只读 `config.yaml`。综合面试需要的 18748 引擎在只启动工作台时不存在，请求会失败（流式接口在没有 `OFFERPILOT_CAREER_USER_TOKEN` 时返回 503「综合面试服务未启动」）。两条通道的调用协议、超时、重试和错误分类各自实现，没有合并。

## 测试

- `interview_agent/tests/test_comprehensive_interview.py`：规划超时保底、二维考纲与备选池、三层防卡死、复盘与重练的确定性清洗、完整 HTTP 与 SSE 流程、追问熔断与并发会话、提示与翻资料指令。
- `interview_agent/tests/test_brief_assembler.py`：简报冻结与口径冲突。
- `tools/tests/test_comprehensive_web_bridge.py`：网页入口、路由校验、静态资源注册。

## 已知限制

- 真实模型下的出题质量、复盘质量没有自动化验证，测试用的是模拟模型。
- 面试官一次只问一个问题的约束靠提示词和结构化输出，没有对自然语言做二次校验。
- 语音输入通道在契约里有 `asr_transcript` 取值，但页面没有语音入口。
