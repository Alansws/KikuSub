# 核对工作台与内核设计原则

> 从 `AGENTS.md` 拆出（2026-11-13）。这是**核对台 / 内核边界 / 历史 / 主题 / 查找替换 / TTS / 选区**这一域的契约正文，改动前必读；总索引与红线见 [AGENTS.md](../../AGENTS.md)。

> 里面每条规则都带着「为什么」和日期——**不要删理由**，那正是它当初被写下来的原因。

---

### 3. 核对工作台与内核设计原则

> 旧 Gradio 界面（`app.py` / `static/`）已从仓库移除，源码归档在 Git 标签 `v0.9-gradio` 与本地独立目录 `~/Downloads/kikusub_gardio`。本章只保留当前桌面端 + 共用内核仍然有效的约束；桌面端核对台从 §3.4 开始。

- **断句改动必须有数字（2026-11）**：改 `qwen_ctc._break_costs` / `partition_cues` / VAD 参数前后，必须用 `python tools/eval/score_srt.py --reference ... --hypothesis ... --from ... --to ...` 跑同一区间，同时看 CER、`particle_start_cues`、`aux_start_cues`、最长条与 >4.3s 条数。禁止只凭个别样例“看起来更好”就改词边界；减少劈词与块均准确率之间存在已知取舍。
- **并发与取消（2026-11 加固）**：转写/局部转写必须通过 `jobs.JobRegistry` 单槽占用，**禁止**再引入模块级 `CANCEL_EVENT`。取消令牌必须归属于发起任务的会话；别的窗口点「打断」只能收到“本会话没有任务”的提示，绝不能误伤正在跑的任务。客户端断开只发取消信号，槽位由真正停止工作的 worker 在 `finally` 中释放，避免“界面已返回、模型还在跑”时被新任务覆盖。所有 `subprocess` 外部命令必须走 `procutil.run_command`（超时/取消/terminate），代理成片先写 `*.part.mp4` 再原子 rename。
- **`app.job` 不是「正在跑」的判据（2026-11-14 修复）**：任务结束后 `app.job` 会保留最后一份快照（状态栏、工具栏要读时长与百分比），所以 `!!app.job` 永远为真。要判断「有任务在跑」一律用 `lib/jobState.ts` 的 `jobBusy()`（`running` / `queued` / `cancelling`）；2026-11-14 就是因为它，「另一引擎复核」按钮在第一次转写之后永久变灰。
- **覆盖审计（2026-11 新增）**：主 VAD 的漏检（VAD 没切到、Whisper 根本没收到）不会产生 `missed` 记录，所以 `core/coverage.py` 必须保持一条**只读旁路**：按字幕切空白间隙 → 20ms/40ms RMS 包络 → 每个间隙取最长候选 → 局部峰值归一化后跑一次 Silero 只取概率 → `last_coverage_spans` 交给 `build_audit_items(coverage_spans=...)`。它**不回写**字幕、不改主 VAD 参数、不改 `load_wav_mono` 的电平；`find_coverage_spans()` 失败必须吞掉，不能影响转写。质检对用户只暴露两个组：`coverage` → `miss`（漏检，默认置顶），`missed/dropped/suspect/nonverbal` → `low`（低置信/待核，默认折叠）；`_audit_coverage()` 仍然只表达引擎能力，不要把 `coverage` 塞进去。默认参数（8s 空白 / 1.5s 候选 / 65 分位 / 局部 VAD 均值 0.20）是在 2026-11-10 的 14 分钟样本上调的；改阈值前先用同一段音频跑 `find_coverage_spans()` 看召回与条数。
- **补录区间必须夹在空白边界内（2026-11 修复）**：`QaPanel.fill()` / `ReviewView` 的 `padEnd:0.3` 会把覆盖项尾部的下一句开头也切进来；`transcribeRange()` 现在接受 `clampStart/clampEnd`，调用方必须传 `item.gap_start/gap_end`。`server/jobs.py` 的 `replace_range` 也不能再按「cue.start < 区间尾就删」处理：只删除重叠 ≥50% 或中点落入区间的 cue，边缘被切到 0.2s 的邻句必须保留。回归用例在 `tests/test_server_jobs_range.py`。

#### 3.4 桌面版核对台（`desktop/renderer/src/views/ReviewView.svelte`）

- **单击 vs 框选**：`pointerdown` 先进入 `pending`，移动超过 `CLICK_SLOP=4px` 才升级为
  `select`。禁止恢复「按下即建选区」：全局视图下 1px 就是好几秒，用户报障过“单击跳转被
  识别成框选”。
- **⌘ 多选与 ⇧ 连选**（2026-11-15 新增）：表格行与底部字幕轨道块共用同一套选择：
  - `⌘ 单击`：切换该块（`stepSelection` 以「当前句」为基准，再点一次取消）；
  - `⇧ 单击`：从**锚点行**到这一行整段连选（含两端），锚点是最近一次普通单击 / ⌘ 单击的
    那一行，连选后不移动（与 Finder 一致，连续 ⇧ 只调终点）。连选同时把时间选区设成
    「首块起点 → 末块终点」，让用户直接在波形上拖两侧手柄微调，再同步到转写页。
    `rangeAnchor` 不用 `play.selected`：后者会跟着播放头走，锚点会被播放悄悄改掉。
  - ⇧ 连选**不 seek**。视窗只在「选区比当前视窗宽」时缩到刚好装下（左右各留 6%），
    因为默认视窗是全片、4 分钟选区在全片视图里只有几像素宽，两端根本拖不住；选区已经
    装得下就完全不动缩放。**禁止**借着这条规则做「选中即放大」或叠加 69× 聚焦。
    拖动选区手柄时，若当前是多选状态，块高亮按新的时间选区重算（`keysInRange`），
    避免工具条上的块数与波形对不上。
  - 表格行 `mousedown` 在 ⇧ 时 `preventDefault`，否则跨行连选会顺带选中一片文字。
- **擦洗区**：顶部 `RULER_H=17px` 和播放头两侧 `PLAYHEAD_GRAB=8px` 是专属 scrub；
  `beginScrub / setScrub / endScrub` 负责暂停、16ms 节流写 `video.currentTime`、松手
  恢复原播放状态。视频进度条复用同一套（禁止再写独立的 click-to-seek），三者共同保证
  拖动时能逐帧预览。
- **底部字幕轨道**：`LANE_H=17px`，`selection.cueBlockAtX()` 按 `(start, end)` 把同区间的双语/
  三语行聚合成一块。拖块体整体平移、拖两端单独改起止；提交走 `applyCueTimes()`
  （整表替换，服务端只压一次历史，⌘Z 一次能退回整块）。
- **同步**：`cueIndex` 变化时（点波形、拖播放头、播放中）表格 `revealRow()` 且
  `play.selected` 跟到该块；用户点的行若已在当前块内则保留其选择，不能被“块内第一条”
  规则抢回去。
- **核对期保存**：右侧检查器底部常驻 `save-dock`。`暂存进度` 调
  `POST /api/cues/draft`，只写运行数据目录的 `{stem}.autosave_draft.srt`（与旧 Gradio
  同名共用），不覆盖导出交付文件；编辑成功后由 `scheduleDraftSave()` 0.9s 防抖自动写一次。
  `导出` 调 `POST /api/cues/export` 写 `settings.json` 的 `export_dir`。两者语义不同：
  草稿是防丢备份，导出是交付文件；即使没有任务报告（重开应用后手动导入字幕）也必须能导出。
- **核对表来源与报告解耦（2026-11 修复）**：`Session.review_source`（`transcription` /
  `import` / `draft`）随字幕快照一起返回，并参与历史回滚；导入字幕或恢复草稿后，
  右侧检查器不得再展示上一次转写的质检速览 / 生效参数 / 输出，`GET /api/qa` 返回
  `detached: true` 的空态且 `POST /api/qa/action` 返回 409——旧 item 与当前字幕已经
  对不上，继续操作会删错句、补错区间。整片/追加转写会重写来源；单句/选区重转保留来源，
  因为它不重写质检队列。
- **跟随**：状态持久化在 `localStorage['kikusub.follow']`；**只有按钮能改它**，缩放/平移、
  点击字幕、表格、画面、质检定位一律不得改——这曾经被报成「缩放时间线/点一下字幕
  跟随就被取消」。暂停时跳转依靠 `revealPlayhead()` 平移视窗让播放头保持可见，
  不应依赖“先敲空格开始播放”。
- 字幕轨道配色走 `app.css` 的 `--cue-lane / --cue-wash / --cue-block / --cue-block-hover /
  --cue-block-active / --cue-edge`，亮暗两套；禁止退回 `--separator` 那种 5% 灰。
- **主题是「令牌 + 注册表」，不是组件分支**：外观 id 只有 `light` / `dark`（青空，浅 + 深）
  与 `mincho`（明朝墨，单色），落在 `<html data-theme>` 上；名字、所属主题与 scheme 的映射在
  `renderer/src/lib/themes.ts`，切换入口是设置页「主题 / 明暗」。持久化走
  `localStorage['kikusub.theme']`，另用 `kikusub.mode` 记住青空上次的明暗（切回青空时恢复）。
  **加主题 = `app.css` 写一块 `html[data-theme='<id>']` 覆盖 + 注册表加一条**，组件里不要再写
  `data-theme` 判断。字幕字体是 `--font-cue`（只有主题换它：明朝墨用明朝，译文轨仍走
  `--font-sans`），主操作实心色是 `--btn-primary-bg`、开关/勾选/滑杆的「开」色是
  `--control-on`，两者当前都等于 accent（**主题色统一**：按钮、滑杆、开关都跟着主题走，
  不要再给某套主题单独换成墨色——产品上已经否过一次）。
- **侧栏（红绿灯列）必须跟着应用主题走**：窗口是 `hiddenInset + vibrancy:'sidebar'`，
  原生毛玻璃的明暗由系统外观决定，不受 `<html data-theme>` 控制。渲染层切主题时要
  通过 preload 的 `setTheme()` 通知主进程 `nativeTheme.themeSource`；主进程只认 scheme
  （`dark` → dark，其余 → light），同时把外观 id 写进 `preferences.json` 供冷启动首帧使用。
  侧栏 `--bg-sidebar` 必须足够不透明（深色当前 `rgba(10,12,16,.92)`），否则浅色系统下会透成灰白。
  `main.ts` 在挂载前先应用 localStorage 里的主题，避免冷启动闪一下浅色。
- 修改后必须 `cd desktop && npm run build`，并至少实际验证：单击跳转、抖动单击不建选区、
  刻度/播放头/进度条拖动、字幕块整体与两端拖动、⌘Z 一次回退整块、播放头同步表格与检查器。

#### 3.4.1 导出目录与转写自动保存（2026-11 新增）

- 字幕交付文件的唯一目标是 `settings.json` 的 `export_dir`；空值才回退到
  `OUTPUT_DIR`（打包后 `~/Library/Application Support/KikuSub/outputs`）。
  新增写字幕的路径必须走 `core.settings.resolve_export_dir()`，不要在
  `core/pipeline.py` 或路由里硬编码 `OUTPUT_DIR`（会绕过设置页）。
- 转写页的整片与区间任务都经 `server/jobs.py` 调 `core.pipeline.run_transcription`，
  完成即落盘；`TranscribeRequest.export_dir` 是服务层把设置传下去的唯一通道。
  漏句清单 / 质检 JSON / 代理缓存仍属于运行数据，留在 `output_dir`。
- **原始转写产物统一带引擎文件名标签（2026-11-15）**：
  `{stem}{slice}.{file_tag}{ext}`，标签只在 `core/engines.py` 的 `file_tag` 登记
  （`AnimeWhisper` / `Qwen3-ASR` / `SenseVoice-Small` / `FireRedASR2-AED`），
  `core.pipeline.output_suffix()` 只读注册表。Whisper 不再特殊到「无后缀」——那正是
  它和交付稿撞名的根源。
- **核对后的交付文件命名（2026-11-15）**：
  `{stem}.{version}.reviewed{track_suffix}{ext}`，由 `core/export_naming.py` 唯一实现。
  `version` 优先取 `Session.review_source.engine`，导入稿从文件名推断引擎（新旧标签都认：
  `.AnimeWhisper` / `.whisper`、`.Qwen3-ASR` / `.qwen`），识别不出才用 `import` / `draft`。
  推断前必须先剥掉媒体 `{stem}`，并且只认点分标签，避免影片名自带 `whisper` 等关键字时误判。
  同名且内容相同 → 原地重写；同名但内容不同 → `next_available_path()` 另存 ` (2)`、` (3)`，
  **禁止静默覆盖另一份内容**，写入一律走 `write_text_atomic()`。禁止再回到
  `{stem}{suffix}{ext}` 这种没有版本身份的裸名。
- 桌面端的导入页、转写页与核对台都有「导入字幕…」，原生对话框的 `defaultPath` 就是导出目录；
  新增入口时继续走 `window.kikusub.pickSubtitle()`，不要让用户自己逐层找路径。
- **最近打开封面**走 `core/thumbnails.py` + `GET /api/media/thumb?path=…`：先取真正的首帧，
  用 Pillow 判断是否纯黑/接近黑场；是黑场才用 FFmpeg `thumbnail` 在前 60 秒里挑代表帧。
  结果按「路径 + mtime + 大小」缓存在 `{output_dir}/thumbnails/`，并限制 2 个并发 ffmpeg。
  不要为了封面解码整部片，也不要在前端用 canvas 抓首帧（MKV/HEVC 会黑屏）。

#### 3.4.2 历史、TTS、查找替换与手动补字幕（2026-11 新增）

- **50 步统一工作区历史（2026-11 重构，替换旧的「字幕 + 导出设置」双时间线）**：
  `Session.history` 是「起始状态 + 每一步操作后的完整 **WorkspaceState**」的时间线，
  `history_cursor` 指向当前状态。**不要再按域拆历史，也不要用双栈**：
  - 一份快照包含 `cues / translations / review_source / qa_payload / export_ui / ai_draft`。
    字幕、译文、质检状态、导出设置、AI diff 草稿都在同一条时间线上，⌘Z 永远退回最近一步。
  - 上限 **50 步操作**（`HISTORY_LIMIT`，另加一条起始状态）。超出后从最旧的操作开始丢。
  - 所有编辑都必须带操作说明：`replace_review(..., label=...)`、`update_cue(..., label=...)`、
    `set_translation(..., label=...)`、`session.record(label)`；缺 label 的历史条目不可接受。
  - `_record(label, coalesce=...)` 支持 1.2 秒窗口合并：同一根滑杆、同一行 AI 建议的连续
    调整只算一步。`POST /api/cues/history/jump` 只移动 cursor、不产生新历史。
  - `undo/redo/jump` 调 `_apply_state()` 一次性恢复全部域；若 `qa_payload` 变化，必须同时
    把 `.qa.json` 写回磁盘，否则面板状态会跟字幕对不上。
  - **导出设置与 AI diff 草稿是渲染层状态**：通过 `POST /api/history/checkpoint`
    （`{label, export_ui, ai_draft, coalesce, record}`）并进服务端快照。导出面板严禁直接写
    `exporter.size = ...`；一律走 `setExportMode / setExportTrack / setExportResolution /
    setExportQuality / setExportSrt / setExportOutDir / updateExportStyle /
    applyExportStylePreset / resetExportStyle`，否则不会进历史。切 AI 上下文用
    `record=false` 同步、不产生步骤。
  - 换片时 `reset_for_media()` 清空这些状态；`openMedia` 用 `syncClientState(false)` 把新片
    的默认导出设置写进基线，但不要记成一次编辑。
  - 工具栏历史面板只有**一组**条目（不再分「字幕编辑 / 导出设置」）；`undo_at/redo_at`
    仍随快照返回，但只用于显示，**禁止**再拿它做“谁更近”的分域判断。
  - 文本框内保留原生逐字撤销；提交（失焦 / ⌘↩）后由 `updateCue` 记一步。⌘Z 在滑杆 /
    复选框聚焦时也要生效（`App.svelte` 的 `onKey` 对滑杆放行）。
- **聚焦倍率固定 69×**：`ReviewView` 的 `FOCUS_ZOOM=69`，工具栏「聚焦」、选区「聚焦」、
  右栏「聚焦」、质检定位全部走 `duration/69`。**禁止**再使用「当前 viewSpan / 6」这类
  会随已有缩放叠加的公式（用户报过 145× 再点一次变 415×）。
- **转写选区完成后必须定位到新句**：服务端 `first_cue_in_range()` 返回 `target_index`
  （合并后第一条与区间重叠的字幕），前端 `onJobDone` 用 `jumpToCue()` 选中并强制滚动。
  `play.selectNonce` 用于绕开 `lastRevealed` 去重；只改 `play.selected` 会遇到
  「新句下标没变 → 表格不滚」的旧 bug。**转写选区不得改视窗缩放**：不要再在这里调
  `focusRange()`（它会把波形放大，用户明确要求保持当前聚焦状态）。
- **⌘F 查找与替换（覆盖原文 / 译文 / 双语）**：`findState` 在 store 里；`ReviewView`
  按当前显示模式决定搜索轨——原文只搜原文、译文只搜译文、双语两条都搜。命中必须带
  `track`（source / target），高亮与替换才能改对表。「全部替换」走
  `replaceAllInTracks()` → `POST /api/cues/replace-all`：客户端算好原文与译文两份完整
  数组，服务端只压**一步**历史，双语模式下 ⌘Z 一次就能退干净。单条替换仍分别走
  `replaceInCue()` / `replaceInTranslation()`。替换文本必须用函数替换
  （`() => replacement`），不能把 `$&` / `$1` 当正则替换模式。菜单 `查找与替换…` 与
  渲染层快捷键都要能打开；输入框聚焦时也要生效。
  **逐处决策（2026-11）**：单处替换成功后必须 `jumpToCue(next)`，让表格选中列、滚动与
  底部字幕轨道跟到下一处——只改文本会让“替换在往后走、高亮却不跟”。查找栏里的「跳过」
  只把当前命中记进本轮的 `findSkipped` 锚点（cue / track / start），不写字幕、不进历史；
  改查找词、切显示模式或关掉查找栏即清空。同一句里更靠前的命中被替换/删除时，必须调
  `shiftFindAnchors()` 平移后面跳过的起点，否则被跳过的逗号会“复活”。上一处 / 下一处 /
  替换 / 跳过都只走**未跳过**的命中；当前这一处用 accent 单独点亮，跳过的命中加删除线。
  「全部替换」也要尊重跳过：把 `skippedFindKeys` 传给 `replaceAllInTracks(..., skip)`，
  只替换未跳过的命中（按钮文案此时是「替换剩余」），同轨整批替换后用
  `reseatSkippedAfterReplaceAll()` 平移剩余锚点；双语下仍只压一步历史。
  快捷键 `review.findPrev` / `review.findNext` 的 `scope` 是 `'find'`，只在查找栏打开时
  参与匹配（默认 ⌘G / ⇧⌘G），避免用户改键后把方向键从正文编辑里抢走。
- **右键手动补字幕**：音轨 `contextmenu` → 「添加字幕」→ `insertCueAt(t)` 在光标处居中插入
  **0.8 秒空字幕**（贴片尾时自动前移），随后 `play.editNonce` 让右侧检查器文本框拿到焦点。
  这是给气声 / 模型识别为空 / 只想手打「啊」的场景用的，不要试图自动跑识别。
  **右键菜单与新建音色浮层必须用 `portal` 挂到 `body`**：`.view-enter.animated` 的切页动画
  `fill-mode: both` 会让计算后的 transform 变成 identity matrix，从而成为 `position: fixed`
  的包含块；留在里面会把菜单整体推偏「侧栏 + 工具栏」的距离（用户报过「离鼠标太远」）。
- **复制 / 粘贴字幕（2026-11-17 新增）**：给气声 / 极轻的「吸って」「入って」这类
  局部转写常常空结果的句子用——只要有一处转对了，就把它原样搬到第二处、第三处。
  - **剪贴板内容**：原文 + 原时长 + 各语种译文（`{lang: {text, base}}`）。`base` 必须
    原样带走，原来过期的译文在新句上仍然显示过期，不能被粘贴伪装成已同步。
  - **粘贴规则**：`start = 播放头`，`end = start + 原时长`；只有片尾不够长才缩短
    （`planCuePaste()`，纯函数在 `lib/cueClip.ts`）。与邻句重叠**允许**，只 toast 提示
    条数与最大重叠秒数，绝不自动改邻句时间轴。插入下标按 `start` 排序，与
    `insertCueAt()` 同口径。
  - **只写当前会话已有的译文轨**：剪贴板跨片保留，粘贴时前端按
    `app.translations` 过滤、服务端 `Session.insert_cue(translations=...)` 再按
    `self.translations` 过滤一次；目标片没有的 lang 静默忽略，不报错、不新建残缺轨。
  - **一步历史**：一次 `POST /api/cues/{index}/insert`，label 为
    `粘贴字幕到 mm:ss.mmm`；原文与译文在同一份 `WorkspaceState` 快照里，⌘Z 一次退干净。
    粘贴后只把 `play.selected` 切到新句并 `selectNonce += 1` 强制滚动；**不 seek、
    不改缩放、不抢文本框焦点**（抢焦点会让下一次 ⌘⇧V 被输入框让位规则挡掉）。
  - **快捷键**：默认 `⌘⇧C / ⌘⇧V`（`review.copyCue` / `review.pasteCue`，可在 ⌘K 改）。
    不用 ⌘C / ⌘V：主进程编辑菜单的 `role:'copy'/'paste'` 会先接走这两个键；文本框内
    仍保持原生复制粘贴。主进程菜单里没有 `⌘⇧C / ⌘⇧V` 的 accelerator，
    `role:'toggleDevTools'` 的默认是 `⌥⌘I`，所以应用窗口里不会被 DevTools 抢走；
    只有 DevTools 窗口自身获得焦点时，`⌘⇧C` 才归它的 Inspect Element。
    两条动作都不设 `allowInTyping`，输入框聚焦时与现有核对台快捷键一样让位。
  - **先提交草稿**：检查器通过 `lib/cueDraftCommit.ts` 注册自己的 `commit()`；
    快捷键与检查器按钮都先 `await flushCueDraft()`，避免复制到还没提交的旧文本。
  - **不碰两个大文件**：状态在 `lib/cueClipboard.svelte.ts`，UI 在 `Inspector.svelte`，
    `store.svelte.ts` / `ReviewView.svelte` 不新增导出行；预算测试保持绿色。
  - 回归：`desktop/test/cueClip.test.mjs`（纯函数）、`tests/test_server_cue_paste.py`
    （一步历史 / 缺轨忽略 / base 保留）、`tools/shots/verify_cue_clipboard.mjs`
    （无窗口真实界面）。
- **切割 / 合并 / 多选删除（2026-11 新增）**：
  - 有字幕区域右键新增「切割字幕」：`POST /api/cues/{index}/split` 在光标时间把一句切成两段，
    **两段都保留完整原文**（用户明确要求：自动判断断点内容不可靠，先保留原句再分别删减）。
    切割点距两端至少 0.05 秒；译文轨在同一位置复制一条，双语不会错位。
  - 框选两条以上字幕后右键「合并这 N 句字幕」：`POST /api/cues/merge` 取首尾时间、文本按顺序
    直接相连（西文单词间补空格），译文轨同样拼接。只允许下标连续的多条。
  - 底部字幕轨道支持 ⌘ 单击多选（再点取消）与 ⇧ 连选，`POST /api/cues/delete` 批量删除只
    压一次历史；多选块在画布上用 accent 描边。删除必须同步删掉译文轨同下标条目。
  - **选区工具条只有一根**（`SelectionBar`，2026-11-15 统一）：块多选与时间选区可以同时
    存在（⇧ 连选就是两者同时成立），所以不能再按「有块多选就藏掉时间选区」二选一——
    那会把 ⇧ 连选后的「转写选区 / 同步到转写页」一起藏掉。工具条先报块数、再报时间范围，
    删除与转写按钮按各自条件出现；关闭按钮一次清掉两种选择。
  - 「填入转写」已更名为**「同步到转写页」**：它做的是把当前起止时间（含波形上微调后的
    结果）写进转写页的两个输入框并切页，不是提交任务；「转写选区」才是在核对台原地局部
    转写。两个名字不许再混用。
  - **`app.slice` 是一次性消息，必须消费**（2026-11-15 修复）：转写页用
    `lib/transcribeSlice.takeSlice()` 读走并置空。`App.svelte` 的 `{#key app.view}` 会
    重建整个视图，写在组件里的 nonce 守卫会跟着归零；只靠它，整片转完自动跳核对台、
    再回转写页时旧区间会复活，输入框显示区间而实际提交的是整片。**禁止**把守卫改回
    组件内变量。
  - **「全片」= 清空时间区间与 `app.slice`**，不再把 `0–片尾` 填进两个输入框：整片任务
    不该带 `_00m00s-…s` 的区间后缀，输入框也不该出现「有时间但按整片跑」的歧义。
  - 进度卡展示的范围只读 `app.jobMeta`（提交时锁定的 scope/label），不跟随输入框；
    Qwen 的逐字对齐说明也只在这里出现，非 CTC 引擎不得显示 `0/0` 汇总。
  - **转写页「结果处理」的三档语义（2026-11-15 重做）**：档位由 `lib/applyMode.ts` 唯一
    决定，**没有「自动」这一档**（旧版前端按"有没有填区间"自己猜成追加或覆盖，用户既看
    不到也猜不到）。整片只有 `覆盖整片 / 追加`；区间多一档 `替换选区`（默认），对应
    `apply=replace_range`——只删区间内旧字幕、写入本次结果、区间外一条不动，和「转写选区」
    同一条服务端路径（`server/jobs.py: merge_replace_range`）。同步区间到转写页时默认选中
    它。区间任务里选「覆盖整片」等于清空整表，必须有**警示色 + 二次确认**；「替换选区」
    强制 `keep_absolute_timeline=true`（相对时间轴会让新区间字幕从 0 秒起编号，旧句被删、
    新句插到片头）。转写页发起的区间任务（`jobMeta.origin='transcribe'`）完成后跳核对台并
    选中 `target_index`；核对台的原地修正（`origin='review'`）停在原处不跳页。
  - 服务端的插入 / 删除 / 切割 / 合并都要经 `Session` 的结构性方法调整 `translations`，
    **禁止**只改 `review_cues` 让译文轨自己错位。`HistoryState` 现在连译文轨一起快照，
    ⌘Z 才能把字幕与译文成对恢复。
- **可自定义快捷键（2026-11 修订）**：`desktop/renderer/src/lib/shortcuts.svelte.ts` 是唯一映射，
  ⌘K 打开面板录制新组合（该快捷键本身也可改）。默认值：Enter 删除当前字幕（底部多选时一起删）、
  Space 播放 / 暂停、↑↓ 上下句、⌘F 查找、⌘↩ 添加空字幕、**⌘G / ⇧⌘G 查找下一处 / 上一处**
  （`scope: 'find'`，只在查找栏打开时生效，见 §3.4.2）；专业剪辑键（2026-11-17）：
  **← / → 逐帧、⌘← / ⌘→ 逐秒、Q / E 入点 / 出点、W 切割、⇧Space 试听、N 磁吸、
  ⇧Z 全片 / 还原、1 / 2 / 3 倍速（⇧2 归 1×）**，详见 §3.4.6；视图键按工作流固定为
  **⌘1 导入 / ⌘2 转写 / ⌘3 核对台 / ⌘4 双引擎复核 / ⌘5 润色 / ⌘6 断句重排 / ⌘7 翻译 / ⌘8 导出**。
  润色与翻译是独立页面，不再共用页签；提示词库与任务详报不占键；设置页走系统惯例 ⌘,
  （侧栏「设置」右侧显示提示），它和 ⌘Z/⇧⌘Z、⌘O、⌘E、⌘Q 等一起列在面板「固定快捷键」组，
  录制时会被判为冲突并拒绝。
  **菜单里不再给播放 / 上下句 / 视图 / 查找绑固定 accelerator**：否则用户改键后旧键仍然生效。
  视图切换仍在菜单里可点，但按键走渲染层。视图菜单与侧栏顺序一致（含双引擎复核 / 润色 / 翻译）；
  核对入口统一叫「核对台」。
  输入框内只有 allowInTyping 的动作（视图切换 / 查找 / 打开面板）生效。
- **本机 TTS（2026-11 升级：系统 say → 本地零样本克隆）**：
  - 引擎分两层，都在 `core/tts/`：`mac_say.py`（零显存兜底，`say -v ?` 的日语列表）与
    `clone_engine.py`（OmniVoice，Apache-2.0，0.6B，官方建议 3–10 秒参考音频）。
    **不要**把 VoiceStudio 的 AGPL 代码搬进来；只借鉴「参考音频克隆 + 音色管理」的产品逻辑。
  - `voice_id` 是唯一命名空间：`system:Kyoko` / `clone:<8位id>`；空串由服务端选默认
    （服务端默认仍是系统语音；**用户可在设置「TTS 对照」里把默认偏好切到克隆音色**，
    存 `kikusub.ttsDefaultKind` / `kikusub.ttsDefaultVoiceId`，没有可用克隆音色时回退系统语音）。
    只有非 macOS 拿不到 `say` 时才回退到已有克隆音色。旧接口 `POST /api/tts`
    （`voice` + `rate`）保留兼容，内部换算成 `voice_id` + `speed`。
  - 音色落在 `{output_dir}/voices/<id>/`：`ref.wav`（24k/单声道/PCM16，已去首尾静音、
    参考响度归一到 −20 LUFS / −2 dBTP、≤10s）、
    `meta.json`（名称/参考文本/时长/来源）、`prompt.pt`（OmniVoice 声线 embedding 缓存，
    损坏或模型升级后自动重建）。**目录名用 id，不用音色名**：用户会重命名、用中文/空格。
  - 接口：`GET /api/tts/voices`（system + custom + engine/download 状态）、
    `POST /api/tts/synthesize`、`POST /api/tts /voices/extract-from-media`（用 ffmpeg 从
    当前视频精准切片 → 建音色）、`/api/tts/voices/upload`、`PATCH|DELETE /api/tts/voices/{id}`、
    `PUT .../ref-text`、`POST /api/tts/model/download`、`GET /api/tts/model/verify`
    （只读校验权重，0 字节文件也算缺失；设置页「校验 / 补齐」先走它，完整时不再弹下载确认）。
  - 缓存键 =「引擎 + voice_id + 参考音频指纹(mtime/size) + ref_text + 文本 + 速度 +
    响度版本（`lufs-v1:-18`）」，命中直接返回文件名；`{output_dir}/tts_cache`
    只留最近 240 个。音频流仍是 `/media/tts/{file}?token=`（`<audio>` 发不了
    Authorization 头）。
  - **响度统一**（2026-11 用户报障：克隆朗读比系统语音/视频小声一截）。OmniVoice
    的输出幅度会跟着参考音频走（参考 −27～−40 LUFS 时输出也落在这个区间），
    和 `say`（≈ −25 LUFS）没有共同基准。因此两处收口：建音色时参考音频经两遍
    ffmpeg `loudnorm` 归一到 −20 LUFS；每次合成都先在临时文件上归一到
    −18 LUFS / −1.5 dBTP，再原子替换进缓存。归一化只是增强项：没有 ffmpeg、
    极短或全静音片段都只记日志并保留原文件，不能让朗读 500。
  - 资源：克隆模型**首次真正合成才加载**；空闲 `KIKUSUB_TTS_IDLE_SECONDS`（默认 300s）
    自动卸载；`JobManager` 的 `on_heavy_job` 在 transcribe / proxy / export 开跑前调
    `TTSManager.release()`。`KIKUSUB_TTS_DEVICE=cpu|mps` 可强制设备，
    `KIKUSUB_TTS_MODEL_DIR` 可改权重目录（默认 `models/omnivoice`）。
  - 下载走 `core/tts/model_store.py` 的独立后台线程（不占 `JobManager` 单槽），
    进度由 `/api/tts/voices` 的 `engine.download` 带出；模型约 3.3GB，**不随包分发**。
  - 前端：`store.tts` 的 `voiceId`/`speed` 落 `localStorage['kikusub.ttsVoiceId']` /
    `['kikusub.ttsSpeed']`（旧 `ttsVoice`/`ttsRate` 自动迁移）。右侧检查器把 TTS 面板
    收成「播放卡片 + 操作 chip」：卡片里是带「朗读 / 停止 / 生成中」文字的实心主按钮、
    音色/语速下拉和当前声线的参考信息（时长、来源、「音量已对齐」）；卡片下是
    **上传 / 截取 / 音色库（带数量）/ 管理** 四个 chip，模型未就绪时另有一条实心
    下载 CTA。音色库用图标动作（试听 / 设为默认 / 管理）而不是一行文字链接。
    参考音频约束（3–10 秒、单人干声）放在上传/截取入口的 title 与各自面板提示里，
    不再常驻一条灰字。字幕表与波形右键「以此句音频新建音色…」仍走
    `extractTtsVoiceFromCue()`。
    换句/换片仍必须 `stopTts()`；不做云端 TTS，不读 AI Key。
  - **降级是硬要求**：没装 `omnivoice`、没下模型、MPS 失败（回退 CPU）都必须只让克隆
    引擎不可用，系统语音与界面不能卡死；合成失败返回可读的 502/503，前端弹 toast。


#### 3.4.3 质检面板：停靠页签 + 可选浮窗（2026-11 重构）

- **默认不再浮在画面上**：`Inspector.svelte` 顶部有「当前条目 / 质检待核」两个页签，
  `QaPanel` 以 `mode="docked"` 填满 348px 的右栏；不再遮挡预览、底部字幕或右侧按钮。
  这是用户明确要求的「不管怎么放都挡一块」的解决方案。
- **浮窗是显式选项**：页签内点「弹出为浮窗」后 `QaPanel mode="floating"` 才用
  `position: fixed` + `left/top/width/height`；可拖标题栏、拖右下角改大小、双击标题栏或
  点「归位」恢复默认位置和大小，点「停靠」回到检查器页签。位置/尺寸存
  `localStorage['kikusub.qaPanel.v2']`。
- **拖动必须用 window 级 pointermove/pointerup**：旧实现把 move/up 挂在标题栏上，
  面板一旦移出指针下方就收不到后续事件（用户报过「拖 100px 只动 10px、位置不落盘」），
  而且 `bottom = startBottom + dy` 的垂直方向是反的。新实现只记录起点，在 window 上算
  位移并 clamp 到可视区；禁止改回标题栏级 capture。
- `qa.floating` 持久化；`setView` 离开核对屏时关闭停靠面板（浮窗例外）。
  `StatusBar` 的「质检」按钮对两种模式都走 `toggleQaPanel()`；从其他页面打开会先切回核对屏。
- 质检动作（mark / skip / delete_cue / restore）现在也进统一历史；`focus` 不记。
  `_apply_state` 恢复 `qa_payload` 时必须写回媒体同名 `.qa.json`。
- **纯发声待核（P0，2026-11-20）**：整条只有喘息/笑声/拟声、已被字幕剔除的段，
  以前只计数 `nonverbal_skips` 就静默消失；现在由 `core.audit` 生成 `nonverbal`
  kind（group `low`，最多 20 条），`QaPanel` 提供「保留 / 确认删除」。保留走
  `qa.apply_action` 的 `mark kept`，由 `_audit_ensure_item_cues` 把原文按原时间
  幂等插回，一步 ⌘Z 可退；确认删除只标状态，不动字幕。开关是
  `whisper.nonverbal_qa`（默认 true）/ `qwen.nonverbal_qa`（默认 false：
  Qwen 对呼吸声敏感，长片容易一次多出二十条，需要时在参数面板打开）。
  **它只影响队列可见性，不改变字幕文本或 CER**。
- **句首静音拉回（P0，2026-11-20）**：`whisper.enable_start_repair`（默认 true）
  在 Anime Whisper 逐段循环里，保留 end，只按「10ms RMS + 全片底噪」把段首静音
  向右收。四道闸门：`head_removed`（已被笑声边界挪过）、`is_nonverbal_only`、
  「…」开头且只有单/双假名（长叹词保护；三字以上仍按音频证据拉回）、
  单/双假名（阈值 0.8s / 最多 40% / 保底 0.8s）。
  CTC 对齐路径不做（对齐层自己给逐字时间）。统计写入
  `segment_stats["start_repair"]`，报告有「句首静音拉回」一行；关闭后时间轴与
  旧版逐字节一致，供 A/B。


#### 3.4.4 批量清理标点（2026-11-15 新增，2026-11-17 改口径）

转写模型爱在句尾补 `、` `。` `…`，有时补在句中；一行字幕末尾的顿号只会让画面显脏。
这是**整轨一次性的文本整理**，不是 AI 提案，做完必须能一步撤回。

> 2026-11-17 用户报障：句中 `、` 被换成空格（换全角空格时看着跟没清一样）、行尾 `…`
> 默认不动，这两类「点了没效果」。改口径为**句中直接删掉、行尾省略号默认清**，并把
> 半角 `｡` `､` 纳入识别。旧的两个选项没删，降级成面板里的可选口径。

- **只清原文轨，永不碰译文轨**。中文译文套这条规则会变成「今 天 的 雨」，是破坏而不是
  整理。应用到译文轨的入口一律不做，也不加「顺便清译文」的复选框。
- **规则是纯函数**：`desktop/renderer/src/lib/punctuation.ts`（零 import，`node --test`
  能直接加载），单测 `desktop/test/punctuation.test.mjs`（21 条）。改动规则先改那些用例。
  - 行首 / 行尾：删掉 `、，。．｡､,.` 与残留空白；**行尾省略号默认也算行尾脏字符**
    （含 `「吸って…」` 这种后面只剩收尾括号的、以及 `吸って…。` 后面只剩要删句号的）；
  - **句中标记默认直接删掉、不补空格**（日语字幕不靠空格断句）：`吐いて、もう一回` →
    `吐いてもう一回`，标记两侧紧贴的空白一起吃（`吐いて、 もう一回` 不留孤零零的空格）；
  - **例外：紧邻英文 / 数字时补 1 个半角空格**，否则会粘词（`Thank you、またね` →
    `Thank you またね`、`100、200` → `100 200`）；
  - 旧口径仍在，降级为可选：句中换 1 个半角 / 全角空格（`mid: 'half' | 'full'`）；
  - 省略号口径 `ellipsis`：`trailing`（默认，只清行尾）/ `all`（连句中的一起清）/
    `keep`（全留）；句中的 `…`（`あの…そう`）是语气，默认保留；删 `、` `。` 紧贴的占位
    省略号时直接删标记（`そうか、…` → `そうか`）；
  - 数字与英文上下文里的 `.` `,` 不动（`3.14` / `1,000` / `No.1` / `v2.0` / `A.I.`）；行尾的点仍按句末删；
  - 收尾括号 `」』）】》` 前的标点直接删、不补空格；
  - 空白**只合并、不换宽度**：`Thank you` 的半角空格不会被压成全角，全角空格也不会被压回半角；
  - 多行字幕逐行处理并保留 `\n`；清完是空的就回退原文（绝不产出空字幕）。
  - 面板「原文」行的标红由 `markedSpans()` 算（同一份规则），组件不许再写一份正则，
    否则预览会和实际结果对不上；受保护的小数点、句中的省略号都不标。
- **偏好存 `localStorage['kikusub.punctClean.v2']`**（`{mid, ellipsis}`）。v1 的键不读也
  不删：口径变了，读旧键会让老用户的 `space: 'half'` 把这次修复整个抵消掉。
- **一次整轨提交 = 一步历史**：走 `POST /api/cues/replace-all`（与「全部替换」同一条路），
  `label = 清理标点（N 条）`；前端 `applyCueSnapshot` + `scheduleDraftSave` + `loadCueHistory`，
  字幕表、底部字幕块、历史面板、草稿暂存同一轮刷新，⌘Z 一次退干净。条数不变，
  已有译文轨不会被丢弃（会如实标成「原文已改」的过期态）。
- **入口三个，面板一个**：核对台顶栏「清理标点」（`Toolbar.svelte`，锚点与「⋯ 更多」同款）、
  `⌘⇧L`（`review.cleanPunct`，可在 ⌘K 面板改键）、编辑菜单「清理标点…」（菜单不绑
  accelerator，键归渲染层）。**⌘K 不能占**——它是键盘快捷键面板。
- **不改 `ReviewView.svelte` 与 `store.svelte.ts`**：这两个文件有行数预算（红线 11），
  所以按钮挂在 Toolbar，状态在 `lib/punctuationPanel.svelte.ts`，UI 在
  `components/PunctCleanPanel.svelte`。要把它挪进字幕表头，得先付出预算。
- **形态是下拉浮层，不是模态确认框**：本应用里只有快捷键面板与退出确认是模态的。
  浮层给两组口径（句中「删掉 / 半角空格 / 全角空格」、省略号「行尾删 / 全部删 / 保留」）、
  「影响 N 条 / 行尾 N 处 · 句中 N 处」，以及三条 before→after；`Enter` 应用、
  `Esc` 关闭、点外部关闭；焦点在浮层里时 `Enter` 交给按钮自己处理，不能穿透到
  「回车 = 删除当前字幕」。

#### 3.4.5 另一引擎复核：可选引擎 + 逐字差异 + TTS 三方对照（2026-11-16）

> 触发：用户指出「另一引擎」原来是自动取当前引擎的反面，引擎一多就不成立；并且
> 上下两版只并排显示文字，差一两个助词时只能肉眼比对；也没法分别听两版 TTS。

- **引擎由用户选，能力只看注册表**：`core/engines.EngineSpec.reviewable` 是唯一能力位
  （当前 `whisper` / `qwen` 为 True，`sherpa` 两个中文引擎没有 `transcribe_window`）。
  `POST /api/jobs` 的 `kind=compare` 用 `spec.reviewable` 拒绝不支持的引擎，**禁止**在
  路由里再写 `{"whisper","qwen"}` 白名单（红线 #12）。新引擎只要补上
  `transcribe_window()` 并打开 `reviewable`，复核下拉与接口自动跟进。
- **候选怎么筛（前端 `lib/secondOpinion.svelte.ts`）**：`reviewable` + 不是当前稿的引擎 +
  覆盖当前稿的**主语种**（注册表 `languages[0]`，经 `sharesLanguage()` 转为「候选是否支持
  这个语种」）。只看主语种是刻意的：SenseVoice 同时会日语，但中文稿不该把日语引擎推荐成
  「同语种」——两个引擎都听不清对方在说什么。设置里停用或权重未下载的仍列出来但置灰，
  说明差什么。**当前稿的引擎优先读
  `app.reviewSource.engine`**，导入稿识别不出才退回转写页当前选择——否则用户把转写页
  切到 B 引擎后，核对台这张 A 稿的「另一引擎」会被错误地选成 A 自己。
- **选择要记住**：`localStorage['kikusub.secondOpinionEngine']`（纯界面偏好，与 TTS 音色
  同层）；用户没选过、或选的引擎失效时，退回两日语引擎互斥的默认（`otherEngineKey`）。
  结果卡片上的引擎名取 `secondOpinion.engine`（这次结果真实用的那个），不是下拉当前值；
  下拉换过引擎后「再听一遍」变成「换引擎重听」。
- **差异高亮**：`lib/textDiff.ts` 的 `charDiff()` 与 `core/dual_review.char_ops` 同口径
  （`eq` / `del` / `ins`，replace 拆成 del + ins），在两版文本里分别用红底删除线 / 绿底
  标出，并在备选卡头显示「N 处不同」/「两版一致」。单句复核接口只回文本，这里在前端算
  （两句几十个字，LCS 足够）；不要为一句 diff 再加一次服务端往返。
- **TTS 三方对照**：当前卡与备选卡各有一个「朗读」chip。当前稿复用 `speakCue()`——
  它和下方 TTS 面板读的是同一句、同一音色，两个入口的「正在播」必须同步；备选稿是
  字幕表之外的一段文字，走 `speakTextTagged(text, tag)`（同一套合成与缓存），
  `tts.tag` 标记它、`tts.index=-2` 表示不属于字幕表，避免被当成当前句。
  上方「试听」已更名为**「试听原声」**：原片声音 / 当前稿 TTS / 另一引擎稿 TTS 三份证据
  同一屏可比。更换选中句仍由 `Inspector` 的 `$effect` 调 `stopTts()`。
- **界面**：卡片抽到 `components/SecondOpinionCard.svelte`（`Inspector` 只负责挂载），
  形态与 TTS 面板一致：白卡 + 引擎点 + 文本，备选卡用 `--accent-line` 描边与
  `--accent-soft` 底；只在没有可用引擎时给一条 `--warn` 提示并把 CTA 换成
  「去设置启用复核引擎」（跳设置页），避免一个永远灰着的按钮。
- **仍不自动采用**：`adoptAlternative()` 只调 `updateCue()`（服务端一步历史，⌘Z 可退）。
- **点行 / 点块即选中该句时间（2026-11-20）**：表格行与底部字幕块**纯单击（未拖拽）**
  都会把时间选区设为该句精确 `[start, end]`；工具条随即出现，可直接「转写选区 /
  同步到转写页」。`⌘` 多选、`⇧` 连选、双击试听、框选、方向键步进不变。`Esc`
  只清时间选区，不丢当前行 / 多选集合；任务运行中仍优先取消任务。
- **单句 AI 判定（2026-11-20）**：两版不一致时，第三张卡
  `ArbitrationCard.svelte` 会出现在 A/B 下方，见
  [ai-proposal §3.7.7](ai-proposal.md#377-单句-ai-判定第三版2026-11-20)。
  它只发两版文本与前后各 3 句上下文；**不自动采用**，采用走 `updateCue()`。
  与 B 相同也保留「采用（同 B 版）」；A/B/时间/媒体变化后旧结果自动失效。
- **自动判定开关（P2-4，2026-11-20）**：设置 → AI 与技能里的
  「两版不一致时自动 AI 判定」默认关闭。开启后 B 引擎复核完成且与 A 不一致时自动
  触发一次（同一媒体 + 同一句 + 同一 B 文本只跑一次）；切换句子、编辑 A/B、卡片卸载
  或点取消都会用 `AbortController` 中断在途请求。不做提示词库第六类，也不做
  QaPanel 入口。

#### 3.4.6 核对台专业剪辑操作（2026-11-17）

> 目标是把核对台从「点一下、拖一下」补成能靠键盘逐帧精修的剪辑台。所有键都进
> `shortcuts.svelte.ts` 同一张表，可在 ⌘K 重绑；文本框 / 输入框 / 下拉 / range 滑杆 /
> contenteditable 内一律让位。

- **逐帧 / 逐秒**：`←` / `→` 后退 / 前进 1 帧，`⌘←` / `⌘→` 后退 / 前进 1 秒。
  - 帧率来自 `MediaInfo.video_fps`（`server/media.py` 的 ffprobe `avg_frame_rate` 优先、
    `r_frame_rate` 兜底）；纯音频 / 未知帧率回落 `FALLBACK_FPS=30`（33.3ms）。
  - 逐帧用帧号 `Math.round(play.time / step) ± 1`，避免连续按键累计浮点漂移；
    步进前 `video.pause()`，结果 clamp 到 `[0, duration]`，再走统一 `seekTo()`。
  - **高速连按必须以同步写回的 `play.time` 为基准**：`seekTo()` 是同步的，而
    `video.currentTime` 在异步解码完成前还是旧值；读后者会让连按原地踏步。
    `lib/transport.svelte.ts` 的注释与 `verify_review_transport.mjs` 的 10 连按断言守着这条。
  - `←/→` 与 `⌘←/⌘→` 在核对台显式 `preventDefault()`；主进程没有 history accelerator，
    但仍加导航守卫，避免任何组合把页面带离应用。输入控件内的方向键保持原生行为。
  - `allowOnControls` 只放行按钮 / 链接：用户点过播放按钮后方向键仍然生效；
    textarea / input（含 range）/ select / contenteditable 永远让位。
- **入点 / 出点**：`Q` / `E` 把当前字幕的入点 / 出点对齐播放头。
  - 纯校验在 `lib/cueEdit.ts`：入点必须 `< end - 0.05`，出点必须 `> start + 0.05`；
    失败只 toast，不改字幕。
  - 提交走 `updateCue()` → 服务端一步历史（自动标签「修改第 N 条时间」），⌘Z 可撤回。
  - 只作用于 `play.selected`；多选状态不改其它块。
- **切割**：`W` 在播放头切割当前字幕，复用 `splitCueAt()`；右键与键盘共用
  `canSplitAt()` 的 0.05 秒边距，禁止两套口径。播放头不在当前字幕内 / 太靠近两端只 toast。
- **试听**：`⇧Space` 调 `previewRange(cue.start, cue.end)`，复用现有 `stopAt`，播到句末
  自动停；不 seek 到别处、不改缩放、不改跟随。
- **磁吸（`N`，默认开）**：拖底部字幕块时吸附播放头与邻句边缘，`--accent` 虚线参考线。
  - 纯函数在 `lib/cueSnap.ts`；候选在 `beginCueDrag` 时冻结（含当时播放头），拖动中
    播放头继续走不会抖；抓取半径 7px 换算成秒后封顶 120ms；带滞回。
  - clamp 后边缘不再等于候选就丢弃参考线（不画骗人的线）。只作用于
    `cue-move / cue-l / cue-r`，**不碰**单击跳转、4px 框选、播放头擦洗、进度条。
  - 偏好存 `localStorage['kikusub.snap']`；开关不进历史。
- **全片适应（`⇧Z`）**：`lib/timelineView.ts` 的 `toggleFitView()` 记住当前视窗切到全片，
  再按恢复；不改跟随，不改 `FOCUS_ZOOM=69` 的聚焦公式。
- **倍速（`1` / `2` / `3`，`⇧2` 归 1×）**：固定档位 `0.5× / 1× / 1.5× / 2×`。
  - `1` 降一档并播放，`3` 升一档并播放，`2` 暂停并保留倍速；`⇧2` 归 1×。
  - 显式 `video.preservesPitch = true`，日语台词变速不变调；换片静默复位 1×。
  - 非 1× 时时间码旁出现可点击的倍速标签，单击恢复 1×；标签不是历史编辑。
  - **不做真倒放**：HTML5 `playbackRate` 不支持负值，定时 seek 模拟反向会与 rAF 推进 /
    音频解码打架；产品上只承诺倍速，不承诺反向穿梭。
- **历史与红线**：入点 / 出点 / 切割走服务端统一历史；步进、试听、磁吸、全片、倍速
  都不进历史。吸附只叠加在 `cueDragTimes()` 之后，不碰 `CLICK_SLOP=4`、进度条
  click-to-seek 与 `duration/69`。`store.svelte.ts` 未增行；`ReviewView` 预算从
  3877 → 3808 → 3802（`tests/test_big_file_budget.py`）。
- **回归**：`desktop/test/frameStep.test.mjs`、`cueEdit.test.mjs`、`cueSnap.test.mjs`、
  `timelineView.test.mjs`、`playbackRate.test.mjs`；Python `tests/test_media_probe.py`；
  真实界面 `tools/shots/verify_review_transport.mjs`（24fps 片源，无窗口）。

#### 3.4.7 核对台工作现场持久化（2026-11-20）

用户报障：「核对到第 137 条，去转写页再回来，视窗回到全片、播放头回到 0」；
以及切页回来波形先白一帧、同一段包络反复请求。两件事都在
`desktop/renderer/src/lib/reviewViewport.ts`（纯函数 + 模块级缓存），组件只接线。

- **波形包络缓存（仅内存）**：键 = `媒体 id | from | span | bins`，LRU 48 项。
  命中时**同步**写回 `peaks / peaksFrom / peaksSpan`，不走 70ms 防抖、不再请求
  `/peaks`——切页回来第一帧就有波形。只存内存：包络是派生数据，没有跨重启价值；
  视窗宽度/高度变了 `bins` 变，旧分辨率不会被复用（否则画成锯齿）。
- **每部影片的现场快照**：`{cueIndex, cueTime, playhead, viewStart, span, selection}`，
  按**媒体文件路径**（不是 media id：重启后 id 会变）写
  `localStorage['kikusub.reviewViewports']`，最近 **50 部**（LRU，`updatedAt` 淘汰）。
  同一位置重复写会被跳过（核对台每 1.5s 落盘一次，播放头静止时不该每 1.5s 全量写盘）。
- **时序**：恢复只在 `<video>` 的 **loadedmetadata** 之后发生（早于它写
  `currentTime` 会被浏览器丢掉）；缩放 / 选区按 `duration` 夹紧（`planViewportRestore`），
  越界或损坏的快照安全降级为「不恢复」。每次换片只恢复一次（`restoreDoneFor`）。
- **换片先落盘**：媒体变化 effect 在复位 `viewStart / viewSpan / play.time` **之前**
  先把上一条落盘；定时器回调与清理函数都校验 `app.media.path === 捕获值`，避免
  换片后旧闭包用归零后的状态覆盖上一部片的现场。
- **显式跳转优先**：`focusRange()`（双引擎复核 / 质检面板 / 报告页 / 翻译页点时间码）
  先 `markExplicitJump(path)`；核对台恢复前 `takeExplicitJump(path)` 命中就**整次跳过**
  历史恢复。标记带路径，只影响那一次、那一部片——不能用一个全局布尔，否则用户从
  别的页面跳转后再换片会被上一次的标记影响。
- **选中行恢复**：`resolveCueIndex()` 先看下标是否还指同一时间（±0.5s），字幕表被
  重新转写 / 导入替换后按 `cueTime` 找最近的一条；找不到就不动。
- **旧数据兼容**：没有新格式快照时退回 `localStorage['kikusub.lastPosition']`
  （旧版只记一个全局播放头），升级不丢现场；`openMedia` 不再单独 seek 一次，
  避免两处恢复互相覆盖。
- **预算**：逻辑全在 lib（新增 `lib/waveformCanvas.ts`：把 `draw()` 的画法整段搬出；
  `lib/findMatches.ts`：查找命中计算）；`ReviewView.svelte` 3802 → 3787，
  `store.svelte.ts` 3287 → 3278（旧 playhead 持久化搬进 lib）。
- **回归**：`desktop/test/reviewViewport.test.mjs`（LRU / clamp / 显式跳转优先级 /
  旧键迁移 / 缓存键）；真实界面 `tools/shots/verify_review_viewport.mjs`
  （切页回来不重新请求 /peaks、缩放 / 播放头 / 选区恢复、快照按路径落盘）。

#### 3.4.8 短选区「轻声兜底」（2026-11-20，只作用于核对台人工短选区）

整片转写里 VAD 没切出语音时返回空结果**是对的**（静音/雨声会被幻觉成字幕），
但人工框选 2 秒有人在说话的气声句，默认阈值（Whisper 0.25 / Qwen 0.30）切不出来
就会报「未检测到有效语音」——用户听到的和界面报的相反。

- 触发条件只有一处：`server/routes_jobs.py` 把 `short_clip_fallback` 置为
  `payload.apply == "replace_range"`，即「转写选区 / 重转此句 / 质检补录」。
  **整片转写与追加（`replace` / `append`）永远是 False**，VAD 挡幻觉的防线不动。
- 降级链（`core/short_clip.py`，纯函数 + 可注入重试）：
  1. 先按当前参数跑（含用户自己调过的阈值）；
  2. 空且选区 ≤ **20s**：阈值降到 **0.05** 静默重试一次；
  3. 仍空且选区 ≤ **12s**：跳过 VAD，整段（保留 dynaudnorm）经
     `engine.transcribe_window()` 送模一次，产出一条覆盖选区的字幕；
  4. 再空才让 `pipeline` 报「未检测到有效语音」。
- 字段名按引擎族的真实 schema 取（whisper `threshold`，qwen/sherpa `vad_threshold`），
  不另造映射；用户已经把阈值调到 0.05 以下时跳过第 2 步。取消在任何一步之间生效，
  整段解码期间的取消被吞成「没有结果」，不报成失败。
- **未改动**：`core/params.py` 的默认值、`tools/eval/` 与 `baseline.json`、整片
  转写、质检门控。Sherpa 新增的 `transcribe_window()` 只服务窗口复核与这条兜底。
- **回归**：`tests/test_short_clip.py`（阈值/步骤/取消/解码取消）、
  `tests/test_pipeline.py` 的 4 个 short_clip 用例（含「整片绝不做整段送模」）。

#### 3.4.9 章节 / 时刻点标记（2026-11-20）

- **数据**：`{id, start, end?, title}`；`end === null` = **时刻点**，
  `end` 有值 = **场景区间**（`00:00 → 23:30 场景1`）。上限 500 条、标题 120 字。
  唯一实现在 `core/chapters.py`（`ChapterMark / normalize_marks / layout_chapters /
  ffmetadata_text`），前端不算顺序/衔接。
- **衔接与防重叠**（`layout_chapters`）：按 `start` 稳定排序 → 夹进 `[0, duration]`
  → 区间不超过下一个标记起点 → 时刻点结束于下一个起点或片尾 → 长度 <1ms 丢弃。
  首个标记晚于 0 时**补一个「开场」章节**：MP4 的章节是一条文本轨，ffmpeg 会把首章
  强行拉回 0；不补的话「12s 的时刻点」在 MP4 里会跳到片头。MKV 本来能保住起点，
  但两份容器同一份章节表更可预期。
- **持久化**：`{output_dir}/chapters/{stem}.{path+size+mtime}.chapters.json`
  （原子写）。路径 + 大小 + mtime 分段：重新压制的同名片不会套上旧章节。
  `server/routes_session.py` 的 `bind_media` 换片时 `session.sync_chapters()` 恢复。
- **历史**：标记进 **`Session.history` 那条统一时间线**（`HistoryState.chapters`），
  没有第二套撤销栈。整表提交 `POST /api/chapters`（`{marks, label}`）→
  `session.set_chapters()` 先 `ensure_baseline()` 再落一步 `_record(label)`，
  所以新建/改名/改时间/删除都是「一次操作 = 一步 ⌘Z」；`_apply_state` 撤销时
  同时把边车写回磁盘（重启后不会看到撤销前的内容）。
- **界面**：`components/ChapterTrack.svelte` 覆盖在刻度条下沿（`top: RULER_H`，
  6px 色条 + 旗标；覆盖层 `pointer-events:none`，只有旗标可点——不能吃掉刻度擦洗）。
  `components/ChaptersPanel.svelte` 是检查器第三个页签「章节」：输入标题回车 =
  「有选区则设为章节，否则在播放头插时刻点」；列表支持点击跳转、编辑标题/起止
  （终点留空 = 时刻点）、删除。导入/历史/换片统一经 `lib/chapters.svelte.ts`。
- **导出**：见 [export-and-prompt.md](export-and-prompt.md) §3.8.2。导出页开关走
  `setExportChapters()`（进统一历史），有标记时默认开并显示数量。
- **「仅处理此片段」**：区间章节（`end` 有值）的操作区多一个按钮，把这个章节设为
  **处理 / 导出范围**（`setExportClip()`，进统一历史）。润色、翻译、导出三页共用这
  一份；时刻点不提供该入口（它是点，不是可处理的片段）。契约见
  [ai-proposal.md](ai-proposal.md) §3.7.8。
- **回归**：`tests/test_chapters.py`（衔接/夹紧/重复 id/转义/持久化/一步历史/撤销
  写盘）、`tests/test_export_chapters.py`（三种模式 + `ffprobe -show_chapters`）、
  `tools/shots/verify_chapters.mjs`（真实界面：添加/编辑/⌘Z/旗标跳转/仅封装导出）。
