# 模拟面试材料接口与复盘服务

Python 3.11+ 标准库实现的本地联通原型，使用 SQLite 保存不可变材料包、会话、结果和复盘草稿。默认只绑定 127.0.0.1，使用服务令牌；当前 HTTP 进程固定一个 owner，尚未对接多用户登录或实际模拟面试引擎。

## 导入已验证的公开样例

在工作区根目录运行：

```powershell
python -X utf8 -m interview_hub import-demo
```

默认数据库为 outputs/interview-hub/interview.db，默认 owner 为 local-demo。样例来自固定提交的 pallets/itsdangerous，与上一轮 UA 材料一致；仍标为公开演示，个人职责未确认，没有生成用户个人简历。

导入会重新检查原文指纹、源码坐标、UA 课程内容及导览关联。材料内容决定 material_id；同内容重复导入可复用，已有版本不可覆盖。材料包保存所需的源码片段和学习片段，不要求模拟面试重复抓取整个仓库。

## 启动与停止

在当前 PowerShell 进程设置本地服务令牌，然后启动：

```powershell
$env:INTERVIEW_HUB_TOKEN = (python -c "import secrets; print(secrets.token_urlsafe(32))").Trim()
python -X utf8 -m interview_hub serve
```

默认地址 http://127.0.0.1:18746。令牌只从指定环境变量读取，不写入 SQLite 或请求日志；--token-env 可以指定其他变量名。--db、--owner、--port 可以改变本次运行参数。按 Ctrl+C 停止服务。

服务令牌供可信的模拟面试后端使用，不交给候选人网页。当前未实现按角色区分的令牌权限；下列接口均处于同一个可信服务边界内，不是对公网的部署方案。

## 调用顺序

材料列表 → 创建固定版本会话 → 读取出题上下文 → 上游开展面试 → 回传最终回答与观察 → 生成复盘草稿 → 后续会话读取历史。

所有接口均需要 Authorization: Bearer 本地服务令牌。POST 使用 application/json，正文最大 1 MiB。

读取材料列表：

```powershell
$interviewHeaders = @{ Authorization = "Bearer $env:INTERVIEW_HUB_TOKEN" }
Invoke-RestMethod 'http://127.0.0.1:18746/v1/materials' -Headers $interviewHeaders
```

材料、会话和结果的存储返回形状分别为：

```json
{"material_id":"mat_...","payload":{},"created_at":"UTC timestamp"}
```

```json
{"session_id":"session_...","material_id":"mat_...","payload":{},"state":"in_progress","created_at":"UTC timestamp"}
```

```json
{"session_id":"session_...","payload":{},"created_at":"UTC timestamp"}
```

材料列表和详情接口只返回摘要，不采用第一种完整存储形状；会话 context 接口再返回所需材料。参考本轮真实输出文件，避免将内部 payload 与外层元数据混淆。

## 接口契约

### GET /v1/materials?limit=20&offset=0

返回当前 owner 可用材料的摘要：material_id、固定源码版本、关联声明、题目数、简历版本、演示标记和限制。limit 为 1–100，offset 为非负整数。

GET /v1/materials/{material_id} 返回单个摘要。当前没有对外开放任意材料上传接口；公开样例通过上述校验导入器进入数据库。

### POST /v1/sessions

请求示例：

```json
{
  "session_id": "interview_001",
  "material_id": "从材料列表取得的ID",
  "mode": "resume_readiness",
  "target": {"company": "目标公司", "role": "初级后端", "round": "一面"}
}
```

session_id 可省略，由服务器生成；重试时提供相同 ID 可复用原会话。target 目前支持 company、role、round，每项最长 200 字符。

mode 支持 resume_readiness 和 mock_interview。正式 mock_interview 要求材料已绑定 resume_version_id；当前公开演示没有个人简历，使用 resume_readiness。接口不会把公开项目冒充个人简历来绕过这个条件。

创建时固定 material_id、简历版本、源码版本、项目快照、目标与当时可用的历史复盘引用。相同 ID 不能换材料或目标；后续轮次产生的新反馈不会插入旧会话上下文。

### GET /v1/sessions/{session_id}/context

提供给可信模拟面试后端的出题上下文：固定会话、声明、项目证据、题目、来源限制，以及创建会话时冻结的 related_history。

题目包含 question_id、claim_id、text、evidence_ids；生成题目还包含 intent 与 reason，不包含预期事实和课程解释。不要把此服务响应原样当候选人前端页面输出。

### POST /v1/sessions/{session_id}/question-plan

Pi 首次出题后，先冻结本轮问题再开始作答。请求包含与材料完全一致的 material_id、source_commit、resume_version_id、project_snapshot_id；generation 声明 provider、model、kind（live_model 或 contract_test）。questions 含 1–5 个对象，每项只含 question_id、claim_id、text、evidence_ids、intent、reason。

intent 可用 implementation、design_tradeoff、failure_boundary、contribution、verification。每题至少引用一份本条 claim 的同版本原文证据。预期答案不能由客户端注入；相关 UA 学习片段由服务按已有引用绑定。接口验证引用与结构，不保证模型问题的语义质量。

返回包含 question_plan_id 的不可变计划。相同内容重试幂等，改题或在已结束会话补计划返回 409。GET 同路径恢复计划。计划存在时，context、evaluation-context、结果校验与复盘都采用本轮计划的问题，不改写原资料包。没有计划的已有服务调用保持原流程。

### GET /v1/sessions/{session_id}/evaluation-context

提供给可信评价模块的完整材料，包括 expected_facts 和已验证引用的 UA 学习内容。expected_facts 是模型准备的评价依据草稿，允许解释变体，不能取代源码复核或个人职责确认。

### POST /v1/sessions/{session_id}/results

面试结束时一次提交最终结果，当前不保存实时音频流或逐字实时事件。示意形状：

```json
{
  "material_id": "本会话的material_id",
  "source_commit": "本会话的源码提交",
  "resume_version_id": null,
  "answers": [
    {"question_id":"题目ID","text":"候选人回答","assistance_mode":"independent"}
  ],
  "observations": [
    {"question_id":"题目ID","status":"partial","gap_type":"understanding","notes":"上游评价模块的观察","evidence_ids":["相关证据ID"]}
  ],
  "summary": "可选的上游总结"
}
```

material_id 与 source_commit 必须回传并匹配固定上下文；resume_version_id 必须匹配。显式提供 session_id、project_snapshot_id 时也必须一致，保存时服务器写入规范值。

使用生成问题计划时还必须传回匹配的 question_plan_id，问题 ID 必须属于该计划。计划绑定在数据库写入事务中再次检查。结果可附 assessment_generation 和 corrections；复盘保留上游来源及待确认修正。

assistance_mode 可用 independent、open_book、hinted、ai_assisted。跳过可写 skipped: true；没有回答不允许记录 consistent、partial 或 conflict。

观察状态：consistent、partial、conflict、insufficient_evidence、not_assessed。缺口类别可用 understanding、expression、responsibility、metric_evidence、material_coverage。观察引用必须属于本题声明过的证据；conflict 还要求对应版本的直接源码依据。

本服务验证并保存上游结构化观察，不会仅凭回答文本自行判断对错。首次保存会将会话标为 completed；相同内容可重传，不同最终回答不能覆盖原记录。

### POST /v1/sessions/{session_id}/recap

发送空对象 {}。服务读取已保存的最终结果，生成并保存复盘草稿；重复触发直接恢复原草稿，不生成漂移的新内容。

草稿包含 what_went_well、needs_review、not_assessed、improvement_tasks、resume_suggestions 与相关历史会话。补强任务含材料、行动、完成条件和变式复测；材料不足先补证，源码冲突先核对版本和职责。

全部建议保持 pending_user_confirmation，ability_verdict 为 null，applied_to_resume 为 false。辅助作答不认证独立掌握，勾选或保存任务也不代表复测通过。

GET /v1/sessions/{session_id}/recap 恢复已保存草稿。GET /v1/sessions/{session_id}/results 恢复原始最终结果；GET /v1/sessions/{session_id} 查看固定会话及状态。

### GET /v1/history?claim_id=声明ID&limit=20&offset=0

返回当前 owner 下关联的材料、会话、question_plan、最终结果与复盘。未结束会话仍可出现，result／recap 为 null，不能当作已经完成的经验。

会话 context 中 related_history 最多保留 20 条关联声明的既有复盘引用，并保留原始版本、目标及确认状态；不会自动推导公司整体规律或把旧版本准备状态转移到新版本。

### 状态码

正常读取为 200，新建或幂等写入为 201，已缓存复盘重取为 200。401 表示令牌不匹配，400 表示格式／引用／版本不符，404 表示记录不存在，409 表示试图改变不可变记录。错误响应不回显回答或源码正文。

## 复现本轮验收

```powershell
python -X utf8 验证/interview_hub_smoke.py
python -X utf8 -m unittest discover -s tests -v
```

HTTP 验收使用公开项目和明确标注的合成回答／观察，创建两轮会话。令牌在进程内生成，不写入验收文件；验收结束关闭临时服务器，保留 SQLite 与 JSON 结果。它不运行真实面试引擎，也不评估用户能力。

完整实现范围、产物与限制见[设计及验收记录](../定制简历_模拟面试资料接口与复盘服务_v0.7.md)。

当前编排与模型接入见 [Python 运行说明](../interview_agent/README.md)；复盘服务自身仍只汇总上游观察，模型观察是单独的调用阶段。历史 Pi 原型已归档至验证目录。
