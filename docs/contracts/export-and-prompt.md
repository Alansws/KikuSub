# 提示词模板、成片导出与手动代理

> 从 `AGENTS.md` 拆出（2026-11-13）。提示词模板库、成片导出、手动代理、媒体 Range 与日志清理。总索引见 [AGENTS.md](../../AGENTS.md)。

---

### 3.8 提示词模板、成片导出与手动代理（2026-11 新增）

#### 3.8.1 提示词模板库

- 模板是普通 JSON，默认与 `settings.json` 同级（`prompts.json`，
  `KIKUSUB_PROMPTS_PATH` 可覆盖）。**2026-11 起分三个互不混杂的分类**：
  - `polish_single`（单源润色）：`{{SRT}}` / `{{RANGE_HINT}}`；
  - `polish_dual`（双源润色）：`{{SRT_A}}` / `{{SRT_B}}` / `{{RANGE_HINT}}`；
  - `translate`（翻译）：`{{SRT}}` / `{{LANG}}`。
  内置模板各分类至少一条；用户修改会持久化，删掉文件恢复出厂。
  2026-11-15 起 `polish_dual` 多一条内置「歌曲歌词润色」：副歌重复段互校、
  统一汉字/假名/英文用字，**仍保持 A 的条数与时间轴**（不开口子补句）。
- 分类各自记住选中项：`selected`（翻译，兼容旧文件）、`selected_polish_single`、
  `selected_polish_dual`。旧 `prompts.json` 里没有 `category` 的模板归入 `translate`；
  跨分类 `select` 会 422。
- 正文占位符兼容旧版 `__SRT__` / `__LANG__`。**没有 SRT 占位符时自动把当前字幕
  追加到末尾**，所以纯指令模板也能直接用。分段提示词会替换
  `{{RANGE}}` / `{{RANGE_HINT}}`；旧模板没有范围占位符时，范围说明会加在正文最前面。
- 手动通道 `GET /api/ai/prompt` 现在接受 `template_id`，缺省用当前选中模板；
  解析回来的 SRT 仍然**只按顺序取文本**，序号/时间戳全部丢弃（D-1 不破）。
- 界面：侧栏「提示词库」；单击选中、双击就地编辑；保存后 AI 优化台的
  「复制提示词」立刻用新内容。禁止把模板内容写进 `settings.json` 或日志。
- **润色也能走手动通道（2026-11）**：`GET /api/ai/prompt?kind=polish` 返回内置润色提示词
  （`core.ai_polish.build_manual_prompt`，带 SRT），`POST /api/ai/from-srt` 的 `kind=polish`
  只按顺序取文本、时间轴仍用当前 cue。润色不要求 API Key，也不绑定「AI 优化」开关。

#### 3.8.2 成片导出

- **不要依赖 ffmpeg 的 `subtitles` / `ass` 滤镜**：Homebrew 的 ffmpeg 默认没有
  libass/freetype（本机 9.0.2 实测没有）。硬字幕走 Pillow 透明精灵 + ffmpeg
  `crop` 时间表达式 + 单个 `overlay`；每批最多 60 句（240 句时 FFmpeg 会报
  `Failed to configure input pad`），块高固定，第 0 块是空白。
- 输出文件名用**实际高度**（源 360p 选 1080p 不会放大，名字写 `360p`），不要
  用用户选的档位骗人。
- 三种模式：`burn`（重编码 + 烧录）、`soft`（重编码 + `mov_text` 软字幕）、
  `copy`（`-c copy` + 软字幕，MP4 不兼容时退回 MKV）。`copy` 模式忽略分辨率/
  码率，规划里要明确告诉用户。
- 编码先试 `h264_videotoolbox`，失败回退 `libx264`；音频 AAC（≥720p 192k，
  否则 128k）；写 `.part` 再原子 rename；`JobManager` 单槽，kind=`export`。
- **进度与取消（2026-11 修复）**：ffmpeg 命令必须带 `-nostats -progress pipe:1`，
  `core/video_export._progress_reader` 用读线程 + 队列轮询，每 150ms 检查取消令牌。
  旧实现没有 `-progress`，stdout 永远没有数据：进度停在 0%，取消也要等 ffmpeg 自己跑完。
  精灵渲染阶段同样要报进度（0–10%）并在每批前检查取消/关机状态。
- **不能留下孤儿 ffmpeg（2026-11 修复）**：Electron 以 `detached:true` 启动 sidecar
  （新进程组），退出时 `kill(-pid)` 覆盖整棵树；主进程退出路径必须
  `await stopSidecarAndWait()` 后再 `app.exit`，不能只发信号就走。
  sidecar 侧：`_KikuSubServer` 在 SIGTERM/SIGINT 时先 `jobs.cancel_all()`，
  再 `begin_shutdown()` + `terminate_all_processes()`；`core/procutil` 的
  `SPAWN_LOCK` 保证关机开始后不会再出生新的 ffmpeg；`server/__main__.py` 还有
  父进程看门狗（Electron 崩溃/被强杀时 sidecar 在 2s 内自杀）。
  **禁止**把这些改回裸 `subprocess.run` 或只 `child.kill()`。
- **章节 / 时刻点写入（2026-11-20 新增）**：
  - 导出页开关「写入章节标记」走 `setExportChapters()`（红线 8：进统一历史），
    有标记时默认开，徽标显示当前标记数；`ExportOptions.write_chapters` 是唯一开关，
    `GET /api/chapters` 的 `chapters` 是**实际会写进容器的区间**。
  - 后端 `core/chapters.py` 按 `start` 排序并处理衔接/防重叠：时刻点 = 下一个标记
    起点或片尾；区间不超过下一个起点；首个标记晚于 0 时补「开场」——MP4 的章节
    是文本轨，ffmpeg 会把首章拉回 0，不补的话真实起点会丢。
  - 生成 `;FFMETADATA1` + 每章 `[CHAPTER] / TIMEBASE=1/1000 / START / END / title`，
    值里的 `\ ; # =` 与换行按 ffmetadata 规则转义（换行 = 反斜杠 + 真实换行）；
    临时文件写好后追加为**最后一个输入**，再用 `-map_chapters <输入序号>` 注入。
  - 三种模式都支持：`burn`（字幕精灵输入在前，序号 = 1 + sprite 数）、
    `soft` / `copy`（序号 = 2）。「仅封装」因此几秒就能出带章节的 MP4/MKV，
    不重编码、画质无损。
  - 回归：`tests/test_export_chapters.py` 用 `ffprobe -show_chapters` 读回容器，
    逐条核对标题 / 起止 / 有序不重叠（IINA 等播放器能直接跳转）；`burn` 用例在没有
    中文字体的机器上按 marker skip。
- **片段导出（2026-11-20 新增）**：导出页「导出范围」（全片 / 区间章节 / 自定义）与
  润色 / 翻译页共用 `store.exporter.clip`（走 `setExportClip()` 进统一历史）。
  - 纯函数在 `core/clip_range.py`：`clip_window()`（归一化窗口）、
    `select_cues_in_range()`（首尾重叠 <0.1s 的邻句不算命中）、
    `shift_cues_to_clip()`（`t - start` 并夹进 `[0, duration]`）、
    `shift_chapters_to_clip()`（保留相交的区间标记与内部时刻点，区间**不被时刻点拆开**；
    例：`0:10 章节1` + `22:55 发射点` 裁成 `[10s, 1462s]` → `0:00` / `22:45`）、
    `clip_tag()`（文件名安全标签）。
  - `ExportOptions` 增加 `clip_start` / `clip_end` / `clip_label`（全片 = `0/0`）；
    `plan_export()` 的 `duration`、码率估算、章节表都按**片段时长**计算，`plan.clip`
    回传 `{start, end, duration, label}`；`copy` 模式额外给「仅封装按关键帧切片」的 warning。
  - `run_export()`：字幕、译文、ffmetadata 章节先经上述纯函数搬到片段坐标，再执行
    ffmpeg：`-ss <start>` 放在 `-i` **之前**（重编码 = 帧级精确，输出时间戳从 0 起）
    + `-t <片段时长>`。`burn` / `soft` **不加** `-avoid_negative_ts make_zero`
    （会因 AAC priming 把字幕轨整体推后 3ms）；只有 `copy` 加它，保证关键帧切片后能正常播。
  - **章节必须二次 remux**：ffmpeg 9.0.2 在「mov_text 字幕 + MP4 章节文本轨」同一次封装时
    会写坏章节头（标题重复成末章、首章 `END` 变成「片段时长 − 首章结束」），`ffprobe` /
    播放器都会读到错的时间。所以 `soft` / `copy` 先出片（不带章节），成功后用
    `-i 成片 -i ffmetadata -map 0 -map_chapters 1 -c copy` 再封装一次；`burn` 没有字幕流，
    仍单次封装。二次 remux 是纯复制，不重编码。
  - 文件名：`{stem}{suffix}.{clip_tag}.{分辨率}.{档位}{ext}`，随片 SRT 同标签
    （`{stem}{suffix}.{clip_tag}.srt`），不会覆盖整片成片。
  - 字幕单独导出：`POST /api/cues/export` 接受 `clip_start` / `clip_end` / `clip_label`，
    先按同一规则选中这一段、把原文与译文一起平移，再走 `target_cues` / `bilingual_entries`；
    文件名后缀带 `.章节1-00m10s-24m22s`。范围内没有字幕 → 409。
  - UI：选择 `copy` + 片段时，导出卡片里出现明确说明「按关键帧切片，精切请用烧录/软字幕重编码」。
  - 回归：`tests/test_clip_range.py`、`tests/test_export_clip.py`
    （软字幕 / 仅封装 / 字幕单独导出，全部用 `ffprobe -show_chapters` 与
    `ffmpeg -f srt` 读回真实产物核对时长、章节 8.5s、字幕归零）。
- **字幕样式（2026-11 新增）**：`SubtitleStyle`（字体/字重/字号/描边/阴影/位置/颜色）
  只影响 `burn`；字体以「文件名 + TTC 内 family/style 名」解析（macOS 的 PingFang、
  兰亭黑等位于 AssetsV2 的 hash 目录，禁止写死路径）。内置预设见 `STYLE_PRESETS`；
  `/api/export/styles` 必须返回本机可用性，`/api/export/style-preview` 用与导出
  完全相同的 `_text_layer()` 渲染 PNG（可带真实视频帧与 `zoom` 特写）。
  改样式字段时同步 `desktop/renderer/src/lib/api.ts` 的 `SubtitleStylePayload`。
- 目录：设置里的 `video_export_dir`，空值跟随 `export_dir`；所有路径统一在
  设置页「运行环境」的 `.path-row` 列表中展示/更改。
- **交付页收尾（2026-11-21，界面重构 Step 6）**：底部操作栏只留「开始导出」，
  不再放「为什么在 KikuSub 里导出」这类宣传性说明；没有译文轨时，字幕文件与
  成片「字幕轨」两处置灰的「译文 / 双语」旁边各跟一句轻量引导
  （`.trk-hint`：「暂无译文轨，可在 AI 处理 → 翻译生成后导出双语」，有译文轨即消失）。
  回归：`tools/shots/verify_settings_ai_fold.mjs`（含导出页两处 hint 与底部只剩一个按钮）。
- 依赖：`Pillow>=10` 必须进 `requirements.txt`；`plan_export` 在缺 Pillow 时
  直接给「改用软字幕」的可读错误。`tests/test_export.py` 覆盖 burn/soft/copy。

#### 3.8.3 手动代理

- `MediaInfo` 现在带 `video_width/height/bitrate` 与 `proxy_reason`
  （`container` / `codec` / `bitrate`）。`needs_proxy` 在码率 ≥25 Mbps 时也为真，
  但它只是「建议代理」的元数据，**不再触发任何自动任务**。
- **导入不再自动压制（2026-11-15）**：`auto_proxy` 设置已彻底删除（旧
  `settings.json` 里的残留键会被忽略）。能正常出画面的视频——包括高码率 H.264
  （能播但拖动卡）——一律不自动压；用户可在核对台「⋯」里手动「压制代理」。
- **黑屏才提示**：核对台画面中央的提示由 `lib/videoFallback.ts` 判定——
  `<video>` 触发 `error`，或 `container` / `codec` 原因下 2.5s 内仍没解出首帧。
  计时从拿到媒体 / 切换 src 就开始，**不挂在 `loadedmetadata` 上**（容器卡死时
  它可能永远不触发）；首帧（`loadeddata`）一到提示立即收起；`bitrate` 原因
  永不弹提示。提示里主按钮「压制代理」，次按钮「导入已有代理…」。
- **画面内不显示进度**：代理任务进行中，黑框中央只保留禁用态的「正在压制…」，
  **不放百分比、不放进度条**；唯一进度显示是顶部工具栏的蓝色 `.proxy-chip`。
  任务失败或取消后按钮随 `job.status` 自动回到可点击的「压制代理」；
  `proxy_ready` 但画面仍失败时只显示「代理已就绪，但画面仍无法播放」。
- 代理任务仍走 `/api/jobs` 的 `kind=proxy`。
- **已有代理可直接挂载（2026-11 新增）**：`POST /api/media/{id}/proxy`（`path`）交给
  `MediaStore.attach_proxy()` → `core.proxy.install_existing_proxy()`：优先硬链接，跨盘用
  符号链接，最后才复制；写进标准 `web_proxies/` 路径并原子 rename，重启后仍会被识别为
  已就绪。`openMedia()` 完全不再自动起压制任务。物理文件不存在/太小、
  音频文件或原片本身都会被拒绝。
- 画面提示文案不要写成「无法解码」这种绝对结论：`bitrate` 只是「能播但拖动卡」，
  而 `container` / `codec` 用「无法直接播放」即可。

#### 3.8.3.1 媒体 Range（2026-11 修复）

- 当前 Starlette 0.38 的 `FileResponse` **没有 Range 支持**（0.39 才加），直接返回
  `FileResponse` 会让 `<video>` 拖动进度条时重新下载整段。`server/routes_media.py`
  的 `_media_response()` 自己处理单段 Range：206 + `Content-Range`，只读请求区间；
  无效 Range 返回 416；无 Range 才退回 `FileResponse`。**不要**再把 `stream_media`
  改回裸 `FileResponse`。`tests/test_server_api.py` 与 `tests/test_proxy.py` 的
  Range 用例是这条的回归保护。

#### 3.8.4 日志清理与复制

- `/api/diagnostics/log/clean` 保持「按保留策略清备份」的语义；新增
  `/api/diagnostics/log/clear` 才**一定释放空间**：通过 handler 的
  `doRollover()` 轮转活动日志，再按 0 天/0 字节删备份，绝不直接 truncate
  正在写的流。主进程的 `main.log` 由 `logs:clear-main` IPC 截断/删备份。
- 设置页文案必须区分两者；`clean` 返回 0 时提示「没有过期备份，可点清空全部」。
- 「复制最近日志」限制 80 行、每行 500 字符；「复制精简诊断」只带最近 8 条问题
  + 20 行日志 + 路径/引擎摘要，并硬截断 24k 字符。**禁止**再把完整 300 行
  日志或 8000 字符 detail 直接塞进剪贴板。
