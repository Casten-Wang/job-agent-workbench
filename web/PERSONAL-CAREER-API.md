# 个人经历与定制简历 v0.4

2026-11-16。当前优先完成定制简历，模型继续使用 `step-5-preview`。模拟面试暂保留接口和历史记录，页面显示预留说明；生成简历不再依赖面试或复盘。

## 两类导入入口（2026-11-17）

定制简历新增“GitHub 项目”与“自主导入经历 / 作品集”。自主导入不查询 GitHub 连接，不要求 OAuth 配置，适用于产品、运营、设计等岗位。当前每次整理一段实习、工作、项目或作品集；个人资料中的教育、其他工作经历与技能继续带入。

自主填写名称、目标岗位、背景和本人贡献；公司、职位、起止时间、成果、作品集链接与 JD 可选。支持从含文字层的 PDF、DOCX、Markdown、TXT 提取补充原文（单文件 5 MB、正文 20000 字符以内）。文件只在本机提取，核对并授权整理后才将文字发给模型；作品集 URL 仅作引用保留，不自动访问。

原始字段与材料文字按内容 SHA-256 冻结，沿用项目准备记录与逐条确认、草稿、不可变版本流程。`source_type: manual` 标识自主材料，`source_commit` 在该类型下为材料内容哈希，不是 Git commit；`project_snapshot_id` 使用 `experience:` 前缀。原文证据标记 `verification_scope: user_supplied`，每条改写保留可核对的 `source_quote`，不宣称独立核验。数字缺乏相应引文支持时拒绝并要求模型修复。

实习和工作进入“实习与工作经历”，作品集进入“作品集”，普通项目进入“项目经历”。导入材料独立保存，修改与重试会产生新准备记录，已保存简历不覆盖。

- `POST /api/career-user/experience-text?mode=user`：`{filename,content_base64}`，仅本机提取文字并返回 `{text}`，不保存原文件、不调用模型。
- `POST /api/career-user/experience-import?mode=user`：`kind` 为 `internship/work/project/portfolio`；字段为 `name,organization,position,start,end,role,jd,context,contribution,outcome,source_text,portfolio_url,confirmed,model_consent`。返回 202 与 `project_id`，通过现有 `/projects/{id}` 读取整理进度并逐条确认。

Python 引擎位于本仓库 `interview_agent/`，新增逻辑在 `interview_agent/experience.py`、`career.py` 与 `career_api.py`；启动器需要使用这份更新后的引擎。

## 简历模板（2026-11-17）

预览支持 `professional`（专业墨蓝，默认）和 `classic`（经典黑白）两款 A4 单栏模板。模板偏好只保存在本机浏览器，切换不修改已保存正文、版本 ID 与内容哈希。打印及 PDF 地址可增加 `template=professional` 或 `template=classic`；未知模板和额外导出参数会被拒绝。Markdown 继续下载原始正文。

两款模板统一姓名、求职意向、联系方式、栏目、经历标题、日期和贡献标签的层级。墨蓝版使用微软雅黑，黑白版使用宋体正文与黑体标题；PDF 嵌入本机字体，支持自然分页、标题与后续正文关联及页码。预览与打印共用 `career-resume.css`，PDF 与打印共用 `resume_layout.py` 的正文结构。排版样例均为虚构材料，不写入个人资料或简历版本。

简历正文带入已确认的姓名、电话、邮箱、城市、微信、个人链接、简介、教育、工作及个人资料中已有的其他项目；与本次选定经历同名的旧项目不重复加入。GitHub 项目另附仓库地址，自主材料保留作品集地址。预览、打印和 PDF 将有效 HTTP/HTTPS 地址生成为可点击链接，链接只作引用，不在生成时自动访问。旧版正文保持原样，补全字段需使用“用最新个人资料生成新版”。

## 首次连接 GitHub

按 README「启动」完整启动后，打开工作台，选择 **05 定制简历 → 首次配置 GitHub 登录应用**。

该启动器使用仓库内的 `interview_agent` 引擎，不是独立打包的 OfferPilot 发行版。引擎依赖记录于 `interview_agent/requirements.txt`，Windows GitHub HTTPS 使用 [truststore 的原生系统证书上下文](https://truststore.readthedocs.io/en/latest/)；不关闭证书校验，也不全局替换 SSL。

1. 点击页面的 GitHub 创建链接，注册自己的 OAuth App。
2. Application name 填 `OfferPilot Local`；Homepage URL 和 Authorization callback URL 都填 `http://127.0.0.1:8766`。设备授权不使用回调，但 GitHub 注册表单需要填写。
3. 创建后启用 **Enable Device Flow**。
4. 将公开的 **Client ID** 填回 OfferPilot；不要填写 Client Secret 或访问令牌。
5. 点击“连接 GitHub”，在 GitHub 设备授权页输入页面显示的验证码并确认。工作台自动按 GitHub 返回的间隔检查状态。

也可在启动进程中配置 `OFFERPILOT_GITHUB_CLIENT_ID`。此值是公开应用标识，不能用不存在的通用应用 ID 替代。账号授权必须由用户完成；未配置应用时，页面会展开配置说明并禁用连接按钮。

采用官方 [OAuth Device Flow](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps#device-flow)。该流程申请 `repo read:user`；OAuth repo 范围包含仓库读写权限，而本服务仅调用仓库读取接口。组织仓库仍受组织授权策略限制。令牌到期后需重新连接，当前不实现 refresh token 自动续期。

GitHub 登录记录在本机 user 目录保存：Windows 使用当前用户 DPAPI 加密，POSIX 使用仅文件所有者可读写的文件。访问令牌、device_code 不返回浏览器，不写入日志或仓库。断开本机连接不会删除既有项目与简历历史；服务授权可在 GitHub 账号设置中撤销。

## 仓库与内容

授权后通过 [List repositories for the authenticated user](https://docs.github.com/en/rest/repos/repos#list-repositories-for-the-authenticated-user) 分页展示账号有权访问的公开、私有、协作和组织仓库，每页 50 项，支持继续加载。

选择“浏览文件”可分页查看完整文件清单；预览支持 256 KiB 以下的 UTF-8 文件，单次显示最多 30000 字。选择项目后再下载和分析，不会把全部仓库自动写成个人经历。

本期一次核验一个仓库。提取沿用固定 commit、文件哈希、大小配额、敏感路径筛选和不执行源码的原有实现；授权令牌只发往 `api.github.com`，跳转到归档下载域时移除 Authorization。

当前语义材料从下载结果中读取最多 12 个源码/说明片段，每片段最多 120 行，总计不超过 40000 字符。页面显示下载与阅读数量，未读取部分不推断已覆盖。此环节使用通用源码文本，不依赖 Graphify 的 Python 解析器；没有宣称完成任意大仓库的全量理解或重建 UA 图谱。

## 用户流程

1. 选择仓库，填写岗位/JD、个人职责与第三方/团队/AI 边界，确认允许把所选材料发给 Step 模型。
2. 服务固定版本、提取引用并生成待确认表述。用户逐条勾选实际属于本人负责的工作。
3. 在个人资料页填写并确认基本事实，至少提供姓名。简历页面提供直接入口。
4. 点击“确认所选经历，生成简历预览”，直接根据确认后的材料生成，不创建面试会话或调用出题/答题评价。
5. 预览采用已确认资料与项目表述生成受控 Markdown；不凭空补写数字，不将职责原始说明或核验过程文字拼入简历正文。职责确认记录、源码和核验限制作为版本元数据保存。
6. 用户核对事实与限制后保存不可变版本；可下载 Markdown、直接下载 PDF，或打开独立打印页。Windows 直接 PDF 导出使用 ReportLab 与本机宋体，嵌入中文字体；不调用模型，不重新改写正文。打印页按标题、段落与要点渲染，所有动态文本经过转义。
7. 可从版本记录重新查看和导出旧版本，也可在修改个人资料后点击“用最新个人资料生成新版”；旧版本不覆盖。模拟面试接口继续保留供后续接入，当前不在简历页面提供启动按钮。

2026-11-17 修复：同一源码和经历重新整理后可再次确认，不因任务编号不同触发 409。生成前检查已保存的姓名与真实性确认；资料缺失或存在未保存修改时，引导至个人资料并保留当前勾选。更换项目会清空旧预览和导出状态，已保存版本仍可从历史打开；刷新页面可恢复最近查看的已保存版本。版本读取先于 GitHub 仓库请求执行，仓库读取失败不会阻止已保存版本的展示。

回归入口：在仓库根目录运行 `.venv/bin/python -B -m unittest discover -s tests -p test_resume_web_flow.py`，覆盖同源 HTTP → 引擎 → 预览 → 幂等保存 → 读取版本 → 打印文档；`test_career_pipeline.py` 覆盖重复整理与确认。网页验收使用隔离的临时数据库、模拟 GitHub 和模型响应，实际点击下载 Markdown 并打开打印页，不替用户确认真实经历。PDF 文件仍通过浏览器打印对话框另存。

直接生成的草稿与版本标记 `assessment_status=not_assessed`，`session_id=null`。它们基于源码证据和用户确认，不代表经过面试或证明独立掌握。已有 session_id 生成路径仍兼容：存在职责或版本纠正时，必须先重新确认材料，不能据旧会话直接生成。个人职责属于用户确认，不把仓库所有权或提交量当作独立完成证明。

本期完成单项目、已确认事实模板的简历版本链路。跨仓库组合与文字润色仍是后续功能。保留的面试 API 每轮最多三题，固定问题计划，不含语音、动态追问或公司面经研究。

## 进程与数据隔离

同一启动器运行三个本机端口：工作台 8766、demo 引擎 18747、user 引擎 18748。两套引擎拥有独立的 Bearer 令牌、owner、业务 SQLite 和 checkpoint。

- demo：`web/data/demo/career-agent/`。
- user：`web/data/user/career-agent/`，含 `sources/`、`interview.db`、`checkpoints.db`、GitHub 应用公开配置和受保护的登录记录。

所有运行数据均被 Git 忽略。外层工作台保持 `/api/state` 的 27 个顶层键，未改岗位审批或投递语义。浏览器仅调用同源 `/api/career-user/...`，此命名空间只接受 `mode=user`；服务器固定转发到 18748，不接收任意目标地址。

## 新增同源接口

- `GET /api/career-user/github/status`：配置/连接状态与账号名，不含令牌。
- `POST .../github/config`：`{client_id}`，保存公开应用配置。
- `POST .../github/start`：启动授权，返回 user_code、固定 GitHub 验证地址、短期 ticket 与轮询间隔。
- `POST .../github/poll`：`{ticket}`，检查 pending/connected/expired/denied；后端再次限制轮询频率并处理 slow_down。
- `POST .../github/disconnect`：断开本机登录。
- `GET .../github/repositories?page=1`：分页仓库摘要。
- `GET .../github/tree?repository=owner/repo&page=1`：版本与文件清单。
- `GET .../github/file?repository=owner/repo&commit=SHA&path=...`：固定版本文件预览。
- `POST .../projects`：仓库、role、jd、contribution、confirmed、model_consent，返回 202 与 project_id；准备在后台进行。
- `GET .../projects/{id}`：读取准备阶段、阅读范围、候选表述与引用。
- `POST .../projects/{id}/confirm`：`{claim_ids,confirmed}`，生成冻结的核验材料。
- `POST .../interviews`：`{material_id,session_id,interview_mode}`，类型为 resume_readiness 或 mock_interview。岗位从材料读取；正式模式还核验真实已保存版本与 claim 绑定。
- `GET .../interviews/{id}`、`POST .../interviews/{id}/turns`、`GET .../interviews/{id}/recap`：会话、幂等答题和复盘。
- `POST .../resume-drafts`：当前主流程使用 `{material_id}`，仅接受经用户确认的个人项目材料；兼容 `{session_id}`。两者必须只选一种。服务端从本机 profile 读取资料，不接受浏览器伪造 profile。
- `POST .../resume-drafts/{id}/save`：`{confirmed:true}`，保存经确认版本；重复请求返回同一版本与时间。
- `GET .../resumes`、`GET .../resumes/{id}`：版本记录与固定正文。
- `GET .../resumes/{id}/print`：独立同源打印文档。
- `GET .../resumes/{id}/pdf?mode=user`：以附件返回固定已保存版本的 PDF，仅接受 user 模式。需要安装 `requirements-offerpilot.txt` 中的 ReportLab 依赖，以及 Windows 宋体字体；缺失时返回明确错误，可沿用打印页导出。

所有 JSON 接口使用 `?mode=user`，POST 可附加 `mode:"user"`。数据模式与面试类型分开，避免覆盖。草稿、版本、材料和会话都按服务端 owner 隔离；版本包含正文 SHA-256、资料/JD/源码快照、职责陈述、选中 claim 与来源会话，保存后不覆盖。

## 验证边界

本次覆盖了 DPAPI 往返、设备授权状态机、轮询限速与过期、私有仓库请求头及重定向脱敏、分页、固定引用、职责确认、简历版本幂等与不可变性、正式面试绑定及复盘。

页面端到端验收使用隔离端口与模拟 GitHub/模型/个人资料，不向真实 user 数据库写入测试经历。桌面与手机布局、打印页面和刷新恢复均已检查。新增 prepare 模型阶段另使用真实 `step-5-preview` 和公开样例验证了引用有效性。

测试不表示已替用户确认个人职责、生成其真实个人简历或完成能力评估。真实数据验收仍需用户完成授权、确认项目职责并填写个人资料；运行状态以当前页面为准。

v0.3 新增验收：确认项目后可直接生成并保存版本，期间没有新建面试会话，也没有调用 plan/intent/observation/hint；公开演示与个人页面不会自动恢复或启动面试。原有面试 API 回归继续保留。

预览按简历标题、段落和要点渲染，不将 Markdown 源码直接作为成品展示。选择项目后收起仓库列表，手机宽度和深色主题下的纸面预览已检查。整理失败时保留仓库、岗位、JD、职责和源码快照，恢复到可重试表单；再次发送材料前仍需用户确认。

2026-11-17 真实联调：使用重新登录的 GitHub 账号 Daxcq、公开仓库 Casten-Wang/offerpilot 的固定提交 `4c4c6032055566e0bf65ced76f7de71dc45bd0c8` 和真实 `step-5-preview` 跑通项目选择、整理、预览、保存、刷新恢复、Markdown/PDF 下载。整理阶段使用本次请求内的短证据编号，并确定映射回原始引用；未知引用进入一次格式修复重试，仍不通过则拒绝。该阶段输出额度调整为 16384，其余阶段保持 8192。导出文件检查了 Markdown SHA-256、PDF 正文完整性、中文字体嵌入和页面渲染。该版本只含账号名和两条项目经历，是联调产物，未补造教育或联系方式。
