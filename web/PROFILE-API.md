# 个人资料接口（PROFILE-API）

工作台把「个人资料」作为本地结构化事实源，供招呼语、模拟面试、定制简历与筛选偏好复用。数据只写入本机 `web/data/<mode>/profile.json`，不联网、不投递；真实资料不会进入 Git 仓库（`web/data/` 已忽略）。

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
{"action": "import-profile-cv", "mode": "user"}
```

只读取本机 `workspace/resume.md`，返回可识别的姓名、邮箱、电话、城市、技能词与一段简介建议；**不会自动保存**。演示模式返回 `400`，避免把真实简历写进 demo 数据。

## 4. 被哪些模块使用

| 模块 | 用法 |
| --- | --- |
| 生成招呼语 `prepare` | 优先用资料中的技能/项目/简介生成草稿；联系方式不进入草稿 |
| 模拟面试 `worksheet` | 题单头部显示资料完整度与项目名；题目仍只来自本地题库 |
| 筛选偏好 | 目标城市与排除词会覆盖 `config.target_cities` / `excluded_terms` 的默认值 |
| 定制简历 | 作为岗位定制的事实源；仍不新增数字或经历 |

## 5. 边界

- 仅绑定 `127.0.0.1`，校验 `Host` 与 `Origin` 为 loopback。
- 不接收凭据、Cookie、平台账号或第三方个人信息。
- 不提供自动投递、自动发送、平台抓取或浏览器接管。
- 真实 `profile.json` 位于 `web/data/user/`，已被 `.gitignore` 忽略；公开仓库只包含代码与虚构 demo 资料。
