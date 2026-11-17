# 定制简历 Agent 最小可行实现 v1.0

日期：2026-11-17

## 结论

当前项目已经有一条可复用的确定性业务链：

```text
GitHub 授权 → 固定 commit 快照 → 源码证据 → Agent 整理候选表述
→ 用户逐条确认 → 冻结材料 → 生成简历草稿 → 用户确认 → 保存不可变版本
```

这条链应该作为 qgent 的第一条业务流程。不要再创建一套新的 LangGraph 业务系统，也不要把 `CareerService` 改造成由模型自由决定的 Agent。

qgent 在这里的最小职责只有三件事：

1. 把用户请求转成一个明确的任务上下文；
2. 在受限阶段调用模型，生成结构化的候选项目表述；
3. 把模型结果交给确定性校验和用户确认。

权限、证据绑定、用户确认、简历正文生成、版本保存和幂等性继续由 Python 代码负责。

## 当前代码与目标边界

当前实现已经覆盖了大部分 MVP：

- `interview_agent/model_adapter.py` 负责模型请求、单工具调用、结构化解析、有限重试和错误分类。
- `interview_agent/decisions.py` 已经有 `ProjectUnderstanding`、`Plan`、`Intent`、`Observation`、`Hint` 等严格输出 Schema。
- `interview_agent/career.py` 已经实现项目准备、用户确认、简历草稿和版本保存。
- `interview_agent/graph.py` 已经实现可恢复的面试状态图：`bootstrap → wait → classify → act → evaluate/hint/finalize`。
- `interview_agent/api.py` 已经把业务 SQLite 与 LangGraph checkpoint 分开。
- `offerpilot/web/career_user.js` 已经连接个人项目、确认经历、生成预览和保存版本的页面流程。

因此第一期不需要再增加一个“总 Agent”。需要补的是边界命名、工具契约和运行上下文，让现有代码能被 qgent 稳定调用。

## 推荐目录结构

第一期保持现有文件不拆分，只增加两个薄模块；面试图和个人项目服务仍由现有文件拥有。

```text
interview_agent/
├── api.py                         # FastAPI 入口、鉴权、生命周期
├── model_adapter.py               # ModelGateway：模型调用与结构化输出
├── decisions.py                   # Agent 决策 Schema 与阶段指令
├── agent_contracts.py              # 新增：RunContext、ToolSpec、ToolResult
├── career_tools.py                 # 新增：CareerService 的 Agent 适配器
├── career.py                       # 确定性个人项目与简历业务服务
├── graph.py                        # 已有：面试工作流 LangGraph
├── repository.py                   # 材料、会话和版本读取边界
├── models.py                       # HTTP 输入模型
└── observability.py                # 脱敏 trace

offerpilot/
└── web/
    ├── career_user_runtime.py      # 已有：个人服务同源转发与 owner 隔离
    ├── career-user.js              # 已有：个人项目 UI 流程
    └── PERSONAL-CAREER-API.md      # 已有：接口契约
```

`agent_contracts.py` 和 `career_tools.py` 只做接口适配，不复制 `CareerService` 的规则，也不引入另一套状态存储。

## 核心接口

### 运行上下文

```python
# interview_agent/agent_contracts.py
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class RunContext:
    owner: str
    trace_id: str
    task: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    model_generation: Mapping[str, str] = field(default_factory=dict)
    budget: int = 1


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: Mapping[str, Any] | None = None
    error_code: str | None = None
    retryable: bool = False
    evidence_ids: tuple[str, ...] = ()
```

`RunContext` 不从模型输出中读取。owner、权限、模型版本和预算由 API 或运行时注入，避免模型伪造身份和权限。

### 工具接口

```python
from typing import Protocol, Type
from pydantic import BaseModel


class CareerTool(Protocol):
    name: str
    input_model: Type[BaseModel]
    risk: str                 # read | propose | confirm | commit
    requires_confirmation: bool

    async def invoke(self, context: RunContext, arguments: BaseModel) -> ToolResult:
        ...
```

现阶段不需要做通用工具注册中心。qgent 根据任务显式传入工具白名单；如果只有 `prepare` 阶段，就只注册 `submit_prepare` 这一类结构化决策工具。

### Agent Runtime 接口

```python
class AgentRuntime(Protocol):
    async def run(
        self,
        *,
        context: RunContext,
        task: str,
        input_data: Mapping[str, Any],
        allowed_tools: tuple[CareerTool, ...],
    ) -> ToolResult:
        ...
```

第一期可以直接由现有 `ModelAdapter.decide(stage, value)` 实现这个接口。不要为了接口统一而立即改写 `ModelAdapter`；先在 `career_tools.py` 做适配，保持已有 checkpoint 中的 `generation` 形状不变。

## 第一条业务流程的工具契约

### 1. `prepare_project`

这是一个外部 API 触发的应用命令，不直接暴露给模型。它负责创建后台任务并冻结用户声明。

```json
{
  "name": "prepare_project",
  "risk": "propose",
  "input": {
    "repository": "owner/repo",
    "role": "后端开发",
    "jd": "岗位描述，可为空",
    "contribution": "用户自述负责范围",
    "confirmed": true,
    "model_consent": true
  },
  "output": {
    "project_id": "project_xxx",
    "status": "preparing"
  }
}
```

确定性检查包括：仓库格式、字段长度、用户确认、模型发送同意、GitHub 授权和 owner 隔离。

### 2. `submit_prepare`

这是当前 `ModelAdapter` 通过 Chat Completions function tool 调用的唯一 Agent 工具。它的 Schema 已由 `ProjectUnderstanding` 生成。

```json
{
  "name": "submit_prepare",
  "risk": "propose",
  "input": {
    "summary": "基于证据的项目摘要",
    "positioning": "与目标岗位的简短定位",
    "claims": [
      {
        "text": "问题/演进 → 个人动作与机制 → 约束或边界 → 证据",
        "pillar": "状态建模",
        "fit_reason": "为什么匹配目标岗位",
        "boundary": "个人职责边界",
        "risk": "仍需用户核对的地方",
        "evidence_ids": ["ev_1", "ev_2"]
      }
    ]
  }
}
```

硬约束：

- `claims` 最多 5 条，每条不超过 320 字；
- 每条都必须引用当前固定 commit 的 `evidence_ids`；
- 不生成无法由证据支持的指标、收入、用户数或性能提升；
- 不把仓库所有权、提交数量或模型生成结果当成个人独立贡献；
- `claim_id`、`material_id` 和 `project_snapshot_id` 由程序生成，模型不能提供。

### 3. `confirm_project_claims`

这是人类确认命令，不允许模型调用。

```json
{
  "project_id": "project_xxx",
  "claim_ids": ["claim_xxx"],
  "confirmed": true
}
```

成功条件：项目状态为 `ready`，所有 claim_id 属于该项目，列表非空且无重复。成功后由 `CareerService.confirm()` 创建不可变的个人材料快照。

### 4. `create_resume_draft`

这是确定性应用命令，不需要 Agent。

```json
{
  "material_id": "mat_xxx",
  "profile": {
    "truth_confirmed": true,
    "basic": {"name": "候选人"},
    "education": [],
    "experiences": [],
    "skills": {"tools": [], "strengths": []}
  }
}
```

服务端只接受已确认的个人材料，按材料中的 claim 文本和用户确认的个人事实生成 Markdown。第一期不让模型改写简历正文，这能保证来源可追溯和测试可重复。

### 5. `save_resume_version`

这是提交副作用的最后一步，需要用户确认。

```json
{
  "draft_id": "draft_xxx",
  "confirmed": true
}
```

保存必须幂等：同一个草稿的重复请求返回同一个 `resume_version_id`，不能生成第二个版本或覆盖旧版本。

## LangGraph 节点边界

### 已有面试图：继续保留

`interview_agent/graph.py` 当前的节点边界已经合理：

```text
bootstrap
  → wait_for_user [interrupt]
  → classify [Agent: intent]
  → act [确定性状态转移]
  ├→ hint [Agent: hint]
  ├→ evaluate [Agent: observation + 证据校验]
  ├→ wait_for_user
  └→ finalize [确定性结果落库]
```

边界规则：

- `classify` 只输出意图，不推进业务状态；
- `act` 只执行确定性状态转移，不调用模型；
- `evaluate` 只产生待复核观察，不决定人的能力或真实性；
- `finalize` 只保存结果和复盘，不修改已确认材料；
- `wait_for_user` 是唯一的人机中断点。

这张图已经是 qgent 在“项目核验面试”场景下的最小 Agent Runtime，不需要再包一层 supervisor。

### 第一条简历流程：暂时不强行做成 LangGraph

“项目准备 → 用户确认 → 简历草稿 → 保存版本”目前是固定路径，而且已经由多个 HTTP 请求和 SQLite 状态自然切分。第一期直接使用 `CareerService` 和现有 API，比把固定 CRUD 流程改写成图更简单、更可靠。

如果以后需要一个可暂停、可恢复、可审计的单次任务图，再按下面的边界拆分：

```text
load_request          [确定性：校验 owner / 权限 / 字段]
  → freeze_repository [确定性：固定 commit、下载、过滤、证据配额]
  → understand_project [Agent：submit_prepare]
  → validate_claims    [确定性：Schema、证据引用、字数、禁用指标]
  → await_confirmation [interrupt：用户逐条确认]
  → freeze_material    [确定性：生成 material_id、保存材料]
  → build_draft        [确定性：按 profile + claims 生成 Markdown]
  → await_save         [interrupt：用户确认版本]
  → save_version       [确定性：事务、幂等、生成 resume_version_id]
```

这张图中的 Agent 节点只有一个：`understand_project`。所有其他节点都不应让模型决定下一步。

## 第一条业务流程的落地步骤

### 第一步：锁定现有主链

以个人模式页面为入口，沿用以下接口，不增加新入口：

```text
POST /api/career-user/projects
GET  /api/career-user/projects/{project_id}
POST /api/career-user/projects/{project_id}/confirm
POST /api/career-user/resume-drafts
POST /api/career-user/resume-drafts/{draft_id}/save
GET  /api/career-user/resumes/{resume_version_id}
```

这条链已经在 `offerpilot/web/career-user.js` 和 `interview_agent/career_api.py` 中存在。第一期只补 trace 字段和统一错误码，不改已有 JSON 字段含义。

### 第二步：补薄适配层

新增 `agent_contracts.py` 和 `career_tools.py`：

- `agent_contracts.py` 定义 `RunContext`、`ToolResult` 和工具协议；
- `career_tools.py` 把 `CareerService` 的方法适配成工具，但不复制规则；
- `ModelAdapter` 继续负责 `submit_prepare` 的单工具调用和 Pydantic 校验；
- `CareerService._prepare()` 只接收已校验的 `ProjectUnderstanding`。

### 第三步：把一次准备任务的证据边界记录完整

项目状态进入 `ready` 时必须同时具备：

- `repository`；
- `source_commit`；
- `project_snapshot_id`；
- `coverage`；
- `evidence`；
- `claims`；
- `model_generation`；
- `trace_id`。

缺少任意一项都不能进入用户确认页面。这样可以把 Agent 输出和固定源码版本绑定起来。

### 第四步：只给 Agent 一个阶段工具

`prepare` 阶段只注册 `submit_prepare`。不要同时暴露 GitHub 原始 API、数据库查询、写文件、简历保存或任意 HTTP 工具。

Agent 输入只包含：

- 目标岗位与 JD；
- 用户自述职责；
- 固定 commit；
- 程序筛选的源码证据；
- 任务规则。

外部文本和源码都作为数据，不作为指令。模型结果必须先通过 `ProjectUnderstanding`，再通过证据引用校验。

### 第五步：把用户确认作为硬闸门

用户没有逐条确认前：

- 不创建个人材料；
- 不生成正式简历版本；
- 不开始正式模拟面试；
- 不把候选表述标记为本人事实。

确认后生成的 `material` 是新的不可变快照。后续修改必须产生新 `material_id` 或新简历版本，不能覆盖原记录。

### 第六步：保持草稿生成确定性

第一期继续使用 `CareerService.draft()` 生成 Markdown，不让 Agent 改写最终正文。这样可以验证：

```text
同一 material_id + 同一 profile → 同一 markdown_sha256
```

如果以后需要语言润色，把润色放在 `build_draft` 之后，输出新的待确认草稿，不能直接覆盖来源事实。

### 第七步：补最小验收集

至少覆盖下面八个用例：

1. Agent 引用不存在的 evidence_id，项目进入失败，不进入确认页面；
2. Agent 生成数字指标，按现有规则拒绝；
3. 用户确认未知 claim_id，返回 400；
4. 未确认个人资料，不能生成草稿；
5. 草稿重复保存返回同一个版本；
6. 旧材料生成新版本时，旧版本正文不变；
7. 模型版本变化不能恢复旧面试 checkpoint；
8. 外部文本包含伪指令时，不能改变工具白名单或业务状态。

## 第一阶段的完成定义

满足以下条件即可认为 qgent 的第一条业务流程完成：

- 用户可以从 GitHub 授权进入个人项目流程；
- Agent 只负责生成有证据引用的候选表述；
- 用户可以逐条确认或拒绝表述；
- 只有确认后的材料能生成简历草稿；
- 保存版本幂等且不可覆盖旧版本；
- 每个项目都能追溯到固定 commit、模型版本和 trace_id；
- 现有 `interview_agent/tests` 和 OfferPilot 根测试保持全绿。

## 暂不做的内容

第一期明确不做：

- 多 Agent 协作；
- Agent 自主决定是否写入简历；
- 让模型直接访问数据库或 GitHub 原始 API；
- 把所有 LangChain 类型重新封装；
- 为固定简历流程增加 supervisor 或复杂 planner；
- 让模型自动判断个人贡献已经被证明；
- 用向量库替代当前固定 commit 和证据引用。

这些能力只有在第一条流程的成功率、拒绝率、恢复和评测数据证明有必要时再增加。

