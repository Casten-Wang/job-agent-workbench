# Graphify Python 结构解析验证

验证日期：2026-11-15。

已在本目录的 .venv-graphify 隔离环境运行 graphifyy==0.9.109。仅安装 Python AST 所需的基础依赖，没有安装全语言语法和可选模型／媒体依赖，没有执行 graphify install，也没有改写用户的 Agent 配置或钩子。

## 实际结果

probe_graphify.py 对本目录 fixture 中的 2 个自建 Python 文件执行结构提取，得到 5 个节点、9 条关系。源码中的写标记文件语句未被执行。符号、跨文件关系、无失败源文件与零模型 token 的检查通过。首次为未缓存提取，复跑命中缓存；耗时只是这两个极小文件的本机观测，不是仓库级性能结论。

结果在 probe-output/probe-result.json 和 probe-output/raw-extraction.json。

PyPI wheel 中 graphify/extract.py 与 GitHub 提交 d4a5b323ef8501518b82c58a05fe21b35ce24992 的同文件逐字节比较一致，SHA-256 为 8222dcccf119d2a45c66f9f90f3b37df2a536f073cc10d7a0895519d5a70f68b。本次没有逐文件证明整个 wheel 与该提交完全相同。

## 重跑

PowerShell：

    & '.\.venv-graphify\Scripts\python.exe' -X utf8 .\probe_graphify.py

独立结构解析调用：

    from pathlib import Path
    from graphify.extract import extract

    root = Path("选定的源码快照").resolve()
    files = [root / "main.py", root / "models.py"]
    result = extract(
        files,
        root=root,
        cache_root=Path("独立的任务输出目录").resolve(),
        parallel=False,
    )

root 必须是源码快照；cache_root 传任务输出目录，以免缓存写入原始材料。传入的文件应来自已经校验过的快照清单，不应把依赖环境、密钥或仓库外文件混入。

## 接入时应处理的字段

- result 包含 nodes、edges、input_tokens、output_tokens、failed_sources、skipped_sources、extracted_sources。
- 节点 source_file 在本次测试中为相对 root 的字符串，例如 main.py；source_location 为 L5 这样的字符串，不是行号数组，也不保证函数结束位置。
- 节点 label 可能带括号或方法前缀，例如 greet()、.normalize()。
- extracted_sources 是本机绝对路径字符串数组，包含被有意跳过的文件；不能单独据此算成功索引。
- 建议按路径对照 failed_sources、skipped_sources 与实际节点：失败、跳过、有结构节点、未产出结构分别记录。结构节点存在也不代表完整语法或语义阅读完成。
- 不直接向公开产物泄露 extracted_sources 等本地绝对路径；业务产物映射回仓库路径。
- 引用要回读原文并检查位置。INFERRED 关系不能直接当成候选人回答的唯一标准事实。

## 配置与执行边界

核对了直接 extract 入口及 rcfile.py、manifest_ingest.py、mcp_ingest.py 的相关逻辑。直接入口自动读取 root/.graphifyrc，它是有限 key=value 解析，语言映射只接受已知语言或后缀，没有执行任意 Python／JavaScript 配置的接口。部分解析器还读取 manifest、tsconfig 等静态项目元数据。

本次有限源码核对未发现上述入口执行待分析仓库脚本的调用；实际 Python fixture 中的顶层代码也没有运行。这不能替代对所有语言、所有依赖或恶意仓库的安全审计。真实产品仍应使用隔离工作目录、受限材料清单和任务资源边界。

## 参考

- [固定提交 pyproject.toml](https://github.com/Graphify-Labs/graphify/blob/d4a5b323ef8501518b82c58a05fe21b35ce24992/pyproject.toml)
- [固定提交 extract.py](https://github.com/Graphify-Labs/graphify/blob/d4a5b323ef8501518b82c58a05fe21b35ce24992/graphify/extract.py)
- [固定提交 rcfile.py](https://github.com/Graphify-Labs/graphify/blob/d4a5b323ef8501518b82c58a05fe21b35ce24992/graphify/rcfile.py)

尚未在用户项目或 pallets/itsdangerous 真实快照上实测；主流程接入后再验证。

