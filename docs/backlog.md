# 待办（唯一入口）

> **本项目所有"还没做的事"只写在这里。** 不要在会话里口头答应、也不要只写进某次 sprint 记录——
> 下一个会话读不到的东西等于不存在。方法论那篇（`docs/contracts/engineering-practice.md` §5）
> 只留三条与方法论直接相关的说明，具体条目以本文件为准。

## 怎么用

1. **新增**：发现的问题、想做的功能，写进对应优先级，一行一条；
2. **必须写验收**：没有验收标准的条目做完也无法判断完成，等于没做；
3. **完成**：移到最下面「已完成」，写 commit hash 和一句结果，**不要直接删**；
4. **优先级**：`P0` 会咬人（数据/发版/用户能用）→ `P1` 结构缺口（现在不做以后更贵）→ `P2` 存量债（能做则做）。
5. 改这张表本身**不需要**跑全量测试，跑 `pytest -q tests/test_docs_health.py` 就够。

---

## P1：结构缺口

| # | 项 | 出处 / 为什么 | 验收 |
| --- | --- | --- | --- |
| 1 | **环境钉版本**：加 `.python-version`（3.12）与 `desktop/package.json` 的 `engines.node`；把"venv 在工作区根 `../.venv`"写进 CONTRIBUTING | 审计 P1-3：本机 `python3` 是 3.14、CI 是 3.12，已经分叉（`server/__pycache__` 有 cpython-314 产物） | 新 clone 后按文档操作，`python3 -m pytest` 不会用到错解释器；CI 与本地版本一致 |
| 2 | **svelte-check 清零并进 CI**：修掉 10 个存量类型错误 | 审计 P1-1；基线冻结在 `desktop/test/svelte-check-baseline.json` | `npm run check:svelte` 报 0 错，且成为 CI 的一步 |
| 3 | **`popIn` 未定义**（`QaPanel.svelte:398`）：`in:popIn` 指向不存在的函数，编译后是全局查找，质检浮窗的进场动画是死的 | 2026-11-13 接入 svelte-check 时发现；用户确认"先不用修" | 选定一种动画（缩放/淡入/去掉指令）并手点验证浮窗开合 |
| 4 | **本页与代码的对账**：`tests/test_docs_health.py` 只覆盖文档结构与链接，不覆盖"契约里的数字/常量 vs 代码" | 审计 P1-5 | 至少一条对账（例如 `HISTORY_LIMIT=50` 与契约里的"50 步"）能在不一致时红 |
| 5 | **Anime Whisper 逐字对齐**：已做通用对齐层（`core/align_layer.py`，借 Qwen 的 acoustic-only CTC 头 + 人工文本）。实测单句段起点 p90 320ms / 终点 p90 477ms（去掉人工提前/停留的系统性偏移后），比原来的字符比例分配（p90 1.35s）好 4 倍，但**仍未达到 ±150ms**，所以只作为可选层 `whisper.use_ctc_alignment`（默认关，多常驻一份 Qwen 权重 5.1GB）；300s 窗口实测 CER 5.96% → 5.30%、起点 p90 0.934s → 0.745s、字幕时长中位 3.48s → 2.13s（人工 2.46s）
| 6 | **日语引擎优化路线**：[docs/日语引擎优化路线-2026-11.md](日语引擎优化路线-2026-11.md)。**P0-2 评测台已入库**（`tools/eval/`：`run_clip.py` / `ab_onset.py` / `probe_window.py` / `baseline.json`）→ **P0-1 已完成：qwen 句首提前默认 400 ms**（Test 二 CER 13.42%→11.47%、句首缺字 5→1；whisper 实测 CER +1.61pt，**不启用**，记为负结果）→ 再开 P0-3 置信度（先特征诊断）；P1 = 第二引擎按需复核 / ForcedAligner spike / 专名词表 | 2026-11 两片实测：9 个句首缺字样本扩窗直送全部恢复；两引擎错误互补；`mean_logprob` 已算但未接质检 | 按文档 §4 各项验收；S1 结束先交 A/B scorecard，再决定后续。**注意**：评测数字只在同一解释器内可比（`.venv` 与 anaconda 的 silero-vad 5.1/6.2 不同，同片 CER 可差 2pt），卡片已记 `env` 指纹 |

## P2：存量债（能做则做）

| # | 项 | 出处 | 验收 |
| --- | --- | --- | --- |
| 1 | 布局语义块合并：`.actions` 6 份、`.empty` 6 份、`.sec-head` 3 份、`.sec` 3 份 | `desktop/test/style-baseline.json` | 每合并一处就把基线数字调小，最终到 1。**⏸ 暂缓（2026-11-13）：动正在跑的界面，需单独一轮 + 截图 PSNR + 手点** |
| 2 | 主题色裸值 → 令牌：`ExportView.svelte:1029` `#8fa6ff`、`:1281` `#14161c`，以及 `themes.ts` 的 swatch 与 `app.css` 双写 | 审计 P2-3 | `style-drift.test.cjs` 增加"组件内不得出现 hex"规则并绿。**⏸ 暂缓（2026-11-13）：同上** |
| 3 | 大文件：`store.svelte.ts` 3933 行、`ReviewView.svelte` 3933 行（`SettingsView.svelte` 2056、`main.cjs` 1570） | engineering-practice §5 | **不做一次性大重构**（动正在跑的核对台，风险高）。改成"随功能抽"：`tests/test_big_file_budget.py` 冻结行数，只能变短——加功能前先把这次要用的纯逻辑抽到 `lib/`。`SettingsView` / `main.cjs` 暂不设预算，等它们真被改到再说 |
| 4 | 机械化测试清理：81 个单断言用例抽检过，多数合理 | 审计 P2-… | 扫一遍删掉"删了没人疼"的用例 |

---

## 明确不做（不是待办，别反复提）

| 项 | 为什么不做 |
| --- | --- |
| 本地 CHANGELOG | Release notes 是唯一对外日志，两处写同一个事实必然漂移（`docs/release.md`） |
| 云端更新配置 + 秒级回滚 | 本项目 DMG 手动分发、没有 autoUpdater；回滚口径见 `docs/release.md` §6 |
| 多模型互相 review | 固定单一模型开发；替代方案是 `docs/review.md` 的自审清单 + 三个补偿动作 |
| 手工整理仓库 md 表格对齐、去 Obsidian frontmatter | 笔记工具会重新写回；已接受为约定，巡检反而可以用 `updated` 判断文档年龄 |

---

## 已完成

| 日期 | 项 | 提交 |
| --- | --- | --- |
| 2026-11-13 | FireRed 原生接 FireRedPunc 标点恢复（ONNX 162 MB，随引擎下载到 `punc/`）；无句读时在切字幕前补标点，中文分句加 soft-max（标点只晚几个字时把当前条放长，不硬切词） | 见 `git log` |
| 2026-11-13 | 新增两个可选装中文引擎：SenseVoice-Small（230 MB，token 时间戳）与 FireRedASR2-AED（1.2 GB，无时间戳按字分时）；走 sherpa-onnx / ONNX / CPU，默认停用、权重按需下载；注册表 + `family` 分派让未知引擎不再静默退回 Whisper | 见 `git log` |
| 2026-11-13 | 导入页「最近打开」支持图标画廊（列表 / 图标切换、偏好持久化、封面悬停浮层）；顺带修掉冷启动时缩略图请求早于握手、401 后永久消失的 bug | 见 `git log` |
| 2026-11-13 | 归档过期 AI 开发文档、契约补齐 D-1～D-6 与 A1–A8、清理工作区 | `1767bb4` |
| 2026-11-13 | 发版四步规范 + `preflight.sh` + CI `release-tag` + 分支模型（`main` 主线） | `cd772d5` |
| 2026-11-13 | 主链路 e2e、`npm run check`（tsc）、svelte-check 基线、CI `desktop` job、`review.md` + PR 模板 | `2ba5712` `5fd25b0` `7132b41` |
| 2026-11-13 | 补 `svelte.config.js`（此前 svelte-check 根本没在查），基线 33 → 10 | `7b3b1a9` |
| 2026-11-13 | 文档巡检测试、待办单一入口、方案模板、验证时机矩阵、pytest marker | 见 `git log` |
| 2026-11-13 | 删掉 5 个死导出（`tcSrt` / `endpoint` / `TtsVoice` / `aiFinalText` / `enabledEngines`——后两个各有一份**活的**内联实现） | 见 `git log` |
| 2026-11-13 | 静默截图当次产出进 gitignore（`docs/images/shots/current/`） | 见 `git log` |
| 2026-11-13 | 覆盖率报告：`tools/check/coverage.sh` + `pytest-cov`；当前 core+server 73%（不设门槛，见脚本头注释） | 见 `git log` |
