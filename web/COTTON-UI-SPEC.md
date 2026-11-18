# 「墨靛」界面改版规格（取代「信号」配色）

状态：设计方案，实施中（2026-11-18）。实现完成并经主会话浏览器复核后，结论并入 `web/DESIGN.md`。`web/SIGNAL-UI-SPEC.md` 的版面与交互规则继续有效，**本规格只换皮肤与组件质感**：颜色、字体、圆角、阴影、组件细节。

来源：用户自有项目「棉见 · 织物洞察台」的设计 DNA（`~/Documents/ChatGPT/前端审美积累/collections/001-mianjian-fiber-intelligence/analysis/design-dna.md`，含截图）。借的是方法，不是品牌：

- 暖/冷白画布 + 墨靛深色章节，**极少量**茜红做唯一情绪信号；
- 衬线做展示标题，无衬线做操作文字，等宽数字做编号和数据；
- 产品窗口式卡片（标题栏 + 内容区），让真实数据当主角；
- 不照搬棉纤维/经纬/棉花等品牌母题，不用渐变装饰。

用户原话：「黄色底不太合适」。当前 `--sg:#D2F53C`（酸性黄绿）与 `#F2F3F0`（偏绿灰底）整体改掉；新界面里**任何位置都不得出现 #D2F53C、#9BC21A**，画布也不得偏黄/偏米色（所以不用棉见的 #F2EEE4，改用冷白纸面）。

## 1. 范围与分工（互不重叠）

两个新文件，各由一个写入者负责，**都不改任何已有文件**（`index.html` 的 `<link>` 由主会话统一加，已加）：

| 文件 | 负责 | 内容 |
| --- | --- | --- |
| `web/static/mj-base.css` | 会话 A | 第 2 节 token（浅/深/跟随系统）与对旧 token 的重映射、全站通用组件（第 4 节）、顶栏、侧栏、首页 `#view-workbench`、对话助理 `#view-agent`、设置 `#view-data`、顶部轻提示 `#status`、滚动条与焦点环 |
| `web/static/mj-pages.css` | 会话 B | 页面级：`#view-collect`、`#view-jobs`、`#view-queue`、`#view-mail`（含 HR 会话收件箱与回复对话框、`#hr-reply-confirm-panel`）、`#view-profile`、`#view-resume`、`#view-interview`、`#view-push` |

加载顺序：在 `sg-tools.css` 之后，先 `mj-base.css` 后 `mj-pages.css`。**B 只使用本规格第 2 节的 `--mj-*` 变量和已有变量，不自己定义 token**，这样两边可以同时开工。

选择器规则：所有选择器以 `body.offer-ui:not(#wa-theme-off)` 开头（与现有层同级特异性，靠加载顺序取胜）；深色用 `:root[data-theme="dark"] body.offer-ui:not(#wa-theme-off)`，并为「跟随系统」写一份 `@media (prefers-color-scheme: dark) { :root:not([data-theme]) body.offer-ui:not(#wa-theme-off) {…} }`。不用 `!important`，除非覆盖内联样式或旧文件的 `!important`，且需在代码里注明被覆盖的位置。

**禁止**：改 `index.html` / `app.js` / `backend.py` / 其他 CSS；新增、重命名、删除任何 id、`data-*`、类名；改动文案；引入远程字体、图片、`@import`。若某处必须改 HTML 才能达成，记在回报里，由主会话决定。

## 2. Token（`--mj-*`，由 A 在 `mj-base.css` 里定义）

| 名 | 浅色 | 深色 | 用途 |
| --- | --- | --- | --- |
| `--mj-canvas` | #F4F5F8 | #111629 | 页面底（冷白纸面，不偏黄） |
| `--mj-paper` | #FFFFFF | #1A2140 | 面板、输入框、窗口体 |
| `--mj-paper-2` | #F8F9FC | #202850 | 窗口标题栏、表头底、次级面 |
| `--mj-ink` | #1E2746 | #ECEFFA | 标题与主按钮底（墨靛） |
| `--mj-text` | #202326 | #E3E6F3 | 正文 |
| `--mj-text-2` | #4A5168 | #AEB5D0 | 说明、表头（对比度 ≥ 4.5） |
| `--mj-mute` | #6B7289 | #8E96B8 | 时间、单位、占位（对比度 ≥ 4.5） |
| `--mj-line` | rgba(30,39,70,.10) | rgba(236,239,250,.12) | 唯一分隔/描边 |
| `--mj-brand` | #3B477A | #AEB9F0 | 品牌靛蓝：选中、链接、聚焦、进度 |
| `--mj-brand-ink` | #FFFFFF | #111629 | 品牌色上的字 |
| `--mj-brand-soft` | #E9ECF7 | #262F5C | 选中底、悬停底、页签轨道 |
| `--mj-spark` | #C45B6C | #E58A98 | 茜红：**唯一**情绪信号，只做小面积（未读点、计数角标、选中左侧 3px 条、危险以外的强调线），一屏不超过 5 处，绝不做大面积底、正文色或按钮底 |
| `--mj-good` / `--mj-good-bg` | #1E7A52 / #E7F4EC | #7FD9B0 / #123629 | 成功 |
| `--mj-warn` / `--mj-warn-bg` | #8A5A00 / #FBF1DC | #F2C777 / #3A2C10 | 警告 |
| `--mj-bad` / `--mj-bad-bg` | #B3374A / #FBE9EC | #F29AA8 / #3E1A22 | 错误、删除 |
| `--mj-serif` | "Songti SC","Source Han Serif SC","Noto Serif CJK SC","STSong",serif | 同 | 展示标题、首页日期、KPI 大数字 |
| `--mj-mono` | ui-monospace,"SF Mono","JetBrains Mono",Menlo,monospace | 同 | 时间戳、编号、表格数值列，配 `font-variant-numeric: tabular-nums` |
| `--mj-r-stage` / `--mj-r-card` / `--mj-r-inner` / `--mj-r-control` / `--mj-r-tag` | 24 / 14 / 12 / 10 / 8 px | 同 | 圆角层级 |
| `--mj-shadow-card` | `0 1px 0 rgba(30,39,70,.04), 0 14px 34px -20px rgba(30,39,70,.22)` | `0 1px 0 rgba(0,0,0,.2), 0 14px 34px -20px rgba(0,0,0,.6)` | 卡片 |
| `--mj-shadow-float` | `0 18px 44px -16px rgba(30,39,70,.30)` | `0 18px 44px -16px rgba(0,0,0,.7)` | 弹窗、下拉、轻提示 |
| `--mj-glass` | rgba(255,255,255,.72) | rgba(26,33,64,.72) | 侧栏、顶栏（配 `backdrop-filter: blur(14px) saturate(1.1)`） |

### 对旧 token 的重映射（A 负责，让没改到的旧规则自动换色）

在 `body.offer-ui:not(#wa-theme-off)` 上（浅/深/跟随系统三份）：

- `--bg` ← `--mj-canvas`；`--surface` ← `--mj-paper`；`--ink` ← `--mj-text`；`--ink-2` ← `--mj-text-2`；`--mute` ← `--mj-mute`；`--line` ← `--mj-line`
- `--accent`、`--accent-fill` ← `--mj-ink`；`--accent-ink` ← 浅色 #FFFFFF、深色 #111629；`--accent-soft` ← `--mj-brand-soft`；`--pill` 同 `--mj-paper-2`
- `--sg` ← `--mj-brand`；`--sg-ink` ← `--mj-brand-ink`；`--sg-sg-mark` ← `--mj-spark`；`--ui-signal`、`--offer-pink` ← `--mj-spark`；`--wa-brand`、`--wa-focus`、`--focus`、`--focus-ring` ← `--mj-brand`（focus-ring 取 brand 的 35% 透明）
- `--good/--good-bg/--warn/--warn-bg/--bad/--bad-bg/--danger` ← 对应 `--mj-*`；`--neutral-bg`、`--code-bg` ← `--mj-paper-2`
- `--series-1` ← `--mj-brand`、`--series-2` ← `--mj-spark`、`--series-3` ← #8C9AD6（深色 #7E8BD0）；`--stage-0…4` 为靛蓝渐深：#E3E7F6、#C3CBEA、#8C9AD6、#5C69A6、#3B477A（深色反向：#2A3366…#C3CBEA）
- `--chart-grid` ← `--mj-line`

旧文件里写死 `#D2F53C`（`workbench-agent.css` 的 `--wa-brand`/`--wa-focus`/`--sg`、`sg-base.css` 的 `--sg-sg-mark`）会被上面同特异性、更靠后的重映射盖掉；A 复核一遍深色下是否仍有黄绿残留。

## 3. 字体与字阶

- 展示（`--mj-serif`，字重 600）：页标题 `.view-title`（34–40px，行高 1.15，字距 -0.01em）、面板主标题 `.panel-head h2/h3`（17–18px）、首页日期大数字与 KPI 大数字、HR 收件箱标题、确认对话框标题。
- 操作与正文：沿用系统无衬线（苹方/HarmonyOS/微软雅黑）。正文 14/1.6，说明 13/1.55 `--mj-text-2`，元信息 12 `--mj-mute`。
- **下限 12px**：新文件里不得出现小于 12px 的 `font-size`（现有 9–11px 辅助字全部提到 12）。
- 数字：`--mj-mono` + tabular-nums，用于表格数值列、时间、编号、计数；首页大数字与 KPI 用 `--mj-serif`。

## 4. 通用组件（A 负责，B 复用，不重复定义）

1. **页头 `.view-head`**：序号小标签（`--mj-mono`，12px，`--mj-mute`）+ 衬线标题 + 一句导语 `--mj-text-2`；下边距 20px，无分隔线。
2. **面板 `.panel` = 产品窗口**：`--mj-paper`、圆角 `--mj-r-card`、`inset 0 0 0 1px var(--mj-line)` 加 `--mj-shadow-card`；`.panel-head` 做窗口标题栏：背景 `--mj-paper-2`、下边 1px `--mj-line`、内边距 12px 18px，标题衬线 17px，右侧计数用 `--mj-mono`；面板体内边距 18–20px。面板之间 16px。**三点标识**（三个 8px 圆点，`--mj-line` 实心）只用在首页深色概览卡的标题栏和对话助理主面板，用 `::before` 实现，不加 DOM。
3. **按钮 `.button`**：圆角 `--mj-r-control`（不再是胶囊），高 38，字重 600。主操作 `--mj-ink` 底、白字，悬停 `--mj-brand` 底；`.button-quiet` 用 `--mj-brand-soft` 底、`--mj-ink` 字；`.button-small` 高 30；禁用 opacity .45、`not-allowed`；危险只用 `--mj-bad` 文字按钮。按压 `scale(.98)`，160ms。
4. **徽标 `.badge`、`.chip`**：高 22、圆角 `--mj-r-tag`、12px、不换行；good/warn/bad 用对应浅底深字；neutral 为 1px `--mj-line` 线框；**不再用实心强调色底**。
5. **表单**：标签 12.5 `--mj-text-2` 在上；控件高 40、圆角 `--mj-r-control`、`--mj-paper` 底、1px `--mj-line` 描边；聚焦 2px `--mj-brand` 外环（`outline` 或 `box-shadow`，不改布局）；占位 `--mj-mute`；必填标记用 `--mj-spark`。
6. **表格**：表头 12/600 `--mj-text-2`、`--mj-paper-2` 底、sticky；行高 ≥ 48、行间 1px `--mj-line`；悬停 `--mj-brand-soft`；选中行左侧 3px `--mj-spark` 条；数值列右对齐 + `--mj-mono`；横向滚动只在表格容器内。
7. **页签 `.ui-hub-tabs`**：轨道 `--mj-brand-soft`、圆角 `--mj-r-control`；选中项 `--mj-ink` 底白字（深色 `--mj-brand` 底 `--mj-brand-ink` 字）；序号与文字同一行不换行。
8. **提示 `.notice`、`.action-result`、`#status`**：浅底 + 左 3px 色条（good/warn/bad，`notice-accent` 用 `--mj-brand`）；`#status` 右上浮起，`--mj-shadow-float`，圆角 `--mj-r-card`。
9. **侧栏 `.sidebar` 与顶栏 `.topbar`**：`--mj-glass` 毛玻璃，下/右边 1px `--mj-line`；侧栏项高 40、圆角 `--mj-r-control`；当前项 `--mj-brand-soft` 底、`--mj-ink` 字，左侧 3px `--mj-spark` 条；序号 `--mj-mono`；未读/待办角标用 `--mj-spark` 底白字，圆角 `--mj-r-tag`，高 18 以上。
10. **滚动条**：8px、`--mj-line` 滑块，圆角 4。
11. **焦点**：全站 `:focus-visible` 为 2px `--mj-brand` 外环 + 2px 偏移，深色同理。
12. **动效**：只动 `transform`/`opacity`/颜色，160–320ms；`@media (prefers-reduced-motion: reduce)` 下全部取消动画与过渡。

## 5. 页面（A 做首页/助理/设置，B 做其余）

- **首页**（A）：画布 `--mj-canvas`。日期大数字 `--mj-serif` 140px 字重 600、`--mj-ink`；深色概览卡改为「墨靛章节」：背景 `--mj-ink`（深色主题下 `#1A2140`），圆角 `--mj-r-stage`，卡内文字 #ECEFFA，右上角一枚 `--mj-spark` 小圆点（直径 10，仅此一处用茜红大于 8px），标题栏三点标识；待办行是「纯行」（沿用现有 `.home-task` 结构，不加卡片边框与圆角——现有测试要求首页块无 `border-radius`/`box-shadow`），计数用 `--mj-serif` 大数字；流水线概览面板的数字用 `--mj-mono`。
- **对话助理**（A）：主面板窗口式；用户气泡 `--mj-brand-soft` 底，助理气泡 `--mj-paper` + 线框；输入区 `--mj-paper` 底、圆角 `--mj-r-card`；快捷提问为描边胶囊（圆角 `--mj-r-control`）。
- **设置**（A）：配置/边界/导出分块为窗口面板；开关与单选组选中态用 `--mj-brand`。
- **采集页**（B）：本次条件行、合格线输入、平台选择格：选中平台用 1.5px `--mj-brand` 描边 + `--mj-brand-soft` 底；预检结果列表 good/warn/bad 色条；任务进度条 `--mj-brand`，完成 `--mj-good`。
- **岗位池 / 审批 / 流水线**（B）：筛选栏紧凑；表格按第 4 节；批量操作条贴底，`--mj-shadow-float`；评分用 `--mj-mono`，≥ 合格线用 `--mj-good`，低于用 `--mj-text-2`（不用红）。
- **HR 回复**（B）：双栏收件箱。左列会话项：未读点 `--mj-spark`（8px），选中项 `--mj-brand-soft` 底 + 左 3px `--mj-spark` 条；平台标记为 `--mj-r-tag` 小方块；右列气泡：HR 在左 `--mj-paper-2`，我在右 `--mj-brand-soft`，摘要预览气泡虚线描边；发送区 `--mj-paper`；确认对话框 `--mj-shadow-float`，圆角 `--mj-r-stage`，标题衬线。
- **个人资料 / 定制简历 / 模拟面试 / 信息推送**（B）：全部用第 4 节通用组件；左侧步骤导航、进度条、完成态用 `--mj-brand` / `--mj-good`；模块卡 `--mj-r-card`；拖拽上传区虚线 1.5px `--mj-line`，悬停 `--mj-brand`。

## 6. 验收

1. `sh tools/run_tests.sh` 全绿；`node --check web/static/app.js`；不得为让测试通过而改旧测试断言。
2. 各自新增测试文件（只读 CSS 文本，不起浏览器）：
   - A：`tools/tests/test_cotton_ui_base.py`；B：`tools/tests/test_cotton_ui_pages.py`。
   - 至少断言：文件存在且已被 `index.html` 引用，顺序在 `sg-tools.css` 之后；不含 `#D2F53C`、`#9BC21A`、`#F2EEE4`、`!important` 滥用（B 文件 `!important` ≤ 3 处且有注释）；没有小于 12px 的 `font-size`；每条选择器以 `body.offer-ui:not(#wa-theme-off)` 或 `:root[data-theme="dark"] body.offer-ui:not(#wa-theme-off)` 开头（`@media` 内同理）；存在 `prefers-reduced-motion` 块；A 文件定义了第 2 节全部 `--mj-*` 名；B 文件只引用 `--mj-*` 而不定义（`--mj-` 变量不出现在冒号左侧）。
3. 桌面宽度 1280×800 浏览器走查（`http://127.0.0.1:8766/`，浅色与深色各看一遍）：左侧 8 个入口、岗位流水线四个页签（采集/岗位池/审批/回复）逐页看，无横向溢出，无遗留黄绿，12px 以下文字为零，控制台无新增报错。手机宽度不管，但不得引入新的横向溢出。
4. 回报：改了哪些区段、没做到哪些、需要主会话改 HTML 的位置清单、测试结果原文。**不要提交**（主会话复核 diff 后统一提交）。
