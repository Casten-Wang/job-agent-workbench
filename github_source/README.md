# GitHub 数据源验证入口

当前交付是本地命令行原型：只读取公开仓库，不读取本地 GitHub 凭据，不启动网页服务。用户登录、GitHub App 安装与私有仓库尚未接入。

在工作区根目录使用 Python 3.11+。取数和引用只依赖标准库：

```powershell
python -X utf8 -m github_source ingest pallets/itsdangerous
```

输出目录为 outputs/github-source/仓库名/提交号，包含 manifest.json、source/、contributions.json 和 REPORT.md。manifest 分别记录清单、下载、排除、结构索引、语义阅读和贡献查询状态。

首次默认限制 250 个文件、单文件 512 KiB、选中文本总量 20 MiB；归档下载最多 50 MiB。命令支持 --max-files、--max-file-bytes 和 --max-total-bytes。预算或过滤导致的排除会保留原因。敏感文件检查为启发式筛选，不能保证发现所有密钥；原型没有向模型发送源码。

先固定分支或提交，再下载相同提交的归档；逐文件验证 Git blob SHA。缺失文件按 blob 补取。不会执行项目安装、构建、测试、钩子或仓库配置脚本。二进制、非 UTF-8、符号链接、子模块与 LFS 实际内容默认不导入。

相同输出目录、提交与预算下重跑，会校验并复用已保存文件。分支更新会产生新目录；要恢复原任务请使用 manifest 中的完整提交号：

```powershell
python -X utf8 -m github_source ingest pallets/itsdangerous --ref 672971d66a2ef9f85151e53283113f33d642dabd
```

可用 --author GitHub用户名 获取贡献线索。默认最多两页提交、两页仓库 PR，每页 100 条，PR 在本地按作者筛选；达到页数上限或请求中途失败时明确标为 partial。PR 与当前快照的归属关系未自动验证。用户名关联不能证明独立完成工作。未提供作者时标为 skipped_no_author。

查询结果绑定获取时间和版本。同一作者与快照的有界结果会复用；当前没有实现手动刷新 PR 元数据或向前补齐分页，需后续接任务同步。

生成准确原文引用：

```powershell
python -X utf8 -m github_source cite "outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd" --path src/itsdangerous/signer.py --start 215 --end 225
```

输出 JSON 包含仓库 ID、固定提交、路径、原始行号、内容指纹和 GitHub 固定链接。本地原文被修改后会拒绝引用；重跑固定提交可修复。行号按 LF 计算，不把字符串中的 Unicode 分隔符误当新行。

## Graphify 可选结构索引

本机已在 验证/github-source-tools/.venv-graphify 中安装 graphifyy==0.9.109 及 Python 语法最小依赖，未安装全部语言能力。探针、版本清单与安装命令见[验证说明](../验证/github-source-tools/PROBE.md)。

```powershell
& '.\验证\github-source-tools\.venv-graphify\Scripts\python.exe' -X utf8 -m github_source index 'outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd'
```

该命令只解析已下载且校验一致的 .py 文件。保存 graph.json、工具版本和每文件结构状态；非 Python 文件显示 outside_validated_python_scope。结构节点包含推断关系，不能自动作为标准答案。语义阅读、个人贡献确认和问答评估均未由此命令完成。

## Understand-Anything 接入验证

已按官方工作流在同一固定样例的 10 个选中文本上生成语义图、六步导览及代码课程，详见[UA 验证与接入结果](../UnderstandAnything_验证与接入结果.md)。当前由本次会话模型执行语义角色，尚未封装为无人值守生成服务。

引用检查命令：

```powershell
python -X utf8 -m github_source ua-check 'outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd' --ua-dir 'outputs/understand-anything/itsdangerous-672971d66a2e/project/.ua' --output 'outputs/understand-anything/itsdangerous-672971d66a2e/reference-validation.json'
```

该命令核对固定提交、原文指纹、行号及节点／课程引用，不评价语义准确性或个人能力。

## 验证与下一步

```powershell
python -X utf8 -m unittest discover -s tests -v
```

离线测试覆盖提交固定、树截断、下载与路径限制、引用完整性、部分结果和恢复。公开仓库实测及问答材料样例见[推进结果](../GitHub数据源_首轮推进结果.md)。

下一步接入实际项目的 GitHub App 用户绑定、安装仓库选择和撤销事件，再接 Agent 语义阅读与前置问答。当前代码不能直接作为对外多用户或私有代码服务运行。
