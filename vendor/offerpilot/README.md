# OfferPilot 内嵌岗位自动化组件

本目录是工作台内置的岗位自动化运行时源码，由 `web/offerpilot_runtime.py`
在同一进程导入。它不是独立服务，也不需要单独端口。

## 许可

本目录包含按 PolyForm Noncommercial License 1.0.0 授权的第三方代码，全文见
[LICENSE](LICENSE)。本项目为个人自用、非商用；不得移除版权声明，也不得把
本目录代码用于商业分发。

## 组成

- `src/offerpilot/`：岗位采集、评分、任务编排、浏览器执行器与本地 Web 适配。
- `src/offerpilot/data/`：城市数据。
- `config.example.yaml`：配置模板；真实配置、凭据、SQLite 与简历只写入
  gitignore 的 `web/data/<mode>/offerpilot/`。

## 边界

- 只在本机运行，由工作台统一监听 `127.0.0.1`。
- 工作台只开放 `collect`、`monitor`、`full` 三种任务，没有独立 `deliver` 入口。
- 发送仍受人工确认门、每日上限、随机间隔与平台安全锁约束；不设时间段限制，全天可发送。
