# Contributing to KikuSub

感谢你愿意花时间改进这个项目。Issue 和 Pull Request 都欢迎，中英文均可。

提交之前，请先确认你的改动属于「修 bug」「补文档」或「可复用的功能」，而不是只针对某部片源的临时参数调整——后者更适合存成预设分享，而不是改代码。

## 报告问题

一个能复现的 issue 比十条描述都有用。请尽量附上：

- **环境**：macOS 版本、芯片（Apple Silicon / Intel）、应用版本（设置页右下角）、`ffmpeg -version` 首行
- **复现步骤**：用的是哪个引擎、哪些参数（可以在「详情与导出」里复制任务详报，里面记录了全部生效参数）、媒体大致类型（动画 / 实拍 / 广播剧，多长）
- **日志**：`~/Library/Application Support/KikuSub/outputs/logs/` 下的 `kikusub.log` 与 `main.log` 末尾片段；设置页的「复制诊断信息」会把版本、目录、引擎状态与最近日志打包好
- **样本**：不要上传整部片源。截取 5–10 秒能复现问题的片段即可
- **界面截图**：出现在 README 里会被公开，请先打码本机路径与片源名

## 开发环境

```bash
git clone https://github.com/Alansws/KikuSub.git
cd KikuSub

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt      # pytest / ruff

cd desktop && npm install && npm run build && cd ..
```

启动开发版：

```bash
cd desktop && npx electron .
```

> 某些 Electron 宿主（例如 WorkBuddy）会在 shell 里留下 `ELECTRON_RUN_AS_NODE=1`，它会让 Electron 退化成纯 Node。启动前清掉：
> `env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS npx electron .`

只想调接口时，sidecar 可以单独跑：

```bash
source .venv/bin/activate
python -m server --port 0
```

界面不依赖模型就能启动，权重只在第一次真正转写时加载。改界面、改波形交互、改字幕格式这类工作，不需要跑完整转写；`KIKUSUB_DEV_SEED` 可以把「媒体 + 字幕」直接灌进核对屏（见 `desktop/README.md`）。

## 代码结构

| 路径 | 改动入口 |
| --- | --- |
| `desktop/main/` | Electron 主进程：窗口、菜单、sidecar 生命周期、首次启动、退出清理、密钥存储、技能安装 |
| `desktop/renderer/src/` | Svelte 5 渲染层：`views/` 是四个工作区 + AI 优化台 + 设置，`lib/store.svelte.ts` 是状态与动作 |
| `server/` | FastAPI 服务层：`/api/*`、`/media/*`、`/ws/jobs/*`；路由按领域拆在 `routes_*.py` |
| `core/` | 算法内核（无 UI 依赖）：VAD、引擎、断句、覆盖率、提案、翻译、设置、日志 |
| `core/ai_proposal.py` | 提案契约：digest、结构校验、`apply_polish()`。**前端不得自己算 digest 或另写校验** |

旧 Gradio 界面（`app.py` / `static/`）已移出仓库，归档在标签 `v0.9-gradio` 与本机 `~/Downloads/kikusub_gardio`；本仓库只维护桌面端。

更细的约束（哪些实现绝对不能改、为什么）写在 [AGENTS.md](AGENTS.md) 与 [AI 优化与翻译开发文档](docs/AI优化与翻译-开发文档-2026-11.md)。

## 改动约定

以下几条是这个项目里踩过坑的地方，改动时请留意。

**提案层是唯一交接格式**
AI 结果只有一种形态：`{i, text}` 的提案文件，不含时间戳。任何把时间码塞进模型载荷、或从提案读时间码的实现都算破坏契约。新增入口（软件内、外部 agent、手动粘贴）必须复用 `core/ai_proposal.py` 的校验。

**翻译是平行轨**
译文永远不写进 `review_cues.text`，它有自己的 `Session.translations[lang]` 与撤销栈。双语只有一份构造实现：`core/i18n.bilingual_cues()`。

**新增调参项**
在 `core/engines.py` 注册引擎，在 `server` 侧暴露参数；参数键必须以引擎名开头（`whisper.` / `qwen.`）。新增引擎还要在 `core/pipeline.py` 注册推理对象并提供 `ensure_model(progress_cb)`。

**预设兼容**
`presets.json` 属于用户数据，不是配置模板。新增字段要有默认值兜底（`core/presets.py` 的 `_normalize` 负责），已有预设的键名不要重命名。删掉一个参数时，旧文件里残留的键应被忽略而不是报错。

**核对台状态**
核对基线与会话里的转写结果是两份独立状态。任何修改核对轴的操作都要压一次历史，否则撤销链会断；整块拖动必须一次压栈。

**桌面端专属**
主进程与渲染层通过 preload 的窄接口通信，不要为了图快开 `nodeIntegration`。密钥只走 `X-AI-Key` 请求头，服务层不读不写不记；日志里不能出现 Key、token、完整音视频内容。

**文案**
界面文案目前是中文。改了用户可见的行为，请同步更新 `README.md` 与 `README_EN.md`。

## 测试与检查

提交前至少跑一遍：

```bash
source .venv/bin/activate
pytest -q
ruff check .

cd desktop && npm run test:main
```

- Python 用例覆盖内核、服务层、AI 提案与译文轨；不涉及推理的用例不需要模型
- `npm run test:main` 覆盖退出清理、密钥加解密、技能安装与模板导入检查
- 通了界面才能确认的改动（拖动、缩放、跟随、双语行高）请附截图或录屏，`desktop/README.md` 里有自截图脚本

## 提交与 PR

Commit 前缀用 Conventional Commits 风格：

```
feat: support VTT output with line breaks
fix: keep partial cues when the job is cancelled mid-segment
perf: reduce waveform peak extraction for 2h+ files
docs: clarify transformers version requirement
```

PR 描述里写清三件事：改了什么、为什么改、怎么验证（有截图或录屏更好）。一次 PR 只做一件事，方便 review 也方便回滚。

## 不要提交的内容

- `models/`、`outputs/`、`*.autosave_draft.srt`、`*.progress.json` 等运行产物（`.gitignore` 已覆盖）
- `settings.json`、`preferences.json`、`.ai-key` 等本机配置与密钥（同样已忽略；**永远不要**为了“方便复现”提交它们）
- 受版权保护的片源、字幕文件或截图
- 与本机环境绑定的绝对路径

## 许可证

提交代码即表示同意以本仓库的 [MIT License](LICENSE) 发布。模型权重不在该许可范围内，请勿把权重文件提交到仓库。
