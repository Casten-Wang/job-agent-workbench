# OfferPilot 完整工作区代码快照

本分支保存 2026-11-17 本地工作区的项目代码、测试、配置示例和设计文档。目录结构与原工作区一致，便于恢复各模块之间的相对路径；`main` 分支仍保留原有的 OfferPilot 仓库布局。

- `offerpilot/`：网页工作台、内嵌岗位自动化后端、演示资料和模块测试，见 [工作台说明](offerpilot/README.md)。
- `interview_agent/`：Python Agent、模型接入、项目证据、知识库和工作流，见 [运行时说明](interview_agent/README.md)。
- `interview_hub/`：面试资料、存储和复盘服务。
- `github_source/`：GitHub 项目获取、授权和结构索引。
- `tests/`：工作区集成与业务测试。
- `验证/`：本项目编写的验证脚本和归档的 Pi 原型代码。

真实个人资料、凭据、会话、运行数据库、生成结果、虚拟环境、依赖安装目录和第三方工具下载副本未纳入快照。`offerpilot/vendor/` 中已内嵌的组件及其许可证保留。

恢复后在此目录创建 `.venv-interview`，按 `interview_agent/README.md` 安装 Python 依赖，并按 `offerpilot/README.md` 配置和启动工作台。凭据需要在本机重新配置。
