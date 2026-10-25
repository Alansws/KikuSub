# Contributing to KikuSub

感谢你愿意花时间改进这个项目。Issue 和 Pull Request 都欢迎，中英文均可。

提交之前，请先确认你的改动属于「修 bug」「补文档」或「可复用的功能」，而不是只针对某部片源的临时参数调整——后者更适合存成预设分享，而不是改代码。

## 报告问题

一个能复现的 issue 比十条描述都有用。请尽量附上：

- **环境**：操作系统、Python 版本、计算设备（MPS / CUDA / CPU）、`ffmpeg -version` 首行
- **复现步骤**：用的哪个引擎、哪些参数（可以直接粘贴「任务详报」，里面记录了全部生效参数）、媒体大致类型（动画 / 实拍 / 广播剧，多长）
- **日志**：终端里的完整 traceback，不要只截最后一行
- **样本**：不要上传整部片源。截取 5–10 秒能复现问题的片段即可

截图和日志里如果出现本机路径、片源文件名，请先打码。这些信息对定位问题没有帮助，但会留在公开记录里。

## 开发环境

```bash
git clone https://github.com/Alansws/KikuSub.git
cd KikuSub
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

界面不依赖模型就能启动，权重只在第一次真正转写时加载。改界面、改波形交互、改字幕格式这类工作，不需要跑完整转写。

只想验证不涉及推理的逻辑（字幕解析、预设读写等）时，直接 `python -c` 调用对应函数即可，不必启动 Gradio。

## 代码结构

| 文件 | 改动入口 |
| --- | --- |
| `app.py` | 界面布局、事件绑定、核对台操作、波形前端脚本（`REVIEWER_CLIENT_JS`）、任务详报 |
| `transcribe.py` | 字幕数据结构与 SRT / VTT / TXT 互转、FFmpeg 抽轨、Silero VAD 切分、Anime Whisper 流水线 |
| `qwen_ctc.py` | Qwen3-ASR 推理、CTC 对齐头、日语断句动态规划、字幕缝合 |
| `presets.py` | `presets.json` 的校验、兼容读取与原子写入 |

## 改动约定

以下几条是这个项目里踩过坑的地方，改动时请留意。

**新增调参项**
在 `app.py` 里用 `param()` 注册，`config_field` 必须对应 `WhisperVadConfig` 或 `QwenCtcConfig` 中真实存在的字段——启动时 `validate_params()` 会直接报错。参数键必须以引擎名开头（`whisper.` / `qwen.`）。

**预设兼容**
`presets.json` 属于用户数据，不是配置模板。新增字段要有默认值兜底（`presets.py` 的 `_normalize` 负责这件事），已有预设的键名不要重命名。删掉一个参数时，旧文件里残留的键应被忽略而不是报错。

**核对台状态**
`review_cues_state`（核对基线）与 `cues_state`（最近一次转写结果）是两份独立状态，不要混用。任何修改核对轴的操作都要先 `_push_history()`，否则撤销链会断。

**错误处理**
核对区的函数遇到非法输入（空时间、越界行号、格式错误）时，用 `gr.Warning()` 提示并返回 fallback 数据，不要抛 `gr.Error`——那会让界面状态丢失。事件处理函数返回的元组长度必须与 `outputs` 列表严格一致，多一个少一个都会静默失败。

**前端脚本**
波形缩放、框选、快捷键都在 `app.py` 的 `REVIEWER_CLIENT_JS` 字符串里。改动后请用触控板和鼠标各测一遍，并确认播放头仍与视频进度同步。

**文案**
界面文案目前是中文。改了用户可见的行为，请同步更新 `README.md` 与 `README_EN.md`。

## 提交与 PR

Commit 前缀用 Conventional Commits 风格：

```
feat: support VTT output with line breaks
fix: keep partial cues when the job is cancelled mid-segment
perf: reduce waveform peak extraction for 2h+ files
docs: clarify transformers version requirement
```

PR 描述里写清三件事：改了什么、为什么改、怎么验证（有截图或录屏更好）。一次 PR 只做一件事，方便 review 也方便回滚。

CI 会跑 `ruff check`、语法编译和 `presets.json` 校验，本地可以先跑一遍：

```bash
pip install ruff
ruff check .
```

## 不要提交的内容

- `models/`、`outputs/`、`*.autosave_draft.srt`、`*.progress.json` 等运行产物（`.gitignore` 已覆盖）
- 受版权保护的片源、字幕文件或截图
- 与本机环境绑定的绝对路径

## 许可证

提交代码即表示同意以本仓库的 [MIT License](LICENSE) 发布。模型权重不在该许可范围内，请勿把权重文件提交到仓库。
