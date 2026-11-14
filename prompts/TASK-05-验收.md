# TASK-05 验收记录（主会话实现与复核）

本记录对应 `prompts/TASK-05-interview-mock.md` 与 `PLAN.md` 第 3 节 M13/M14/M15、第 4 节阶段 4。实现只用 Python 3 标准库与本地虚构样例，不安装/运行 `faster-whisper`，不读取真实录音，不调用外部 API。

## 产出文件

- `tools/config_task05.json`：30 分钟分段、空题库提示、weakness 标签词表、题库路径、ASR 安装命令与离线边界。
- `tools/data/question-bank.json`：初始空结构；运行 demo 后写入 demo 隔离题库 `demo/question-bank.json`，不污染用户题库。
- `tools/mock_interview.py`：只从题库挑题，生成三段题单与文本问答记录；空题库明确写「题库为空，需补充题目」。
- `tools/asr_adapter.py`：`transcribe(audio_path, model_size, language)` 适配接口；未启用/未安装时返回 `unavailable`，不伪造转写。
- `tools/interview_debrief.py`：从逐字稿抽问题/答案/弱点标签，生成复盘卡片；新问题按文本 sha256 去重入题库；指令样文本原样引用。
- `tools/interview_analytics.py`：汇总多次复盘的高频弱点标签 JSON，不画图。
- `tools/tests/test_task05.py`：9 个离线测试。

## 已自动验证

| 测试 | 对应验收条目 |
|---|---|
| 空题库不编造题目，明确输出提示；30 分钟三段均存在 | M13 定向 Mock；任务规格第 4.1 节 |
| 题库题目按 sha256 去重，只从题库挑题；10/12/8 分钟分段与 60 分钟按比例缩放 | M14 模拟面试题单 |
| 题库 shape 错误、minutes 非法明确报错 | 模块降级与输入校验 |
| ASR 未启用/包可用但无显式 runner 时均返回 `unavailable`，`transcript: null` | M15 录音转写 adapter；不伪造转写 |
| 复盘卡片六个字段齐全；无证据字段为空数组；逻辑漏洞/量化不足标签来自显式文本 | M15 结构化复盘卡片 |
| 新问题重复抽取只入题库一次；指令文本不执行、写入 `input_anomalies` | 不可信外部内容边界；题库去重 |
| JSON 逐字稿、空问答、弱点标签频次统计 | M15 多次复盘聚合 |

## 需人工验证

- 一次真实 30 分钟模拟面试的互动质量、题目与真实 JD 的相关性：当前是离线题单，不实现对话式 AI 面试官。
- 真实录音的转写准确率、说话人分离、中文标点与专有名词：未运行 ASR。
- 复盘卡片中的弱点判断、业务逻辑漏洞、STAR 完整性：当前只抽取显式标记词，不对候选人下实质性评价。
- 用户手动补充的真实面经/题库内容是否准确、是否有版权或第三方隐私风险：需人工审查。

## 未实现 / 未确认

- 未安装、未 import、未运行 `faster-whisper`；未下载模型；未处理音频。
- 未实现语音采集、实时对话、自动评分、LLM 生成复盘结论或自动追问。
- 未接入 `PrepLabsAI/InterviewMentor` 插件运行；只保留本地题单与复盘结构。
- 真实 `faster-whisper` 模型大小、设备、语言、音频采样率与性能：**未确认**。
- 真实面经题库与公司业务动态：**未确认**，不编造。

## 真实启用 ASR 的步骤（不提问）

1. 在用户自己的 Python 环境中安装 `faster-whisper`：`python3 -m pip install faster-whisper`。
2. 由用户显式提供本地录音路径、模型大小、语言与运行确认；自行下载/缓存模型。
3. 用户自行实现或批准一个本地 runner，调用 `WhisperModel` 并把结果写成 JSON/Markdown 逐字稿，再交给 `interview_debrief.py`。
4. 当前 `asr_adapter.py` 只返回结构化状态，不会自动安装、联网或处理音频。

## 复核结论

离线 Mock 题单、复盘卡片与统计链路通过自动测试；真实语音转写与对话式模拟面试未执行，不记作已完成。代码中没有抓取、自动投递、凭据处理或外部 API 调用。
