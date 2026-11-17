# 个人资料接口（PROFILE-API）

工作台把「个人资料」作为本地结构化事实源，供招呼语、模拟面试、定制简历与筛选偏好复用。数据只写入本机 `web/data/user/profile.json`，不联网、不投递；真实资料不会进入 Git 仓库（`web/data/` 已忽略）。

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
{"action": "import-profile-cv", "mode": "user"}
```

只读取本机 `workspace/resume.md`，返回可识别的姓名、邮箱、电话、城市、技能词与一段简介建议；**不会自动保存**。

导入来源与解析范围（只增不改，旧字段保持原样）：

- 来源：优先 `workspace/resume.md`；不存在时回退到采集页已上传的 Markdown 简历（运行时目录内的 `resume.md` 优先，否则最近修改的 `.md`，只读取，不改动其内容）。两处都没有返回 `404`；只有非 `.md` 的上传简历时返回 `400` 并提示改用 `.md` 或手动填写。
- 响应新增 `source` 字段，标明本次读取的是哪一份简历。
- 解析 Markdown 的 `##` 段落：`Professional Summary` / 个人简介 → `summary`；`Work Experience` / 工作经历 / 实习经历 → `experiences`（`### 公司 — 城市` + `**职位**` + 日期行 + `-`/`*`/`•` 要点）；`Projects` / 项目经历 → `projects`；`Education` / 教育经历 / 教育背景 → `education`；`Skills` / 技能 → `skills.tools`（与内置词表命中合并去重）。
- 日期支持 `2019年10月 - 至今`、`2018.03-2018.06`、`2019-03 ~ 2019-06` 等写法，统一输出为 `YYYY-MM` 或 `至今`。
- 要点中的 `[[ILLEGIBLE]]` 标记会被去掉，保留可读部分；去掉后几乎没有文字的要点直接丢弃。
- 解析不到的字段保持空值，不推断期望薪资，`job_intent.titles` 留空。联系方式（电话/邮箱）照常提取进 `basic`。

### 3.1 资料状态字段（GET 与快照的只增字段）

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

- 仅绑定 `127.0.0.1`，校验 `Host` 与 `Origin` 为 loopback。
- 不接收凭据、Cookie、平台账号或第三方个人信息。
- 不提供自动投递、自动发送、平台抓取或浏览器接管。
- 唯一的 `profile.json` 位于 `web/data/user/`，已被 `.gitignore` 忽略；公开仓库只包含代码、测试夹具与虚构 `demo/` 样例文件。
