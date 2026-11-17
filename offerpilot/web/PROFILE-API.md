# 个人资料接口（PROFILE-API）

工作台把「个人资料」作为本地结构化事实源，供招呼语、模拟面试、定制简历与筛选偏好复用。确认后的资料保存于本机 `web/data/<mode>/profile.json`，不自动投递；用户发起的简历导入会调用已配置模型解析全文（见第 3 节）。真实资料不会进入 Git 仓库（`web/data/` 已忽略）。

- 服务地址：`http://127.0.0.1:8766`（仅 loopback）
- 数据模式：`demo`（虚构演示）或 `user`（本机真实资料）
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

页面支持点击选择或拖入 PDF、DOCX、Markdown、TXT（最大 5 MB、60000 字符，PDF 最多 30 页）。本机提取文字后，完整文字发送给已配置的 `step-5-preview` Agent，经严格结构校验与原文核对后返回建议，不保存原始文件。加密或扫描图片 PDF 暂不支持，请先转成可复制文字的文件。TXT/Markdown 支持 UTF-8、带 BOM 的 UTF-16 和 GB18030。

返回 `profile` 建议、`filename`、`source_text` 解析原文、`warnings` 和 `generation`。识别基本信息、求职意向、教育、工作/实习、项目经历、技能和简介；经历按条目附原文片段进行服务端核对，无法核对的字段留空并提示，不补造日期或成果。页面更新识别到的字段与经历列表，未识别的部分保留原资料，取消真实性勾选；**不会自动保存**。用户可逐项编辑，页面要求核对并勾选真实性确认后，仍通过 `save-profile` 保存。Agent 超时、不可用或返回无效结果时提示重试，原表单与已保存资料不变。

个人 Agent 内部接口为鉴权的 `POST /v1/career/profile-import`（仅个人服务安装此路由），接收 `{"text":"完整简历文字"}`。复用现有 Python 模型适配器的 `profile_extract` 决策阶段，无文件读写、保存资料或面试状态变更。

岗位采集的评分简历和 ATS 检查入口也支持拖入；前者沿用 PDF/DOCX/MD 上传流程，后者仅选择 PDF，仍需点击「检查 PDF」，不会发送给模型。

兼容旧调用：同时省略 `filename` 与 `content_base64` 时，读取本机 `workspace/resume.md`。演示模式始终返回 `400`，不会读取文件或导入真实资料。

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

新增的公开项目核验接口不读取本接口或 `profile.json`，只在 demo 模式处理公开样例与本轮回答。该能力独立于本节早期个人资料工具的离线边界；模型与运行数据说明见 [CAREER-AGENT-API](CAREER-AGENT-API.md)。个人资料字段、完整度和保存语义保持原样。

- 仅绑定 `127.0.0.1`，校验 `Host` 与 `Origin` 为 loopback。
- 不接收凭据、Cookie、平台账号或第三方个人信息。
- 不提供自动投递、自动发送、平台抓取或浏览器接管。
- 真实 `profile.json` 位于 `web/data/user/`，已被 `.gitignore` 忽略；公开仓库只包含代码与虚构 demo 资料。

全局 Agent 仅把精简后的专业资料传入决策阶段。对话内导入资料先生成待确认提案，经用户确认并校验原资料快照后才调用既有 `save_profile`；重复确认使用持久化回执，不改变本接口原有保存字段。详见 [WORKBENCH-AGENT-API](WORKBENCH-AGENT-API.md)。
