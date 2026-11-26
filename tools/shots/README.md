# 静默截图矩阵

改样式/布局时的验收工具：一次截下关键界面，再和基线做像素比对。**编译通过 ≠ 没改坏。**

底层用的是主进程自带的 `--screenshot`（透明窗口 + `capturePage` + `app.exit`），
**桌面上什么都不出现**、可以后台跑，也不参与启动失败计数（见 `desktop/main/launchguard.cjs`）。

## 用法

```bash
# 1) 生成一套截图（默认到 docs/images/shots/current）
bash tools/shots/capture_matrix.sh

# 2) 换视口 / 指定状态 / 输出目录
bash tools/shots/capture_matrix.sh --out /tmp/shots --size 1440x960 --states "review settings"

# 3) 和基线比（PSNR；inf 或 >80dB 视为一致，<35dB 基本可判定改坏了）
bash tools/shots/capture_matrix.sh --compare docs/images/shots/baseline

# 4) 一次跑三套主题：文件名带 -light / -dark / -mincho 后缀
bash tools/shots/capture_matrix.sh --theme dark --states "polish reshape dual"

# 5) 重出 README 成品图（见下一节）
KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox bash tools/shots/capture_matrix.sh \
  --seed tools/shots/readme-seed.json --delay 12000 \
  --states "import transcribe review translate export settings"
```

沙箱或 CI 里 Electron 起不来时，用 `KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox` 追加启动参数；
脚本会为每张图使用独立的临时 `--user-data-dir`，不会落到用户的 Application Support。

`--theme` 的 `polish / reshape / dual` 拍的是**空态**。带字幕、B 版与提案的 AI 三页基线用
下一节的专用脚本。

状态名：`import` `transcribe` `review` `dual` `polish` `translate` `export` `settings` `prompts`。
`--seed` 指定种子（默认 `tools/shots/seed.json`；`--seed tools/shots/readme-seed.json` 是 README 成品图那份）。
**导入 / 转写 / 核对 / 翻译 / 导出这五个状态都用种子**：空态的转写与导出页只有一句「先导入媒体」，
对验收和 README 都没信息量。其余状态靠 `KIKUSUB_DEV_EVAL` 点侧栏切换，截到的是真实页面而不是空壳。

> 早期 `transcribe` 状态其实没有点侧栏，截出来是导入页——文件名一直在骗人。现在每个状态都显式点
> `.sb-item[n]`；导出页额外等 3 秒，让样式预览取回当前帧，否则会截到「渲染中…」+ 纯色底。

## README 成品图

`docs/images/*.jpg` 由同一套无窗口路径生成，只是种子不同：

- `tools/shots/readme-seed.json`：12 条演示台词 + 一版中文译文 + 一份「另一引擎」结果，时间挪到
  《言叶之庭》约 2:00 的那座桥——不挪的话首帧是黑场，首屏截图会是一整块黑。
- 主图 `review`、`transcribe`、`translate`、`export` 用上面第 5 条命令；双引擎 / 润色 / 断句重排用
  `capture_ai_workbench.mjs --theme light --states "polish-dual,reshape-draft,dual" --size 1440x900`。
- 设置页两张（引擎与模型 / AI 与技能折叠态）单独一个脚本——要等引擎注册表落地，否则会截到
  半透明骨架屏：`bash tools/shots/capture_settings_pages.sh /tmp/readme-settings`
  （加 `KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox` 可在沙箱里跑）。
- 落盘是 2× Retina PNG，转 JPG 用 `sips -Z 2000 -s format jpeg -s formatOptions 82`。

## AI 三页专用矩阵

润色 / 断句重排 / 双引擎复核的代表状态需要「有种子字幕 + 一份假提案 + 一份 B 版边车」；
`capture_matrix.sh` 只给 `review` 灌种子，所以这三页单独一个 Node 脚本：

```bash
# 默认三页 × 三主题 → docs/images/shots/current-ai
node tools/shots/capture_ai_workbench.mjs --out /tmp/ai-current

# 只跑青空深 / 只跑某几页
node tools/shots/capture_ai_workbench.mjs --out /tmp/ai-current --theme dark --states "polish-dual,dual"

# 沙箱 / CI
node tools/shots/capture_ai_workbench.mjs --out /tmp/ai-current --no-sandbox

# 采完直接和基线做 PSNR
node tools/shots/capture_ai_workbench.mjs --out /tmp/ai-current --compare docs/images/shots/baseline
```

状态：`polish-dual`（A 12 / B 9 / AI 终稿）、`reshape-draft`（粘入 9 条新稿后的新旧对照）、
`dual`（双引擎差异表）。输出名 `<state>-<theme>-<1360x838>.png`，与 `capture_matrix.sh` 一致。
夹具在系统临时目录生成，固定了提案与 B 版边车的时间戳，因此同一台机器上可逐像素复现。

## 断句重排分段计划回归

用户报障过的交互（2026-11-15「覆盖两段后切单源再切回双源，4 段变 3 段」）有专门的行为回归：
501 条 A + 516 条 B，在真实界面里跑「切换源 / 覆盖两段 / ⌘Z 撤回 / 核对台删一条」，
断言段轨、勾选、失效横幅与出口按钮。

```bash
# 两个场景（flow：冻结与 ⌘Z 同步；stale：外部改动横幅）
node tools/shots/verify_reshape_flow.mjs

# 只跑一个场景
node tools/shots/verify_reshape_flow.mjs --scenario stale
```

同样走 `--screenshot` 静默路径（透明窗口 + `capturePage` + `app.exit`，桌面上不出现），
断言失败退出码非 0。契约口径见 `docs/contracts/ai-proposal.md` §3.7.6。

## 外壳几何与主题对比度（Phase 2）

核对台改过外壳之后，有三件事既有脚本看不到：**52px 收起态与系统红绿灯的安全区**、
**暗底监看舞台的比例与状态条**、**1px 分割线 / 状态条文字的对比度**。
红绿灯是原生绘制、DOM 读不到，所以脚本量的是渲染层能负责的那一半（开关必须移出左栏
且让出安全区、与三颗灯同一水平线、品牌图标与第一个导航项的位置）；对比度则按 CSS 令牌
**实算** WCAG 比值，不靠肉眼。

```bash
node tools/shots/verify_phase2_shell.mjs
# 沙箱 / CI：KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_phase2_shell.mjs
```

40 条断言，亮 / 暗两套主题 + 紧凑模式（880px 真实窄窗）各跑一遍，失败退出码非 0。收起态除了「开关必须移出左栏」，
还断言它与红绿灯的**横向净空 ≥16px、中线差 ≤1px**，以及顶部 40px 是一整块底色
（竖分割线从 y=40 起，不横穿红绿灯）。口径见
`docs/contracts/review-console.md` §3.4.13。

## 清理标点回归

用户报障过的两类行（2026-11-17「句中顿号被换成空格」「行尾省略号点了不动」）有专门的
行为回归：种子字幕里放上截图那几句 + 两个反例，在真实界面里打开「清理标点」浮层，断言
统计、三条 before→after、标红字符、两组口径（句中 / 省略号）切换、v2 偏好键。

```bash
node tools/shots/verify_punct_clean.mjs
# 沙箱 / CI：KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_punct_clean.mjs
```

截图落在 `/tmp/kikusub-punct-verify/punct-clean.png`。契约口径见
`docs/contracts/review-console.md` §3.4.4。

## 译文轨三态与单句补译回归

2026-11-25 用户报障的两件事：清理标点后译文区一堆「待更新」（其实内容没问题）、
局部转写补一句把整条译文轨删掉。脚本在真实界面里断言：待译 / 原文已改两种计数分开、
只改标点不过期、真改字才过期、待译行显示「待译」、AI 补译的草稿进输入框并能采纳、
请求材料只带前后几行原文 + 邻居已有译文。AI 那一跳指向脚本自己起的假模型
（独立进程），不需要 LM Studio 或网络。

```bash
node tools/shots/verify_translation_flow.mjs
# 沙箱 / CI：KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_translation_flow.mjs
```

截图落在系统临时目录的 `kikusub-translation-flow/translation-flow.png`。契约口径见
`docs/contracts/review-console.md` §3.4.20。

## 复制 / 粘贴字幕回归

气声句（吸って / 入って）从「偶尔转对的一条」复制到两个播放头位置，是 2026-11-17 的新流程。
脚本在真实界面里断言：检查器复制按钮与 `⌘⇧C` 都会先提交未失焦的草稿、粘贴后是 4 条 /
再粘 5 条、一次撤回回到 4 条、播放头与缩放不变、新句被选中。

```bash
node tools/shots/verify_cue_clipboard.mjs
# 沙箱 / CI：KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_cue_clipboard.mjs
```

截图落在系统临时目录的 `kikusub-cue-clipboard/cue-clipboard.png`（macOS 通常是
`$TMPDIR/kikusub-cue-clipboard/`）。契约口径见 `docs/contracts/review-console.md` §3.4.2。

## 核对台专业剪辑回归

`←/→` 逐帧、`⌘←/⌘→` 逐秒、`Q/E` 入出点、`W` 切割、`⇧Space` 试听、`N` 磁吸、
`⇧Z` 全片切换、`1/2/3` 倍速，以及「高速连按以同步 `play.time` 为基准」和
「方向键不触发 WebView 前进/后退」。脚本生成 24fps 测试片，断言真实界面里的时间码、
字幕行、`video.playbackRate / preservesPitch` 与 URL/history。

```bash
node tools/shots/verify_review_transport.mjs
# 沙箱 / CI：KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_review_transport.mjs
```

截图落在系统临时目录的 `kikusub-review-transport/review-transport.png`。契约口径见
`docs/contracts/review-console.md` §3.4.6。

## 播放头拖到边缘自动滚动回归

把播放头拖过波形左右缘后，视窗与播放头一起继续推进（指针压住不动也走）。脚本用
合成 `PointerEvent` 覆盖：单击刻度条不自动滚、右缘推进时播放头钉住且缩放不变、
松手立刻停、松手后画面落在最终位置、往左对称。

```bash
node tools/shots/verify_scrub_pan.mjs
```

截图落在系统临时目录的 `kikusub-scrub-pan/scrub-pan.png`。契约口径见
`docs/contracts/review-console.md` §3.4.6「拖到边缘自动滚动」。

## 章节草稿（把时刻点补成区间）回归

先找到场景结束（插时刻点），再回头找开始——两个端点分别落位，不用把 14 分钟塞进一屏。
脚本覆盖：补起点 / 补终点、`I` / `O` 落端点、时间轴虚线预览、端点越界拦截、
Esc 撤草稿、保存后 ⌘Z 退回时刻点。

```bash
node tools/shots/verify_chapter_draft.mjs
```

截图落在系统临时目录的 `kikusub-chapter-draft/chapter-draft.png`。契约口径见
`docs/contracts/review-console.md` §3.4.9「章节草稿」。

## 章节页（自动命名 / 加入转写选区）回归

章节页重做后的回归：新建区与行内操作、时刻点补成区间时的自动命名（章节二 / 章节三）、
「加入转写选区」跳到转写页并填好起止、设置里改模板后新章节按新模板命名（场景四）。

```bash
node tools/shots/verify_chapter_panel.mjs
```

截图落在系统临时目录的 `kikusub-chapter-panel/chapter-panel.png`。契约口径见
`docs/contracts/review-console.md` §3.4.9「自动命名 / 加入转写选区」。

## 章节区间端点拖动回归

区间章节两端直接在 6px 色条上拖：旗标拖过 4px 改起点（单击仍是跳转），右端抓手改终点；
拖到边缘时视窗自己平移。脚本覆盖拖动、⌘Z 撤销、压住右缘继续推进、拖动不 seek。

```bash
node tools/shots/verify_chapter_edge.mjs
```

截图落在系统临时目录的 `kikusub-chapter-edge/chapter-edge.png`。契约口径见
`docs/contracts/review-console.md` §3.4.9「端点拖动」。

## 点行选区与单句 AI 判定回归

2026-11-20 新增两条用户报障/新流程的静默回归：

```bash
# 点表格行 / 点底部字幕块 → 选区工具条；Esc 只清选区、不丢当前行
node tools/shots/verify_cue_selection.mjs

# A/B + 第三版卡片：徽章、理由、朗读、采用按钮（dev seed，不加载模型）
node tools/shots/verify_arbitration.mjs

# 常驻 AI 区（B 返回空也能用）+ 听音线索草稿缓存 + 多轮对话浮窗拖动/缩放/Esc
# 以及：发送追问 / 清空重判彻底分离（重判请求体无旧 history）、撤销追问后结果卡同步、
# 复制按钮、文本可选中、右侧只保留一个对话入口
node tools/shots/verify_arbitration_dialog.mjs
```

都走 `--screenshot` 静默路径；沙箱环境加
`KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox`。截图落在系统临时目录的
`kikusub-cue-selection/`、`kikusub-arbitration/` 与 `kikusub-arbitration-dialog/`。

## 片段范围（局部处理 / 导出）回归

「只处理 / 只导出这一段」的三页联动（润色 / 翻译 / 导出）有专门回归：区间章节设为范围后，
字幕条数变成 `4 / 5`、润色与翻译表格只剩 4 行、仅封装给出关键帧说明、字幕导出的 SRT
已归零且只含这一段、成片 ffprobe 时长 = 12s 且「发射点」平移到 8.5s、章节面板
「仅处理此片段」一键带入。

```bash
node tools/shots/verify_clip_scope.mjs
# 截图停在润色页 / 翻译页
KIKUSUB_FINAL_VIEW=polish node tools/shots/verify_clip_scope.mjs
# 沙箱 / CI
KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_clip_scope.mjs
```

截图落在系统临时目录的 `kikusub-clip-scope/clip-scope.png`。契约口径见
[ai-proposal.md](../../docs/contracts/ai-proposal.md) §3.7.8 与
[export-and-prompt.md](../../docs/contracts/export-and-prompt.md) §3.8.2。

## 手动分批 / 译文时间轴对齐 / 局部重排回归

润色页手动批次（1–2 → 下一批 → 3–4，复制 / 粘回只含本批，润色仍严格等条数）、
翻译页默认按时间轴对齐（4 条原文贴 3 条：合并覆盖 / 空缺 / 范围外高亮，严格开关
打开后回到 422）、断句重排页接入处理范围（越界高亮、只替换本段、范围外尾部译文
保持对齐，总条数 6 → 5）。

```bash
# 沙箱 / CI 环境
KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_batch_and_align.mjs
```

截图落在系统临时目录的 `kikusub-batch-align/batch-align.png`。契约口径见
[ai-proposal.md](../../docs/contracts/ai-proposal.md) §3.7.9–§3.7.11。

## 设置页专用矩阵

设置页的取证要「先切主题、再切页签」（主题卡只在外观页里），所以单独一个脚本：

```bash
bash tools/shots/capture_settings_matrix.sh --out /tmp/kikusub-settings-shots
# 只跑其中几张：
bash tools/shots/capture_settings_matrix.sh --only light-engines,dark-env
```

产出 3 主题 × 4 页签 + 4 张展开态/窄视口，共 16 张 PNG。仓库里提交的是转成 WebP 的同一批
（体积约 1/3），转换命令与当次结论见
`docs/sprints/2026-11-settings-redesign/落地记录.md`。

## 设置 AI「进阶」折叠 + 导出页收尾回归

2026-11-21（界面重构 Step 6）新增。四件在真实界面里断言：

- 全新配置时「进阶：单句判定独立模型与本地部署」默认收起，顶层只剩核心配置；
- 预置判定地址 / 模型 + 自动判定时默认展开（既有高级配置不会因为折叠而消失）；
- 点开 / 收起都生效，收起后摘要是「跟随全局 / 已单独配置 / 本机 LM Studio · 自动判定开/关」；
- 导出页底部不再有「为什么在 KikuSub 里导出」，无译文轨时置灰的「译文 / 双语」旁有引导。

```bash
node tools/shots/verify_settings_ai_fold.mjs
# 沙箱 / CI
KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_settings_ai_fold.mjs
```

截图落在系统临时目录的 `kikusub-settings-ai-fold/`：`settings-ai-fold-collapsed.png`、
`settings-ai-fold-configured.png`、`export-track-hint.png`、`export-bottom.png`。
契约口径见 [ai-proposal.md](../../docs/contracts/ai-proposal.md) §3.7.7 与
[export-and-prompt.md](../../docs/contracts/export-and-prompt.md) §3.8.2。

## 设置四页布局回归（不越界 / 不重叠 / 不挤成竖条）

2026-11-24 新增。用户报「设置每个子页都显示异常」时，真正坏的不是断点，是
`.set-row-ctl { flex: 0 0 auto }` 让控件列永不收缩：一条「路径 + 徽标 + 三个按钮」
把左侧说明压成 46–160px、9–11 行的竖条，音色克隆卡的步骤链还会压住右侧按钮。
这个脚本不比较像素（字体微调就会红），只断言三条布局不变量：

- 内容区里没有元素的右边界越过 `.set-content`；
- 没有两块可见文字（按钮 / 徽标 / 步骤 / 标题 / 说明 / 输入框）互相压住；
- 没有可见文字元素 `scrollWidth > clientWidth`（`.set-path` 的省略号是有意的，放行）。

四页 × 三种视口条件（1440×900 / 1120×800 / 1000×700）；**不含 200% 缩放**（红线 14，见下），
每个视口里都把折叠区展开再量。修复前会红 13 条。

```bash
node tools/shots/verify_settings_layout.mjs
KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_settings_layout.mjs
```

契约口径见 [review-console.md](../../docs/contracts/review-console.md) §3.4.16。

> **不看 200% 页面缩放**（2026-11-24，`AGENTS.md` 红线 14 / desktop-lifecycle §3.7.1）：
> 应用没有缩放菜单，200% 的视口只有 680×419，布局必然塌。它**不是**验收条件，
> 不要在脚本里加 `zoom200` / `KIKUSUB_ZOOM=2` 用例（只会稳定报假红）。
> `KIKUSUB_ZOOM` 取证开关仍在，但要手动看一眼时才用。

## 基线

`docs/images/shots/baseline/` 现在有两组基线：

- **三屏基线**（2026-11-13）：`transcribe` / `review` / `settings`，1360×838，文件名 `<state>-1360x838.png`。
- **AI 三页基线**（2026-11-15）：`polish-dual` / `reshape-draft` / `dual` × `light` / `dark` / `mincho`，
  文件名 `<state>-<theme>-1360x838.png`。

**改动有意的视觉调整时**：先跑一遍 `--compare baseline` 确认差异只落在预期区域，再把新的
`current` 覆盖回 `baseline`，并在提交信息里写清改了什么。AI 三页的覆盖命令：

```bash
node tools/shots/capture_ai_workbench.mjs --out /tmp/ai-current
node tools/shots/capture_ai_workbench.mjs --out /tmp/ai-current --compare docs/images/shots/baseline
# 人工确认差异只落在预期区域后：
node tools/shots/capture_ai_workbench.mjs --out docs/images/shots/baseline
```

旧的 `capture_matrix.sh --compare docs/images/shots/baseline` 仍用于三屏基线；两组文件名不冲突。

## 已知的非确定性

`settings` 页有少量运行时文本（模型目录、日志尾巴），PSNR 会落在 85–99dB 之间波动，
不是回归。`transcribe` / `review` 在同样 seed 下是逐像素一致的（inf）。AI 三页的夹具时间戳固定，
同一台机器上应接近逐像素一致；状态栏的加速设备（MPS / CPU）随机器不同，不作为跨机器基线。

## 核对台工作现场持久化回归

切去别的页面再回来，波形包络**不重新请求**、缩放 / 播放头 / 选区按原样恢复，快照按
媒体路径写进 localStorage（最近 50 部）。脚本在真实界面里统计 `/peaks` 请求数并读回
`localStorage['kikusub.reviewViewports']`。

```bash
node tools/shots/verify_review_viewport.mjs
# 沙箱 / CI：KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_review_viewport.mjs
```

截图落在系统临时目录的 `kikusub-review-viewport/review-viewport.png`。契约口径见
`docs/contracts/review-console.md` §3.4.7。

## 核对台「打开体验 + 右侧栏不溢出」回归

2026-11-21（界面重构 Step 3）新增。10 分钟「长片」+ 已挂译文轨的种子，断言：

- 没有本机现场快照时默认**聚焦第 1 条字幕 + ~50× 视野**，并且真的 seek 到第 1 条
  （不再停在片头黑场）；短片（≤60s）仍保持全片视图；
- 有译文轨时默认**双语**，且只生效一次（手动切回原文后，换页回来不许再翻回去）；
- 1360×838 下从显示模式到 AI 判定整块**不用滚动**就能操作，也不会滑到底部保存栏下面；
- 操作行里「试听原声 / 朗读 / 音色 / ⚙」同一行，朗读面板默认收起、点开后也在可视高度内。

```bash
node tools/shots/verify_review_defaults.mjs
# 沙箱 / CI：KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_review_defaults.mjs
```

截图落在系统临时目录的 `kikusub-review-defaults/review-defaults.png`。契约口径见
[review-console.md](../../docs/contracts/review-console.md) §3.4.10。

## 章节 / 时刻点标记与成片写入回归

检查器「章节」页签 + 波形顶部旗标：播放头插时刻点、选区设为章节（回车添加）、
编辑标题、⌘Z 一次撤回、旗标单击跳转；随后用「仅封装」真实导出一次，再用
`ffprobe -show_chapters` 读回容器里的章节（标题 / 起止 / 有序不重叠）。

```bash
node tools/shots/verify_chapters.mjs
# 只截导出页（看「写入章节标记 N 个」开关）
CHAPTERS_FINAL_VIEW=export node tools/shots/verify_chapters.mjs
# 沙箱 / CI：KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_chapters.mjs
```

截图落在 `kikusub-chapters/chapters-review.png` 与 `chapters-export.png`。
契约口径见 `docs/contracts/review-console.md` §3.4.9 与 `export-and-prompt.md` §3.8.2。
