# GitHub 数据源首轮推进结果

日期：2026-11-15。

已交付本地可运行的公开仓库取数、快照复用、原文引用与 Python 结构索引。当前工作区没有应用后端，因此先以命令行验证，不预设前后端框架。未连接用户账号或私有仓库，也未实施真实候选人的能力评估。

后续阶段：已在同一固定样例的 10 个选中文本上实际使用 Understand-Anything，生成项目解释、导览与代码课程，见[UA 验证与接入结果](./UnderstandAnything_验证与接入结果.md)。下文保留首轮结构验证的原范围和结果。

## 实际运行结果

样例：公开项目 pallets/itsdangerous，固定提交 672971d66a2ef9f85151e53283113f33d642dabd。它仅用于工具验证，不属于当前用户的简历经历。

- 文件清单：50 项；下载并逐项校验 49 个文本文件，1 个生成文件按规则排除。
- 下载文本：120259 字节。所有保存文件同时通过 Git blob SHA 与本地 SHA-256 核对。
- Graphify：graphifyy 0.9.109，在独立 Python 3.11.16 环境解析 15 个 .py 文件；产出 216 个节点、642 条关系，未报告失败文件。此处为静态结构，包括推断关系，不代表所有实现路径均正确或已经运行。
- 模型调用：本次结构解析未使用模型，Graphify 报告输入／输出 token 为零。自动语义阅读服务未实现，覆盖清单仍为 0，不把当前 Agent 阅读的少量片段填成全仓通读。
- 贡献查询：以公开维护者 davidism 作为样例，取得 200 条提交、40 条 PR 线索。查询限制为两页提交与两页仓库 PR，达到上限，明确保存为 partial；PR 是否包含在当前源码快照中尚未验证。这些材料不证明用户的任何个人贡献。
- 固定提交重跑：复用文件与已保存贡献材料，仅执行两次仓库／提交解析请求，没有重新下载归档。
- 问答材料：当前 Agent 阅读并核对指定代码片段后整理 1 条项目事实、4 份原文证据、3 道问题和 1 项学习任务示例。未收到候选人回答，没有能力判断；这份材料不是已实现的自动出题服务。

完整源码均作为数据保存和解析，未执行样例仓库的安装、构建、测试或业务代码。Graphify 自建小样例中的顶层副作用也未被执行；该探针只验证本次 Python 静态解析路径，不构成全语言安全审计。

## 代码与产物

[使用说明与命令](./github_source/README.md)、[GitHub 连接器](./github_source/github_api.py)、[快照与引用](./github_source/ingest.py)、[Graphify 适配](./github_source/indexer.py)。

[源码快照报告](./outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd/REPORT.md)、[完整覆盖清单](./outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd/manifest.json)、[贡献查询及范围](./outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd/contributions.json)、[结构图数据](./outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd/graph.json)。

[带源码依据的经历卡与三题样例](./outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd/experience-card-demo.json)、[公开快照验证结果](./outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd/verification-result.json)、[复查脚本](./验证/github_source_smoke.py)。

[Graphify 安装与自建样例验证](./验证/github-source-tools/PROBE.md)。依赖安装在本次独立目录，没有改原小红书环境、用户 Agent 配置、Git hooks 或全局代理。

## 验证范围

离线单元测试覆盖固定提交、递归树截断补取、API 与重定向域名限制、下载大小、私库拒绝、贡献分页部分结果、引用指纹、原始行号、路径越界、文件排除、缓存及中断恢复。测试使用本地构造数据，不调用外部仓库。

本轮最终运行 29 项离线测试全部通过；见[测试结果](./outputs/github-source-unit-tests.json)及[日志](./outputs/github-source-unit-tests.log)。

真实公开快照验证另外检查文件完整性、图谱与源码提交一致、引用固定版本、贡献查询截断标记、未归属用户经历、未夸大语义阅读，以及固定版本复用。各项结果见上面的 JSON，不将离线测试当作真实授权验证。

## 还没有完成

1. GitHub App 注册、登录与安装绑定、授权仓库列表、组织审批、私有仓库和撤销事件。
2. 产品界面、后台任务服务及多用户材料隔离。当前仅是本机公开仓库验证工具，不可直接作为对外服务部署。
3. Python 以外语言的实际解析验证，以及全仓语义分析、自动生成经历卡和自动评价回答。
4. 用户本人职责确认、真实问答、补强复测和模拟面试的状态联通。

后续接入按现有 v0.6 设计继续，保留本轮已验证的固定快照、覆盖清单与证据字段，不将原型的公开访问模式直接扩展为私有代码授权。
