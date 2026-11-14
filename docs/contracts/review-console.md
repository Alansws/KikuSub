# 核对工作台与内核设计原则

> 从 `AGENTS.md` 拆出（2026-11-13）。这是**核对台 / 内核边界 / 历史 / 主题 / 查找替换 / TTS / 选区**这一域的契约正文，改动前必读；总索引与红线见 [AGENTS.md](../../AGENTS.md)。

> 里面每条规则都带着「为什么」和日期——**不要删理由**，那正是它当初被写下来的原因。

---

### 3. 核对工作台与内核设计原则

> 旧 Gradio 界面（`app.py` / `static/`）已从仓库移除，源码归档在 Git 标签 `v0.9-gradio` 与本地独立目录 `~/Downloads/kikusub_gardio`。本章只保留当前桌面端 + 共用内核仍然有效的约束；桌面端核对台从 §3.4 开始。

- **断句改动必须有数字（2026-11）**：改 `qwen_ctc._break_costs` / `partition_cues` / VAD 参数前后，必须用 `python tools/eval/score_srt.py --reference ... --hypothesis ... --from ... --to ...` 跑同一区间，同时看 CER、`particle_start_cues`、`aux_start_cues`、最长条与 >4.3s 条数。禁止只凭个别样例“看起来更好”就改词边界；减少劈词与块均准确率之间存在已知取舍。
- **并发与取消（2026-11 加固）**：转写/局部转写必须通过 `jobs.JobRegistry` 单槽占用，**禁止**再引入模块级 `CANCEL_EVENT`。取消令牌必须归属于发起任务的会话；别的窗口点「打断」只能收到“本会话没有任务”的提示，绝不能误伤正在跑的任务。客户端断开只发取消信号，槽位由真正停止工作的 worker 在 `finally` 中释放，避免“界面已返回、模型还在跑”时被新任务覆盖。所有 `subprocess` 外部命令必须走 `procutil.run_command`（超时/取消/terminate），代理成片先写 `*.part.mp4` 再原子 rename。
- **`app.job` 不是「正在跑」的判据（2026-11-14 修复）**：任务结束后 `app.job` 会保留最后一份快照（状态栏、工具栏要读时长与百分比），所以 `!!app.job` 永远为真。要判断「有任务在跑」一律用 `lib/jobState.ts` 的 `jobBusy()`（`running` / `queued` / `cancelling`）；2026-11-14 就是因为它，「另一引擎复核」按钮在第一次转写之后永久变灰。
- **覆盖审计（2026-11 新增）**：主 VAD 的漏检（VAD 没切到、Whisper 根本没收到）不会产生 `missed` 记录，所以 `core/coverage.py` 必须保持一条**只读旁路**：按字幕切空白间隙 → 20ms/40ms RMS 包络 → 每个间隙取最长候选 → 局部峰值归一化后跑一次 Silero 只取概率 → `last_coverage_spans` 交给 `build_audit_items(coverage_spans=...)`。它**不回写**字幕、不改主 VAD 参数、不改 `load_wav_mono` 的电平；`find_coverage_spans()` 失败必须吞掉，不能影响转写。质检对用户只暴露两个组：`coverage` → `miss`（漏检，默认置顶），`missed/dropped/suspect` → `low`（低置信，默认折叠）；`_audit_coverage()` 仍然只表达引擎能力，不要把 `coverage` 塞进去。默认参数（8s 空白 / 1.5s 候选 / 65 分位 / 局部 VAD 均值 0.20）是在 2026-11-10 的 14 分钟样本上调的；改阈值前先用同一段音频跑 `find_coverage_spans()` 看召回与条数。
- **补录区间必须夹在空白边界内（2026-11 修复）**：`QaPanel.fill()` / `ReviewView` 的 `padEnd:0.3` 会把覆盖项尾部的下一句开头也切进来；`transcribeRange()` 现在接受 `clampStart/clampEnd`，调用方必须传 `item.gap_start/gap_end`。`server/jobs.py` 的 `replace_range` 也不能再按「cue.start < 区间尾就删」处理：只删除重叠 ≥50% 或中点落入区间的 cue，边缘被切到 0.2s 的邻句必须保留。回归用例在 `tests/test_server_jobs_range.py`。

#### 3.4 桌面版核对台（`desktop/renderer/src/views/ReviewView.svelte`）

- **单击 vs 框选**：`pointerdown` 先进入 `pending`，移动超过 `CLICK_SLOP=4px` 才升级为
  `select`。禁止恢复「按下即建选区」：全局视图下 1px 就是好几秒，用户报障过“单击跳转被
  识别成框选”。
- **擦洗区**：顶部 `RULER_H=17px` 和播放头两侧 `PLAYHEAD_GRAB=8px` 是专属 scrub；
  `beginScrub / setScrub / endScrub` 负责暂停、16ms 节流写 `video.currentTime`、松手
  恢复原播放状态。视频进度条复用同一套（禁止再写独立的 click-to-seek），三者共同保证
  拖动时能逐帧预览。
- **底部字幕轨道**：`LANE_H=17px`，`cueBlockAt()` 按 `(start, end)` 把同区间的双语/
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
- **切割 / 合并 / 多选删除（2026-11 新增）**：
  - 有字幕区域右键新增「切割字幕」：`POST /api/cues/{index}/split` 在光标时间把一句切成两段，
    **两段都保留完整原文**（用户明确要求：自动判断断点内容不可靠，先保留原句再分别删减）。
    切割点距两端至少 0.05 秒；译文轨在同一位置复制一条，双语不会错位。
  - 框选两条以上字幕后右键「合并这 N 句字幕」：`POST /api/cues/merge` 取首尾时间、文本按顺序
    直接相连（西文单词间补空格），译文轨同样拼接。只允许下标连续的多条。
  - 底部字幕轨道支持 ⌘ 单击多选（再点取消），`POST /api/cues/delete` 批量删除只压一次历史；
    ⌘ 多选块在画布上用 accent 描边。删除必须同步删掉译文轨同下标条目。
  - 服务端的插入 / 删除 / 切割 / 合并都要经 `Session` 的结构性方法调整 `translations`，
    **禁止**只改 `review_cues` 让译文轨自己错位。`HistoryState` 现在连译文轨一起快照，
    ⌘Z 才能把字幕与译文成对恢复。
- **可自定义快捷键（2026-11 修订）**：`desktop/renderer/src/lib/shortcuts.svelte.ts` 是唯一映射，
  ⌘K 打开面板录制新组合（该快捷键本身也可改）。默认值：Enter 删除当前字幕（底部多选时一起删）、
  Space 播放 / 暂停、↑↓ 上下句、⌘F 查找、⌘↩ 添加空字幕、**⌘G / ⇧⌘G 查找下一处 / 上一处**
  （`scope: 'find'`，只在查找栏打开时生效，见 §3.4.2）；视图键按工作流固定为
  **⌘1 导入 / ⌘2 转写 / ⌘3 核对台 / ⌘4 双引擎复核 / ⌘5 润色 / ⌘6 翻译 / ⌘7 导出**。
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
  - 音色落在 `{output_dir}/voices/<id>/`：`ref.wav`（24k/单声道/PCM16，已去首尾静音、≤10s）、
    `meta.json`（名称/参考文本/时长/来源）、`prompt.pt`（OmniVoice 声线 embedding 缓存，
    损坏或模型升级后自动重建）。**目录名用 id，不用音色名**：用户会重命名、用中文/空格。
  - 接口：`GET /api/tts/voices`（system + custom + engine/download 状态）、
    `POST /api/tts/synthesize`、`POST /api/tts /voices/extract-from-media`（用 ffmpeg 从
    当前视频精准切片 → 建音色）、`/api/tts/voices/upload`、`PATCH|DELETE /api/tts/voices/{id}`、
    `PUT .../ref-text`、`POST /api/tts/model/download`、`GET /api/tts/model/verify`
    （只读校验权重，0 字节文件也算缺失；设置页「校验 / 补齐」先走它，完整时不再弹下载确认）。
  - 缓存键 =「引擎 + voice_id + 参考音频指纹(mtime/size) + ref_text + 文本 + 速度」，
    命中直接返回文件名；`{output_dir}/tts_cache` 只留最近 240 个。音频流仍是
    `/media/tts/{file}?token=`（`<audio>` 发不了 Authorization 头）。
  - 资源：克隆模型**首次真正合成才加载**；空闲 `KIKUSUB_TTS_IDLE_SECONDS`（默认 300s）
    自动卸载；`JobManager` 的 `on_heavy_job` 在 transcribe / proxy / export 开跑前调
    `TTSManager.release()`。`KIKUSUB_TTS_DEVICE=cpu|mps` 可强制设备，
    `KIKUSUB_TTS_MODEL_DIR` 可改权重目录（默认 `models/omnivoice`）。
  - 下载走 `core/tts/model_store.py` 的独立后台线程（不占 `JobManager` 单槽），
    进度由 `/api/tts/voices` 的 `engine.download` 带出；模型约 3.3GB，**不随包分发**。
  - 前端：`store.tts` 的 `voiceId`/`speed` 落 `localStorage['kikusub.ttsVoiceId']` /
    `['kikusub.ttsSpeed']`（旧 `ttsVoice`/`ttsRate` 自动迁移）。右侧检查器负责音色下拉
    （克隆/系统分组）、**上传参考音频（原生对话框默认落在上次上传目录 / 当前视频目录，
    可一次选多段，每段各建一个音色）**、**从当前句截取**、**音色库（保存/试听/设为默认/
    重命名/删除/在访达中打开）**、模型下载；字幕表与波形右键「以此句音频新建音色…」
    仍走 `extractTtsVoiceFromCue()`。参考音频提示只保留一行「3–10 秒、单人、干声、无音乐」。
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
