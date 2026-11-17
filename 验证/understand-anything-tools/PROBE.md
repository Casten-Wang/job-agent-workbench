# Understand-Anything 隔离运行验证

本目录仅为工具验证，不安装到用户 Agent 平台，不运行上游 install.sh 或 install.ps1，也不更改全局配置或原小红书环境。

## 固定来源与环境

- 官方仓库：Egonex-AI/Understand-Anything。
- 固定提交：b861852dda79273bd9d2e01c3160d42e2df510d2。
- 源码位于 source/，通过 GitHub API 对该提交下载 ZIP，25,510,721 字节。解包时拒绝越界并不跟随符号链接。
- 来源记录：[source-snapshot.json](./source-snapshot.json)。
- Node.js：24.15.0；pnpm 执行时按上游 packageManager 使用 10.6.2。
- 已构建 @understand-anything/core 0.1.0；上游 skill 包为 2.9.8。
- 精确已安装运行依赖见 [installed-runtime-versions.json](./installed-runtime-versions.json)，完整上游约束来自固定提交中的 pnpm-lock.yaml。

## 实际安装与构建

以下命令在 source/ 内运行，采用冻结锁文件和禁用安装生命周期脚本。仅显式执行核对过的 core TypeScript 构建；未构建看板或安装平台技能。

```powershell
pnpm --config.manage-package-manager-versions=false --config.package-manager-strict=false install --frozen-lockfile --ignore-scripts --filter '@understand-anything/core...'
pnpm --config.manage-package-manager-versions=false --config.package-manager-strict=false --filter '@understand-anything/core' build
pnpm --config.manage-package-manager-versions=false --config.package-manager-strict=false install --frozen-lockfile --ignore-scripts --filter '@understand-anything/skill...'
```

pnpm 提示 package.json 内旧 pnpm.onlyBuiltDependencies 位置不再使用；本次忽略安装脚本，core 编译和 Python WASM 结构提取均实际成功。未启用或构建 native grammar 安装脚本，其他语言未实测。

## 样例范围与确定性阶段

目标为已固定源码副本 outputs/understand-anything/itsdangerous-672971d66a2e/project，仅含 README、pyproject.toml 与 src/itsdangerous 下 8 个 Python 文本文件。原始样例提交为 672971d66a2ef9f85151e53283113f33d642dabd，副本不是 Git checkout；git ls-files 不可用时，官方扫描脚本回退到目录遍历，不能据此声称 Git 历史或增量同步已验证。

在工作区根目录运行：

```powershell
node '验证/understand-anything-tools/run_core_probe.mjs'
```

该封装调用固定提交内的真实官方脚本：

1. scan-project.mjs：扫描 10 个文本文件，8 code、1 docs、1 config，扫描失败为零。
2. extract-import-map.mjs：10 文件中 6 个存在内部导入，共 21 条内部导入映射。
3. compute-batches.mjs：官方算法生成 2 批，文件数分别为 6、4。
4. extract-structure.mjs：2 批共 10/10 文件结构提取成功；代码调用结构 8 成功，2 个非代码文件按规则跳过调用图；不可读、跳过结构和结构失败均为零。

所有确定性输入和输出保留在 project/.ua/intermediate/。本工具不会导入或运行待分析 Python 项目。读取和分析源码的工具本身是 Node 程序，其运行不等于执行样例业务代码。

核心导入还确认 validateGraph、sanitizeGraph、GraphBuilder、TreeSitterPlugin、buildFileAnalysisPrompt 与 buildTourGenerationPrompt 可调用，但该探针没有虚构语义摘要或做全工作流模型分析。语义图批次、架构层、学习路线、源码教学内容由主会话随后按上游 Agent 工作流生成和复核。

[core-probe-result.json](./core-probe-result.json) 记录范围和各批结果；[core-probe-commands.json](./core-probe-commands.json) 保留官方脚本参数、退出码及原始 stdout/stderr。

run_core_probe.mjs 是确定性阶段复现入口，重跑会覆盖对应的 scan-result.json 和结构中间文件；请在新的分析副本上复现，或在主会话语义阶段开始前运行，避免覆盖后来补充的扫描叙述字段。

## 后续图谱处理入口

同一官方 skills/understand/ 目录内提供 merge-batch-graphs.py、normalize-tour.mjs、build-fingerprints.mjs。主会话负责组装、图谱校验、引用复核和产品适配；本目录的确定性探针不将结构成功当作理解正确率或候选人能力通过。

## 官方看板准备

已读取固定源码中的 understand-dashboard/SKILL.md。按其步骤先尝试插件同版本 v2.9.8 的预构建 viewer，但官方 release tag API 返回 HTTP 404，因此没有使用 latest 版本，改用同一固定源码的 Vite 看板。

只追加安装 @understand-anything/dashboard 的依赖（冻结锁文件、忽略安装脚本），未执行 dashboard build 或 viewer build。start_dashboard.mjs 复用官方 vite.config.ts，覆盖绑定为 127.0.0.1:18745、strictPort=true、open=false；GRAPH_DIR 仅设置在该进程内。官方配置会生成一次性访问令牌并打印完整 URL。

由主会话完成知识图谱的 schema 与引用校验后，再运行：

```powershell
& '.\验证\understand-anything-tools\start_dashboard.ps1'
```

启动脚本使用 Start-Process -WindowStyle Hidden；PID、stdout、stderr 都保存在本目录。启动后从 dashboard.stdout.log 取得带 ?token= 的 Dashboard URL。不要仅传裸地址，否则官方看板会要求访问令牌。

停止方式：

```powershell
& '.\验证\understand-anything-tools\stop_dashboard.ps1'
```

停止脚本会核对记录的 PID 命令行确属本目录入口，避免停止 PID 复用后的其他进程。当前查看器准备状态记录在 viewer-preparation.json；仅有依赖准备不表示页面已经启动或完成视觉验证。
