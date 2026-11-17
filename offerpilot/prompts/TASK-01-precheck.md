# TASK-01：投递前 30 天去重检查

## 1. 背景与目标
个人自用的求职 Agent，本地运行。总方案见 `/Users/casten/Documents/程序开发/求职/PLAN.md`，动手前完整阅读第 0、2、3（M8）、4（阶段 2）、6 节。本机工作区位于 `/Users/casten/Documents/程序开发/求职/workspace`，依赖已装好。

本任务只实现 PLAN.md 的 M8：投递前的 30 天去重检查。它是一个只读的本地工具，不连接任何外部服务，也不产生投递动作。

## 2. 先调研，再编码
阅读项目根目录的 `README.md`、`CLAUDE.md` 与 `workspace/applications.md` 的格式说明，确认 tracker 的列格式、日期格式与状态取值。不要修改 `workspace/` 下的个人文件。自写代码放在 `/Users/casten/Documents/程序开发/求职/tools/` 下。

注意：tracker 是本机用户文件，默认路径为 `workspace/applications.md`，通过 `--tracker` 参数可配置。不要硬编码 `$HOME` 或扫描其他目录。

## 3. 实现要求
- 新建 Python 3 脚本 `求职/tools/precheck.py`（仅用标准库）。
- 命令行接口：`python3 -I tools/precheck.py --tracker <path> --company <name> --title <role> --city <city> --date YYYY-MM-DD --json`。
- 归一化：公司名去掉常见公司后缀（有限公司/股份有限公司/Ltd/Inc 等）、空白、大小写和全角半角差异；岗位名和城市同样做大小写与空白归一化；不要做激进的模糊匹配。
- 指纹：`sha256(normalize(company) + '|' + normalize(title) + '|' + normalize(city))`。
- 判定：tracker 中同指纹、状态不是 `Discarded`/`SKIP`、且 Date 在检查日前 30 天内的记录，返回 `block: true`，并列出匹配行；否则 `block: false`。
- 日期缺失或无法解析时，返回 `block: false` 并在 `warnings` 中列出该行，绝不静默丢弃。
- JSON 输出字段：`block`、`fingerprint`、`matches`（公司、岗位、日期、状态、原始行号）、`warnings`。
- 不联网、不写 tracker、不改 `workspace/` 下任何文件、不执行投递。
- 不创建虚构的申请记录。测试数据要明确标注为"测试数据"。

## 4. 测试要求
- 在 `求职/tools/tests/` 下写一个临时 tracker 样例，包含 5 行：同指纹 31 天前（应放行）、同指纹 10 天前（应拦截）、同指纹 10 天前但状态为 `Discarded`（应放行）、不同公司（应放行）、日期缺失（应放行并产生 warning）。
- 用 `python3 -I -m unittest discover -s tools/tests -v` 验证，自行编写对应的 `test_precheck.py`。
- 报告每个测试的名字与结果，以及命令的原始退出码。

## 5. 允许修改的路径
仅 `/Users/casten/Documents/程序开发/求职/tools/precheck.py`、`/Users/casten/Documents/程序开发/求职/tools/tests/*`。其他路径只读。若必须修改别的文件，先停止并说明原因。

## 6. 禁止事项
- 不执行 `git commit`、`git init`、`git push`，不删除或覆盖已有文件。
- 不新增任何招聘平台抓取、自动投递、绕过检测或微信/社媒 Hook 代码。
- 不写入凭据、API key、真实个人信息；不访问网络、邮箱、飞书或第三方 URL。
- 不使用 `sudo`、`--force`、`rm -rf`。
- 不派生子会话或子代理。
- 不修改 `workspace/` 下的任何个人文件。
- 遇到命令被权限拒绝时，停止后续步骤并原样报告，不换命令绕过。

## 7. 完成标准
- `precheck.py` 与测试文件存在。
- 5 个场景的测试全部通过。
- `git status --porcelain` 无输出（个人文件被忽略）。
- 报告列出所有新建文件、测试原始输出、未完成项。

## 8. 输出报告（最后一条消息）
1. 调研结论：tracker 的实际格式与状态取值。
2. 按步骤列出执行的命令与退出码。
3. 测试原始输出。
4. 所有新建文件的绝对路径。
5. `git status --porcelain` 原始输出。
6. 未完成项与不确定之处；不确定写"未确认"，不要猜测。
