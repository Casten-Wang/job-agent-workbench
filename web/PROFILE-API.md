# 个人资料接口（PROFILE-API）

工作台把「个人资料」作为本地结构化事实源，供招呼语、模拟面试、定制简历与筛选偏好复用。确认后的资料保存于本机 `web/data/user/profile.json`，不自动投递；用户发起的简历文件导入会调用已配置模型解析全文（见第 3 节）。真实资料不会进入 Git 仓库（`web/data/` 已忽略）。

- 服务地址：`http://127.0.0.1:8766`（仅 loopback）
- 数据模式：只有一个模式 `user`（本机真实资料）；`mode` 参数保留为兼容字段，其他取值按 `user` 处理
- 版本：`1.0`

## 1. 读取

```http
GET /api/profile?mode=user
```

响应：

```json
{
  "ok": true,
  "mode": "user",
  "profile": {
    "version": 1,
    "updated_at": "2026-11-14T16:40:00+08:00",
    "truth_confirmed": true,
    "basic": {
      "name": "…",
      "phone": "…",
      "email": "…",
      "city": "上海",
      "wechat": "…",
      "links": "…"
    },
    "job_intent": {
      "titles": ["产品经理"],
      "cities": ["上海", "杭州"],
      "salary_min": 15000,
      "salary_max": 25000,
      "job_type": "全职",
      "availability": "一个月内"
    },
    "education": [
      {"school": "…", "major": "…", "degree": "本科", "start": "2018-09", "end": "2022-06", "summary": "…"}
    ],
    "experiences": [
      {"company": "…", "title": "…", "start": "…", "end": "…", "summary": "…"}
    ],
    "projects": [
      {"name": "…", "role": "…", "start": "…", "end": "…", "summary": "…"}
    ],
    "skills": {"tools": ["Axure"], "strengths": ["需求分析"]},
    "summary": "…",
    "excluded_terms": ["外包"],
    "completeness": {
      "percent": 100,
      "level": "ready",
      "ready": true,
      "sections": [{"key": "basic", "label": "基本信息", "weight": 25, "done": true, "hint": "…"}],
      "missing": []
    },
    "has_content": true
  },
  "guarantees": {
    "local_only": true,
    "contact_fields_in_drafts": false,
    "auto_submit": false
  }
}
```

`completeness.level`：

- `empty`：尚未填写
- `partial`：部分字段缺失
- `ready`：完整度 ≥ 80% 且已勾选事实确认

## 2. 写入

统一动作入口：

```http
POST /api/action
Content-Type: application/json

{
  "action": "save-profile",
  "mode": "user",
  "profile": {
    "basic": {"name": "…", "email": "…", "city": "上海"},
    "job_intent": {"titles": ["产品经理"], "cities": ["上海"]},
    "skills": {"tools": ["Axure"], "strengths": ["需求分析"]},
    "summary": "…",
    "truth_confirmed": true
  }
}
```

服务端只保留已知字段，并对文本、列表长度与薪资数值做边界校验；未知字段会被丢弃。保存后返回规范化后的 `profile` 与 `completeness`。

## 3. 从本地简历导入建议

```http
POST /api/action
{"action": "import-profile-cv", "mode": "user", "filename": "resume.pdf", "content_base64": "<文件原始字节的 Base64>"}
```

页面支持点击选择或拖入 PDF、DOCX、Markdown、TXT（最大 5 MB、60000 字符，PDF 最多 30 页）。本机提取文字后发送给已配置模型的 `profile_extract` 阶段解析，不保存原始文件。加密 PDF 暂不支持。PDF 文字层不可用（字体无标准编码导致的乱码，或纯图片扫描件）时，后端用 macOS 自带 `sips` 把前 6 页渲染成图片，交给已配置的多模态模型逐字转写（`web/resume_vision.py`，不保存图片），转写文字再走同一条抽取链路，响应 `text_origin` 为 `image`；没有渲染器或模型不支持图片时，返回原先的「文字层乱码/无文字，请重新导出」提示并附上失败原因。TXT/Markdown 支持 UTF-8、带 BOM 的 UTF-16 和 GB18030。

### 3.1 长简历分段与原文核对

- 60000 字以内的简历照常一次解析；超过约 7000 字时按空行切分为每段不超过 6000 字的若干段，最多 3 路并发解析，再合并基本信息、技能与经历条目（按原文去重，每类最多 20 条）。
- 某一段的输出被截断或未通过校验时，程序把该段对半再试（最多 3 层）；仍失败只影响该段，其余段的结果照常返回。
- 每条教育/工作/项目记录以模型给出的「开头标题行」为锚点，在原文中定位并截取整段内容作为描述；标题行与该条的字段都在这一段原文中核对，核对不到的字段留空并提示。
- 核对时忽略排版差异：空白、列表符号、软连字符、行尾连字符断行、全角/半角与大小写都不影响匹配，PDF 换行或全角数字因此不会让整条记录被丢弃。
- 仍无法定位的条目和失败段落的原文放进 `unmatched_sections`，供用户对照手动补全；不引入任何「失败后按本地正则自动填字段」的回退。

### 3.2 响应字段（只增不改）

`profile` 建议、`filename`、`source_text` 解析原文、`warnings`、`generation` 保持不变，新增：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `failure` | string \| null | 需要用户重试或手工补全的原因；`null` 表示模型完整返回 |
| `partial` | bool | 是否有段落或条目未能解析 |
| `text_origin` | string | `text_layer`（直接读取文字）或 `image`（文字层不可用，经图片识别得到，界面会提示重点核对）；新增键 |
| `unmatched_sections` | list | `[{"section": "工作经历", "text": "原文段落"}]`，单段最多 6000 字、合计最多 20000 字、最多 20 项 |

`failure` 取值：

- `truncated`：模型输出被截断
- `timeout`：模型响应超时
- `invalid_output`：模型结果未通过校验
- `model_unconfigured`：未配置模型或密钥
- `model_unavailable`：模型服务暂时不可用
- `no_supported_fields`：未识别到可核对的内容

`failure` 非空时，接口仍返回 200（`ok: true`）与本地解析的 `source_text`，未识别字段为空，`message` 是该情形的中文说明；原表单与已保存资料不变。`ok` 只在本地输入错误（文件名、大小、格式、编码）时为 `false`。

识别基本信息、求职意向、教育、工作/实习、项目经历、技能和简介；经历按条目在原文中核对，无法核对的字段留空并提示，不补造日期或成果。**不会自动保存**。页面更新识别到的字段与经历列表，未识别的部分保留原资料，取消真实性勾选；用户逐项编辑并勾选真实性确认后，仍通过 `save-profile` 保存。

个人 Agent 内部接口为鉴权的 `POST /v1/career/profile-import`（仅个人服务安装此路由），接收 `{"text":"完整简历文字"}`，返回同样的解析结果（含 `failure`、`partial`、`unmatched_sections`）。复用现有 Python 模型适配器的 `profile_extract` 决策阶段，无文件读写、保存资料或面试状态变更。

岗位采集的评分简历和 ATS 检查入口也支持拖入；前者沿用 PDF/DOCX/MD 上传流程，后者仅选择 PDF，仍需点击「检查 PDF」，不会发送给模型。

兼容旧调用：同时省略 `filename` 与 `content_base64` 时，沿用下面的本机 Markdown 读取逻辑，行为与字段不变。

读取本机 `workspace/resume.md` 或采集页已上传的 Markdown 简历（较新的一份），返回可识别的姓名、邮箱、电话、城市、技能词与一段简介建议；**不会自动保存**。

导入来源与解析范围（只增不改，旧字段保持原样）：

- 来源：比较 `workspace/resume.md` 与采集页已上传的 Markdown 简历的修改时间，取较新的一份——采集页上传的 `.md` 比 workspace 文件新时用上传件，否则用 `workspace/resume.md`；时间相同取 workspace。上传件多个时运行时目录内的 `resume.md` 优先，否则最近修改的 `.md`。两处都只读取，不改动其内容；都没有返回 `404`；只有非 `.md` 的上传简历时返回 `400` 并提示改用 `.md` 或手动填写。
- 响应新增 `source` 字段，标明本次读取的是哪一份简历。
- 解析 Markdown 的 `##` 段落：`Professional Summary` / 个人简介 → `summary`；`Work Experience` / 工作经历 / 实习经历 → `experiences`（`### 公司 — 城市` + `**职位**` + 日期行 + `-`/`*`/`•` 要点）；`Projects` / 项目经历 → `projects`；`Education` / 教育经历 / 教育背景 → `education`；`Skills` / 技能 → `skills.tools`（与内置词表命中合并去重）。
- 日期支持 `2019年10月 - 至今`、`2018.03-2018.06`、`2019-03 ~ 2019-06` 等写法，统一输出为 `YYYY-MM` 或 `至今`。
- 要点中的 `[[ILLEGIBLE]]` 标记会被去掉，保留可读部分；去掉后几乎没有文字的要点直接丢弃。
- 解析不到的字段保持空值，不推断期望薪资，`job_intent.titles` 留空。联系方式（电话/邮箱）照常提取进 `basic`。

### 3.3 资料状态字段（GET 与快照的只增字段）

`GET /api/profile` 的 `profile` 对象，以及工作台快照的 `profile` 键，新增两个只读字段：

| 字段 | 含义 |
| --- | --- |
| `saved` | 本机是否已通过 `save-profile` 写入过 `profile.json`。`false` 表示还只是空白或未保存的草稿来源 |
| `cv_available` | 本机是否有可读的 Markdown 简历可供导入 |

页面据此决定是否在首次进入时自动预填一次草稿：仅当 `saved=false` 且 `cv_available=true` 时，预填结果只进入表单、不保存，并要求用户核对后再点「保存」。已保存过的资料（`saved=true`）不会被自动覆盖。

## 4. 被哪些模块使用

| 模块 | 用法 |
| --- | --- |
| 生成招呼语 `prepare` | 优先用资料中的技能/项目/简介生成草稿；联系方式不进入草稿 |
| 模拟面试 `worksheet` | 题单头部显示资料完整度与项目名；题目仍只来自本地题库 |
| 筛选偏好 | 目标城市与排除词会覆盖 `config.target_cities` / `excluded_terms` 的默认值 |
| 定制简历 | 作为岗位定制的事实源；仍不新增数字或经历 |

## 5. 边界

定制简历当前可直接使用已确认项目材料与 user profile 生成，无需面试会话。个人资料不足时提示补全；不会自动填造姓名、学历或经历。模拟面试暂保留接口。

个人简历预览会从 user profile 读取经用户确认的资料并冻结进简历版本；不接受浏览器另传一份 profile。联系方式用于本机最终简历正文；正式面试仅发送冻结版本的专业资料字段，不读取 basic 姓名/联系方式。现有字段与保存语义不变，详见 [PERSONAL-CAREER-API](PERSONAL-CAREER-API.md)。

新增的公开项目核验接口不读取本接口或 `profile.json`，只处理固定公开样例与本轮回答，接口参数沿用单一 `user` 模式。该能力独立于本节早期个人资料工具的离线边界；模型与运行数据说明见 [CAREER-AGENT-API](CAREER-AGENT-API.md)。个人资料字段、完整度和保存语义保持原样。

- 仅绑定 `127.0.0.1`，校验 `Host` 与 `Origin` 为 loopback。
- 不接收凭据、Cookie、平台账号或第三方个人信息。
- 不提供自动投递、自动发送、平台抓取或浏览器接管。
- 唯一的 `profile.json` 位于 `web/data/user/`，已被 `.gitignore` 忽略；公开仓库只包含代码、测试夹具与虚构 `demo/` 样例文件。

全局 Agent 仅把精简后的专业资料传入决策阶段。对话内导入资料先生成待确认提案，经用户确认并校验原资料快照后才调用既有 `save_profile`；重复确认使用持久化回执，不改变本接口原有保存字段。详见 [WORKBENCH-AGENT-API](WORKBENCH-AGENT-API.md)。
