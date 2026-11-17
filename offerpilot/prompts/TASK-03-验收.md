# TASK-03 验收记录（主会话复核）

本记录对应 `prompts/TASK-03-intake-filters.md` 与 `PLAN.md` 第 3 节 M2/M4/M17、第 4 节阶段 1/2、第 5 节全局验收。所有结论来自本地离线代码与 `unittest`，没有联网、LLM 打分、真实岗位抓取或投递。

## 产出文件

- `tools/config.json`：目标城市、排除词、岗位方向关键词、薪资下限、指纹算法、评分阈值（仅配置）、埋点初始值、JD 标签与异常文本模式。
- `tools/filters.py`：归一化、SHA-256 指纹、薪资解析、城市/排除词/薪资硬规则、岗位方向 warning。
- `tools/jd_intake.py`：只从明确 `标签：值` 提取字段，输出结构化 JSON；指令样文本原样摘录为 `input_anomalies`。
- `tools/ats_check.py`：PDF magic bytes、页数提示、文字层与关键词保守校验；不可解析时 `needs_manual_check`。
- `tools/variants.py`：只保存用户手动编辑的经历变体原文，不读、不写 Master Resume。
- `tools/tests/test_task03.py`：离线测试。

## 已自动验证

| 测试覆盖 | 对应验收条目 |
|---|---|
| 配置默认值、城市允许/拒绝、排除词命中、薪资下限拦截 | M4 硬规则漏斗 |
| `15k-25k`、`15000-25000`、`面议`、显式薪资上下限、不可解析薪资放行并 warning | M4 薪资规则；不猜测数值 |
| 城市为空、公司/岗位缺失、岗位方向未命中只记 warning | 缺失字段为 `null`，不臆造 |
| NFKC/casefold/空白折叠/法律实体后缀去除，跨平台指纹一致 | 全局验收「公司+岗位名+城市」指纹 |
| JD 指令样文本被 `input_anomalies` 引用而不执行 | 不可信外部内容边界 |
| 单栏 ATS PDF 静态检查：magic bytes、页数提示、文本层、Flate 文字流、关键词命中/缺失 | M6/阶段 1 的「可自动验证」部分 |
| 变体新增与列出、内容寻址、不覆盖 `resume.md` | M7 经历变体 |
| CLI 输出 JSON、只读输入；测试禁用网络连接 | 本地优先、不联网 |

## 需人工验证

- 10 份真实 JD 的评估、定制简历与 PDF 渲染；PDF 中文字体、分栏顺序、图片与表格需要人工抽查。
- 「JD 关键词覆盖率 ≥ 90%」：`ats_check.py` 只能校验标准库可解码的文字层，不能证明真实 ATS 解析覆盖率。
- 「简历中每个数字能在 `resume.md` 找到出处」：本任务不生成简历；需事实核查与人工确认共同完成。
- `portals.yml` 至少 20 家公司及同配置两次扫描一致：本任务不配置、不运行扫描器。
- 真实 JD 的 active status、发布时间与 HR 活跃度：需要真实数据源，离线样例无法验证。

## 未实现 / 未确认

- 未实现 LLM 评估打分；`score.high_threshold=4.5`、`approval_min=4.0`、`approval_max=4.4` 只写进配置。
- 未实现招聘平台自动采集、OCR 截图录入、私域潮汐监控、微信群转发解析。
- `tools/config.json` 的 `LLM_Rewrite_Edited_Flag` 与 `PLAN.md` M17 的 `LLM_Edited_Flag` 字段名不一致：**未确认**，需统一命名后再接入 tracker。
- OfferPilot 静态导出字段由 TASK-07 宽松映射，真实导出字段清单：**未确认**。
- 未修改 `workspace/` 任何系统层文件；`git status --porcelain` 无输出。

## 复核结论

TASK-03 的离线可验收部分已完成并通过全量测试；真实 JD 打分、PDF 视觉/ATS 解析、平台扫描与简历事实闭环仍属于人工验证或未实现，不记作已完成。
