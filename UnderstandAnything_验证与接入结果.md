# Understand-Anything 验证与接入结果

日期：2026-11-15。

本轮没有阻塞确认项，沿用用户已选择的公开样例。已实际使用 Understand-Anything 的官方脚本与 Agent 工作流，完成范围明确的项目解释、架构分组、学习导览及源码引用检查。未安装全局平台技能，也未修改原小红书环境。

后续联通：本轮已验证的声明、问题、证据与课程片段已进入[模拟面试材料接口和复盘原型](./定制简历_模拟面试资料接口与复盘服务_v0.7.md)，并完成两轮合成结果的 HTTP 验收；真实面试评价仍未实施。

## 实际使用了什么

官方源码固定在 b861852dda79273bd9d2e01c3160d42e2df510d2，隔离构建 @understand-anything/core 0.1.0，插件版本 2.9.8。[安装及确定性流程说明](./验证/understand-anything-tools/PROBE.md)、[来源记录](./验证/understand-anything-tools/source-snapshot.json)。

输入仍为 pallets/itsdangerous 的固定提交 672971d66a2ef9f85151e53283113f33d642dabd。本轮语义范围为运行时代码的 8 个 Python 文件、README 和 pyproject.toml，共 10 个文本、1431 行。逐文件核对后复制到独立目录；测试与完整文档未进入本轮语义分析，不能把该结果说成原仓库 49 个已下载文本都已通读。

执行过程：官方扫描 → 内部导入映射 → 官方语义分批 → 官方结构提取 → 当前会话模型按 file-analyzer 角色生成中文语义 → 官方合并 → 架构与导览 → 官方导览规范化 → 逐文件代码讲解 → 官方 schema 校验及结构指纹 → 原快照引用校验。

结构和校验调用的是真实上游代码。语义内容由当前会话模型阅读源码后按上游角色生成；尚未封装为无人值守的模型 API 后台任务。生成脚本只保存本次模型撰写的材料，不冒充另一个语义模型。模型用量未计量，不能据此声称 token 消耗为零。[生成过程与适配说明](./outputs/understand-anything/itsdangerous-672971d66a2e/generation-provenance.json)。

## 结果与验证

- 官方扫描和结构提取：10/10 成功，两批分别为 6／4 个文件，无不可读或结构失败。
- 图谱：36 个节点、94 条关系，包含全部 21 条内部导入映射。
- 架构：项目说明与公共入口、签名与时效、负载序列化、编码与异常，共 4 组。
- 学习路线：6 步，从用途和入口到签名、对象序列化、时效及 URL-safe 负载。
- 代码导览：10 文件、43 节中文解释；章节行范围不重叠并与导览步序关联。
- 引用检查：36 个节点引用与 43 个课程章节引用，共 79 处，都能恢复到原快照中的实际内容，版本、路径、行号与内容指纹校验通过。
- 单元测试：原有取数／快照测试加新引用适配测试，共 42 项通过。[测试结果](./outputs/understand-anything-unit-tests.json)、[日志](./outputs/understand-anything-unit-tests.log)。

[官方 schema 结果](./outputs/understand-anything/itsdangerous-672971d66a2e/schema-validation.json)、[引用结果与实际原文](./outputs/understand-anything/itsdangerous-672971d66a2e/reference-validation.json)、[汇总验证记录](./outputs/understand-anything/itsdangerous-672971d66a2e/verification-result.json)。

另一次独立源码抽查核对了 NoneAlgorithm／签名非加密、正常加载与 unsafe 恢复、过期不继续 fallback、URL-safe 压缩阈值及前导标记四项，未发现必修语义错误。该结果仅为定向抽查，没有测出全仓理解准确率；边权也不是正确概率或运行时证明。[抽查记录](./outputs/understand-anything/itsdangerous-672971d66a2e/semantic-review.json)。

NoneAlgorithm 不签名、密钥派生的 none 与关闭签名不是同一概念；unsafe 路径也不能保证任何情况下都不抛异常。此类条件需要保留在问题与反馈里，不能把文档口号或模型摘要直接当作唯一标准答案。

## 已连接到前置核验样例

保留上一轮的 claim_id 和固定源码版本，把原来的三道问题关联到本轮真实 UA 课程与导览步序。每道题都有可回读的原文和对应学习内容，可用于“回答 → 查看相关实现 → 补强 → 变式复测”的后续接入。

[核验与学习材料样例](./outputs/understand-anything/itsdangerous-672971d66a2e/resume-readiness-demo.json)、[联通检查](./outputs/understand-anything/itsdangerous-672971d66a2e/readiness-integration-check.json)。

这三题仍是本次会话准备的样例，自动出题服务未实现。没有收到真实候选人回答，没有作出能力判断；公开项目不归于当前用户，个人简历表述保持未生成。

产品侧新增 [UA 引用检查器](./github_source/understand.py)，并接入 CLI：

```powershell
python -X utf8 -m github_source ua-check 'outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd' --ua-dir 'outputs/understand-anything/itsdangerous-672971d66a2e/project/.ua' --output 'outputs/understand-anything/itsdangerous-672971d66a2e/reference-validation.json'
```

检查器不会用摘要冒充原文；缺坐标的节点只能导航，错误版本不产生源码证据。检查通过表示引用可恢复，不等于解释正确、贡献真实或能力通过。

## 看板实看

官方看板已在本机后台运行：[打开交互式看板](http://127.0.0.1:18745/?token=4c8221ffb26b4780be4d8bd60e660ec5)。仅监听 127.0.0.1，未带令牌的数据请求返回 403。

已通过浏览器实际检查架构渲染、启动六步导览、选择签名步骤、打开 signer.py 源码，再选择“生成带签名消息”；界面定位到第 215–225 行并展示对应中文解释。[浏览器检查记录](./outputs/understand-anything/itsdangerous-672971d66a2e/browser-verification.json)。

已知提示：看板显示无法读取 Git HEAD，因为输入是从固定提交取得的源码副本，不是 Git checkout。原始版本与全部引用由我们的快照指纹独立校验；没有隐藏此提示，也没有伪造 Git 历史。增量更新和 Git 状态提示还未验证。

停止看板：

```powershell
& '.\验证\understand-anything-tools\stop_dashboard.ps1'
```

## 结论与剩余工作

Understand-Anything 本轮已实际用于项目解释和学习导览。GitHub 取数与固定快照继续复用既有实现；下一步可以消费 UA 的摘要、导览和课程，而无需把现有 Graphify 验证图再维护成一套重复产品图谱。两轮分析范围和节点粒度不同，节点数量不用于比较理解质量。

仍未完成：GitHub App／私库授权、多用户后台任务、无人值守语义生成、真实候选人问答与评价、补强复测及模拟面试状态联通。正式接入时再确认 GitHub App 归属和模型提供方；这些信息不阻塞本轮公开样例验证。
