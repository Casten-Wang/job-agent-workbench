# VERSIONS

## 运行环境

- Python：3.14.8（项目要求 3.10+）
- 工作台入口：`web/server.py`，默认 `127.0.0.1:8766`
- 依赖：`requirements-offerpilot.txt`；`run_web.sh` 在首次运行时创建 `.venv` 并安装

## 内嵌岗位自动化运行时

- 包名：`offerpilot`
- 版本：2.4.0（见 `vendor/offerpilot/pyproject.toml`）
- 源码：`vendor/offerpilot/src/offerpilot/`
- 加载方式：`web/offerpilot_runtime.py` 懒加载 `offerpilot.web.server`，`base_url` 为 `embedded://offerpilot`
- 运行数据：`web/data/demo/offerpilot/` 与 `web/data/user/offerpilot/`（均被忽略）
- 许可：`vendor/offerpilot/LICENSE`（PolyForm Noncommercial 1.0.0），保留原始版权声明

## 数据版本

- 工作台快照：`GET /api/state` 27 个顶层键（以 `tools/tests/test_web_backend.py` 为准）
- 流程契约：`GET /api/pipeline` 六段流程，`POST /api/pipeline/event` 只记录回报
- 个人资料：`GET /api/profile` 读取 `web/data/<mode>/profile.json`；`workspace/` 下的文件由本地工具单独使用
