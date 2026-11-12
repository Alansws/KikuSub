# 提示词模板、成片导出与手动代理

> 从 `AGENTS.md` 拆出（2026-11-13）。提示词模板库、成片导出、手动代理、媒体 Range 与日志清理。总索引见 [AGENTS.md](../../AGENTS.md)。

---

### 3.8 提示词模板、成片导出与手动代理（2026-11 新增）

#### 3.8.1 提示词模板库

- 模板是普通 JSON，默认与 `settings.json` 同级（`prompts.json`，
  `KIKUSUB_PROMPTS_PATH` 可覆盖）。内置两条：`legacy`（原有模板）与
  `localization`（成熟汉化组）；用户对内置模板的修改会持久化，删掉文件恢复出厂。
- 正文占位符只有 `{{SRT}}` 与 `{{LANG}}`（兼容旧版 `__SRT__` / `__LANG__`）。
  **没有 `{{SRT}}` 时自动把当前字幕追加到末尾**，所以纯指令模板也能直接用。
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
- **字幕样式（2026-11 新增）**：`SubtitleStyle`（字体/字重/字号/描边/阴影/位置/颜色）
  只影响 `burn`；字体以「文件名 + TTC 内 family/style 名」解析（macOS 的 PingFang、
  兰亭黑等位于 AssetsV2 的 hash 目录，禁止写死路径）。内置预设见 `STYLE_PRESETS`；
  `/api/export/styles` 必须返回本机可用性，`/api/export/style-preview` 用与导出
  完全相同的 `_text_layer()` 渲染 PNG（可带真实视频帧与 `zoom` 特写）。
  改样式字段时同步 `desktop/renderer/src/lib/api.ts` 的 `SubtitleStylePayload`。
- 目录：设置里的 `video_export_dir`，空值跟随 `export_dir`；所有路径统一在
  设置页「运行环境」的 `.path-row` 列表中展示/更改。
- 依赖：`Pillow>=10` 必须进 `requirements.txt`；`plan_export` 在缺 Pillow 时
  直接给「改用软字幕」的可读错误。`tests/test_export.py` 覆盖 burn/soft/copy。

#### 3.8.3 手动代理

- `MediaInfo` 现在带 `video_width/height/bitrate` 与 `proxy_reason`
  （`container` / `codec` / `bitrate`）。`needs_proxy` 在码率 ≥25 Mbps 时也为真。
- 自动压制仍由 `auto_proxy` 控制；核对台工具栏与画面提示都提供手动
  「压制代理」，不依赖自动判定。代理任务仍走 `/api/jobs` 的 `kind=proxy`。
- **已有代理可直接挂载（2026-11 新增）**：`POST /api/media/{id}/proxy`（`path`）交给
  `MediaStore.attach_proxy()` → `core.proxy.install_existing_proxy()`：优先硬链接，跨盘用
  符号链接，最后才复制；写进标准 `web_proxies/` 路径并原子 rename，重启后仍会被识别为
  已就绪。`openMedia()` 看到 `proxy_ready` 时不再自动起压制任务。物理文件不存在/太小、
  音频文件或原片本身都会被拒绝。
- 高码率 H.264 的提示文案要说明「能播但拖动卡」，不要写成「无法解码」。

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
