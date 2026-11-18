# 本机离线项目知识库

本模块提供固定版本的项目原文、目录、覆盖报告和检索接口，供外部模拟面试后端使用。它不新增出题、对话、评分或面试页面，不修改已有面试材料和简历。索引和查询不调用模型、不上传正文。

## 启动

正常使用 `tools/run_career_demo.py` 启动工作台时，个人服务同时提供知识库接口。只有资料服务需求时，在仓库根目录运行（macOS / Linux 把 `.\.venv\Scripts\python.exe` 换成 `.venv/bin/python`），无需模型密钥：

```powershell
& '.\.venv\Scripts\python.exe' -B '.\tools\run_career_demo.py' --engine-root . --knowledge-only
```

工作台地址为 `http://127.0.0.1:8766/`。`--knowledge-only` 仅启动工作台及知识库，简历模型与面试功能不可用。若同端口已有旧服务，先正常停止旧服务，再使用新代码启动；不要同时运行两个个人服务。

可信后端也可单独启动知识库。在工作区根目录设置自己的服务令牌后运行：

```powershell
$env:OFFERPILOT_CAREER_USER_TOKEN = (python -c "import secrets; print(secrets.token_urlsafe(32))").Trim()
& '.\.venv\Scripts\python.exe' -B -m interview_agent.knowledge_api --root '.\web\data\user\career-agent'
```

独立服务默认 `127.0.0.1:18748`，owner 默认为 `offerpilot-personal`；可用 `--port` 和 `--owner` 指定其他本机实例。所有接口包括 `/health` 均要求 `Authorization: Bearer <服务令牌>`。令牌供可信后端使用，不放进候选人网页。正常工作台启动会生成并在进程内传递令牌。

## 预热与版本

- 服务启动时扫描当前 owner 的全部已导入项目，不受旧记录列表的 100 条上限限制。Web 进入个人模式及每次重新打开时独立发送预热请求，不等待其他表单初始化，也不要求进入面试页面。
- 选择 GitHub 项目立即登记后台任务；手动经历与现有项目在保存原始资料后自动关联。重复打开、刷新或登记复用资料源和索引。
- 有固定提交和本地清单时先校验并复用本地文件，只有缺失内容才使用现有 GitHub 授权补取。首次选择尚无版本的仓库需联网固定一次版本，之后不自动跟随默认分支。
- 用户通过原项目导入流程更新项目后，新提交成为另一个资料源和不可变快照；调用方应保存所用 `snapshot_id`。旧快照继续可检索。
- 按 owner 分目录保存于 `<career-root>/knowledge/owner_*/`，包含 SQLite 索引和源码缓存；正常工作台下位于被忽略的 `web/data/`。原简历、职责确认和面试结果不被修改。

## 接口

根路径 `/v1/knowledge`，正文为 JSON 对象。浏览器通过同源 `/api/career-user/knowledge/...?mode=user` 转发；demo 模式不能读写个人知识库。owner 来自服务配置，不能由请求覆盖。

### `POST /sources` → 202

正文二选一：`{"repository":"owner/repo"}` 或 `{"project_id":"已有个人项目ID"}`。不接受本地路径、下载 URL 或客户端提交的源码；仓库也可使用普通 HTTPS GitHub 地址。

返回资料源摘要，含 `source_id`、`source_type`、`repository`、`source_commit`、`project_ids`、`status`、`snapshot_id`、`coverage`。源码版本尚未取得的旧项目返回 `waiting_for_source`，不会冒充可检索资料。

### `POST /warmup` → 202

正文 `{}`，返回 `queued`（当前排队及构建任务数）与 `source_count`。为缺失索引、索引格式版本变化、失败或中断任务排队；已完成的缓存不重复构建。存在失败文件的部分快照可在后续预热重试，预算限制本身不会触发反复下载。

### `GET /sources?limit=20&offset=0` → 200

`limit` 为 1–100，`offset` 为非负整数，返回 `items`、`total`、`next_offset`。调用方应分页读取全部项目。

`status` 包括 `queued`、`building`、`ready`、`partial`、`empty`、`failed`、`interrupted`；处理时有 `processed_files`，完成后有 `build_ms`。`snapshot_id` 非空表示有可用快照；重建失败仍可保留此前快照。`empty` 仅表示允许范围内确实没有可索引内容，无法读取的源码不会被标为空项目。

### `GET /snapshots/{snapshot_id}/context` → 200

返回固定提交、文件目录及指纹、覆盖报告、逐文件处理状态和来源限制。`confirmed_contributions` 单独汇总同 owner、同仓库、同版本材料中的已确认职责，属于当前确认状态；原始快照本身不认证个人贡献。手动经历标记为用户提供、未经独立核验。

### `POST /search` → 200

```json
{"snapshot_ids":["从资料源列表获取的ksnap_..."],"query":"登录鉴权 permission_check","top_k":8}
```

`snapshot_ids` 必填，一次最多 100 个快照；`query` 为 1–1000 字符；`top_k` 默认为 8，范围 1–20。

返回 `items`、`snapshot_ids`、`search_ms`。命中包含 `evidence_id`、`snapshot_id`、`path`、`line_start`、`line_end`、`source_commit`、`sha256`、`text`、`source_url`、`source_kind`、`personal_contribution`、`score`。`sha256` 对应完整原文件；行号按 LF 计数，文本为连续的最多 60 行原文。使用 SQLite FTS5 与 BM25，中文双字切分、英文标识符拆分，不等同语义搜索。

未知或其他 owner 的快照返回 404；把未就绪资料源 ID 当快照查询返回 409，不能用空命中冒充已就绪。非法字段或范围返回 400，未授权返回 401，正文结构错误返回 422。没有命中的合法查询返回空 `items`。

## 覆盖、恢复与接入边界

全项目文本包含源码、测试、文档和配置，不沿用简历最多 12 段证据的抽样。保留单文件 512 KiB、单项目 20 MiB 上限，不设 250 文件截断。依赖、生成物、二进制、非 UTF-8 文本、敏感路径、疑似密钥、符号链接与子模块不纳入索引；筛选属于启发式检查。

索引规则第 2 版将图片、压缩包、PDF、Office 文档等需额外提取器的格式统一标为 `non_text_attachment`，不因其大小触发文本覆盖缺口，页面会明确提示附件未纳入文本索引。大源码或文本仍保留 `file_size_budget` 并标记 `partial`。升级后预热生成新快照，旧快照保留原有报告；此状态修正不代表已经读取附件内容。

`coverage` 包含清单完整性、总文件数、已索引数、各状态计数、排除/失败原因及 `complete`。`ready` 指声明的允许范围已完成，不能解释为敏感文件等也已导入。预算不足、缺失和下载失败会明确标注。调用方应保留版本与覆盖限制，不将整个仓库当用户个人成果。

先保存固定版本清单与校验后的原文件，再事务发布索引及资料源指针。中断、网络不可用或索引格式升级后可通过预热重建；上一可用快照继续服务。旧业务数据库与已发布材料保持不变。服务使用单 worker，不支持多个进程同时拥有同一知识库运行目录。

`kev_` 引用属于知识库契约，本次没有扩大旧 `question-plan` 接口允许的材料引用集合。模拟面试模块应自行调用上下文和检索接口完成接入。

## 路演 PDF / PPTX（索引规则第 3 版）

已选 GitHub 项目中的 `.pdf`、`.pptx` 现在会按固定提交下载并保留原文件。源码仍受单文件 512 KiB、累计 20 MiB 限制；这两类文档单独使用每文件 10 MiB、累计 20 MiB 的预算，最多 100 页/张、200000 字符。其他图片、压缩包及旧版 `.ppt` 仍明确排除，不作为源码缺失。

- PDF 先读取文字层；没有文字的页通过本机 `pdftoppm` 渲染，再交给 Windows OCR。
- PPTX 按 presentation 的幻灯片关系顺序读取可编辑段落和表格文字；没有文字的幻灯片，对内嵌图片做本机 OCR。不会访问外链、运行宏或执行文档里的指令。
- 原文件用 Git blob SHA 校验，提取结果按文件指纹与提取器版本缓存。重复打开和离线重建可复用结果，旧快照及旧引用继续保留。
- 解析在独立 Python 子进程进行，单文件最多 90 秒；ZIP/XML 大小、页数和文字总量受限。加密、损坏、超限、OCR 不可用或没有识别文字的页均会出现在覆盖报告，不能冒充已导入。

解析依赖已列入 `interview_agent/requirements.txt`：pypdf、Pillow。可编辑 PPTX 和有文字层的 PDF 不需要 OCR。图片页识别需要 Windows PowerShell、已安装的 Windows OCR 语言和 PATH 中的 `pdftoppm`；本机已具备这些工具。OCR 不发送云端、不调用模型；识别结果可能有错字，需对照原页核对。不会将文字提取视为文档成果声明已经得到验证。

文档检索命中保留原 `path`、`source_commit`、原文件 `sha256` 和文件链接，并新增：

- `source_kind: "document_text"`、`unit_type: "page" | "slide"`、从 1 开始的 `unit_number`，以及 `page_number` 或 `slide_number`。
- `extraction_kind: "pdf_text" | "pdf_ocr" | "pptx_text" | "pptx_ocr"`；OCR 命中的 `needs_review` 为 true。
- `text_sha256` 对应该页/张的完整提取文字；`line_basis: "extracted_text"` 表明 `line_start/line_end` 是该页/张提取文字内的行号，不能当作二进制文件行号。

文档文件链接不拼接源码的 `#L` 锚点。调用方展示引用时应使用“原文件名，第 N 页/张”，并保留 OCR 核对标记。`coverage` 增加 `document_files`、`document_units`、`document_text_units`、`document_ocr_units`；逐文件报告保留未读取文字的页码。页面的「项目知识库」状态块同步显示文档数量、可检索页数和 OCR 页数。

追问路演时，`POST /search` 可额外传 `"source_kind":"document_text"`，只在文档中检索，避免大量源码命中占据前 20 条。也支持 `source_text`（源码/普通文本）和 `user_supplied`（自主经历原文）。不传该字段时保持原有混合检索行为。
