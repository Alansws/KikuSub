# AGENTS.md — 日语影片字幕转录工作台开发指南

本文件面向在此仓库中继续开发的智能体与开发者。开始改动前先阅读本文件和相关模块；它记录当前实际实现，而不仅是产品愿景。

## 1. 项目定位与运行方式

这是一个以 **Gradio** 提供本地 Web 界面的日语影视字幕转录工具。它面向动漫、电影、Galgame、广播剧等音频场景，支持：

- Anime Whisper：重视自然、连贯的日语对话转写；
- Qwen3-ASR + CTC：转写后利用自带的 CTC 对齐头取得逐字发声时间，并针对日语分句；
- Silero VAD 分段、可选动态响度归一化、时间范围转录、原片绝对时间轴、取消后保存已完成字幕；
- SRT/VTT/TXT 导出、纯标点字幕清理、参数预设读写与完整任务报告。

主入口是 `app.py`。在安装 `requirements.txt` 及系统 `ffmpeg` 后运行：

```bash
python app.py
```

服务仅监听 `127.0.0.1:7860`，并在浏览器中打开。首次真正转录时才会加载（必要时下载）模型。不要在不需要模型推理的改动验证中触发下载或完整转录。

## 2. 仓库结构

| 路径 | 职责 |
| --- | --- |
| `app.py` | Gradio 页面、参数控件注册、预设交互、任务编排、文件写出和报告生成。 |
| `transcribe.py` | 共用字幕数据结构/格式、时间解析、FFmpeg 音频抽取、Anime Whisper、Silero VAD 和启发式分句。 |
| `qwen_ctc.py` | Qwen3-ASR 模型推理、CTC 对齐头、日语断句动态规划、字幕劈词修复。 |
| `audio_cache.py` | 16k wav 解码缓存（`cache_key` / `ensure_wav` / `peaks` / `prune`），转写与核对台波形共用一次解码；`KIKUSUB_AUDIO_CACHE=0` 关闭。 |
| `presets.py` | `presets.json` 的校验、向后兼容读取和原子写入。 |
| `presets.json` | 用户持久化的命名调参预设；属于运行数据，修改其 schema 时要兼容旧内容。 |
| `models/` | 模型缓存。`anime-whisper/` 与 `qwen3-asr-ja-anime/` 均可能很大，不应作为普通源码改动。 |
| `outputs/` | 生成的字幕样例和运行产物。 |
| `README.md` | 面向用户的安装、功能和调参说明；改变用户可见行为时同步更新。 |

## 3. 补漏核对工作台设计原则

- **监看画面与转录源解耦**：`review_payload` 的 `src` 有四种来源——自动跟随导入的媒体、手动导入的任意本地片源（`📂 导入监看画面`）、`outputs/web_proxies` 里的历史 480p 代理（`📦` 下拉，零拷贝）、以及「已关闭」空态。手动片源路径记录在 `outputs/monitor_last.json`，供下次打开自动恢复；`prepare_review_workspace`（即 `media.change`）会清空该记忆，重新回到自动模式。`src` 为空时前端必须销毁 `window.__reviewerInstance` 与 keydown 监听，避免悬空引用。
- 底部核对区由 `review_cues_state` 管理，和当前转写结果 `cues_state` 分离。导入 SRT 或“将本次转写设为基线”才会覆盖核对基线；“添加本次局部转写”追加去重后的条目。
- 视频播放器拖动进度条、播放时，底部音频轨道必须有高亮时间播放线（时间游标）实时同步跟随。
- 触控板缩放（捏合）与双指横移操作需精准平滑支持，允许将局部波形横向大幅放大（如放大至数秒区间），方便精细框选。
- 框选范围后，提供一键将该时间段同步到上方“时间片段截取”输入框（`slice-start`, `slice-end`），且能够联动更新上方的状态或者直接触发局部转录。
- 重新导入 SRT 时，必须彻底更新 `review_cues_state` 以及前端表格和波形展示，杜绝旧基线残留。
- **全链路撤回/重做体系 (Undo/Redo)**：由 `undo_stack_state` 与 `redo_stack_state` 管理，支持任意删除、单行更新、插入、清空、导入或追加操作后的无损撤回。前端通过 `Cmd+Z` (Mac) 或 `Ctrl+Z` (Windows/Linux) 及界面按钮触发撤回，`Cmd+Shift+Z` / `Ctrl+Shift+Z` / `Ctrl+Y` 触发重做。
- **高健壮性与防崩溃规范**：核对区所有操作函数在面对用户误操作（如空白时间、非法格式、越界行号）时，一律采用 `gr.Warning()` 友好提示并返回 `fallback` 保护当前已有字幕状态，严禁抛出未经处理的 `gr.Error()` 导致界面状态丢失；所有 Gradio 事件处理函数返回值的数量必须与 `outputs` 声明的组件列表严格一一对应。
