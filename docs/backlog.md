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
| 2 | **svelte-check 清零并进 CI**：修掉 6 个存量类型错误 | 审计 P1-1；基线冻结在 `desktop/test/svelte-check-baseline.json` | `npm run check:svelte` 报 0 错，且成为 CI 的一步 |
| 3 | **`popIn` 未定义**（`QaPanel.svelte:398`）：`in:popIn` 指向不存在的函数，编译后是全局查找，质检浮窗的进场动画是死的 | 2026-11-13 接入 svelte-check 时发现；用户确认"先不用修" | 选定一种动画（缩放/淡入/去掉指令）并手点验证浮窗开合 |
| 4 | **本页与代码的对账**：`tests/test_docs_health.py` 只覆盖文档结构与链接，不覆盖"契约里的数字/常量 vs 代码" | 审计 P1-5 | 至少一条对账（例如 `HISTORY_LIMIT=50` 与契约里的"50 步"）能在不一致时红 |
| 5 | **Anime Whisper 逐字对齐**：已做通用对齐层（`core/align_layer.py`，借 Qwen 的 acoustic-only CTC 头 + 人工文本）。实测单句段起点 p90 320ms / 终点 p90 477ms（去掉人工提前/停留的系统性偏移后），比原来的字符比例分配（p90 1.35s）好 4 倍，但**仍未达到 ±150ms**，所以只作为可选层 `whisper.use_ctc_alignment`（默认关，多常驻一份 Qwen 权重 5.1GB）；300s 窗口实测 CER 5.96% → 5.30%、起点 p90 0.934s → 0.745s、字幕时长中位 3.48s → 2.13s（人工 2.46s）
| 6 | **日语引擎优化路线**：[docs/日语引擎优化路线-2026-11.md](日语引擎优化路线-2026-11.md)。**P0-2 评测台已入库**（`tools/eval/`：`run_clip.py` / `ab_onset.py` / `probe_window.py` / `baseline.json`）→ **P0-1 已完成：qwen 句首提前默认 400 ms**（Test 二 CER 13.42%→11.47%、句首缺字 5→1；whisper 实测 CER +1.61pt，**不启用**，记为负结果）→ P0-3a 已诊断（AUC <0.75，不上线）→ **P1-1 段一/段二已完成**（`kind="compare"` 只回文本；核对台「当前条目」与质检条目可发起复核），段三（多选批量）已完成；P1 = 第二引擎按需复核 / ForcedAligner spike / 专名词表 | 2026-11 两片实测：9 个句首缺字样本扩窗直送全部恢复；两引擎错误互补；`mean_logprob` 已算但未接质检 | 按文档 §4 各项验收；S1 结束先交 A/B scorecard，再决定后续。**注意**：评测数字只在同一解释器内可比（`.venv` 与 anaconda 的 silero-vad 5.1/6.2 不同，同片 CER 可差 2pt），卡片已记 `env` 指纹 |

## P2：存量债（能做则做）

| # | 项 | 出处 | 验收 |
| --- | --- | --- | --- |
| 1 | 布局语义块合并：`.actions` 6 份、`.empty` 6 份、`.sec-head` 3 份、`.sec` 3 份 | `desktop/test/style-baseline.json` | 每合并一处就把基线数字调小，最终到 1。**⏸ 暂缓（2026-11-13）：动正在跑的界面，需单独一轮 + 截图 PSNR + 手点** |
| 2 | 主题色裸值 → 令牌：`ExportView.svelte:1029` `#8fa6ff`、`:1281` `#14161c`，以及 `themes.ts` 的 swatch 与 `app.css` 双写 | 审计 P2-3 | `style-drift.test.cjs` 增加"组件内不得出现 hex"规则并绿。**⏸ 暂缓（2026-11-13）：同上** |
| 3 | 大文件：`store.svelte.ts` 3315 行、`ReviewView.svelte` 3877 行（`SettingsView.svelte` 149、`main.cjs` 1581） | engineering-practice §5 | **不做一次性大重构**（动正在跑的核对台，风险高）。改成"随功能抽"：`tests/test_big_file_budget.py` 冻结行数，只能变短——加功能前先把这次要用的纯逻辑抽到 `lib/`。`SettingsView` 已拆到 149 行、不再需要预算；`main.cjs` 暂不设预算，等它真被改到再说 |
| 4 | 机械化测试清理：81 个单断言用例抽检过，多数合理 | 审计 P2-… | 扫一遍删掉"删了没人疼"的用例 |
| 5 | **中文术语表 / ITN 后处理**：FireRed 把 eSIM 写成 `E SIM`、`10月3号` 写成 `十月三号`；SenseVoice 把 eSIM 听成「一信」。这是词表问题，不是参数问题（[标定文档](转录标定-中文-2026-11.md) §2） | 2026-11-14 中文引擎标定：剩余错误集中在专名与数字写法 | 用户可编辑的热词表（术语 → 规范写法）生效后，同一素材的 CER 再降 ≥1pt，且不影响未被映射的句子；与日语侧 P1-3 词表共用一套界面 |
| 6 | **润色页分段与断句重排统一到同一套 `reshapePlan` 模型**（2026-11-15 顺查结论：**不是**同一类 bug，但同一机制） | 断句重排修复时的顺查 | 润色页**没有**「组件重建清空进度」问题：`resetAi()` 全仓库没有调用点，`ai.segments` / `ai.filled` / `ai.pasteText` 都在模块级 `$state`；`planAiSegments()` 每次 `cuesRevision` 变化都重算，但润色是 1:1 车道（`apply_polish()` 逐条保条数与时间轴），重算结果逐段相同，所以安全。**残留盲区**：在核对台做结构编辑（删 / 并 / 插）后回来，分段会变成另一套，`ai.filled` 的旧 key 变孤儿 →「已回填 x/y」静默归零；此时按旧段号粘回的稿子会被 422 拦下（条数校验），**不会**错位覆盖。要做的是：段身份换成原稿起条号 + 已开工不静默重切 + 失效横幅，与断句重排共用一个模块 |

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
| 2026-11-15 | **断句重排分段计划冻结修复（P0+P1）**：用户报障「双源 A+B 覆盖两段后点一下底稿『单源』再切回双源，4 段变 3 段、第三段草稿无处可粘」。根因：冻结键里塞了 `source`（还有 `dual.count`），覆盖过两段后重切用的是已改过的表；副因：视图挂载即 `resetReshape()`（切视图重建组件），以及 `applied` 用展示区间 `"from-to"` 当 key。修法：冻结键只认「媒体 + 做法 + 第二版身份 + 有没有稿」；已开工只挂失效横幅不重切；段身份改原稿起条号；⌘Z 撤掉自家那次覆盖时同步回退标记；`cuesRevision` 侦测外部改动；计划快照可恢复；进页只在换媒体时重置。纯函数抽到 `lib/reshapePlan.ts`（`desktop/test/reshapePlan.test.mjs` 12 例）。端到端复现与验收：新增 `tools/shots/verify_reshape_flow.mjs`（`--screenshot` 静默路径，501+516 条真实界面，14+10 条断言；旧构建 4→3 复现，新构建段轨 / 勾选 / ⌘Z / 失效横幅 / 恢复按钮可见性全通过）。契约：`contracts/ai-proposal.md` §3.7.6 | 见 `git log` |
| 2026-11-15 | **AI 三页两处手感修复**：润色双源的分段轨点击只显示该段字幕（表格 / 复制 / 粘贴同一范围，解析后停在本段、不再自动跳段、换段清空粘贴框）；双引擎复核点时间码去核对台后，按 ⌘4 / 侧栏回来恢复滚动位置并高亮刚点的那一行（`lib/scrollMemory.ts`）。契约：`contracts/ai-proposal.md` §3.7.3 | 见 `git log` |
| 2026-11-15 | **设置页重构**：`SettingsView.svelte` 2032 行 → 149 行的页签骨架，四页签（引擎与模型 / 外观与朗读 / AI 与技能 / 环境与诊断）拆到 `views/settings/`，纯逻辑在 `lib/settings/`；三主题 × 四页签 + 680×900 取证矩阵。方案与验收：[sprints/2026-11-settings-redesign/](sprints/2026-11-settings-redesign/) | 见 `git log` |
| 2026-11-15 | **断句重排（整份换稿）车道**：外部模型给完整 SRT，按原稿索引区间整段替换，条数/切分/时间码/文字均可变；体检只标注不拦路，条数腰斩二次确认，digest 守卫。契约：`contracts/ai-proposal.md` §3.7.6 | 见 `git log` |
| 2026-11-15 | **核对台批量清理标点**：`lib/punctuation.ts` 纯规则（零 import）+ 浮层三入口（顶栏 / `⌘⇧L` / 编辑菜单），只清原文轨、整轨一步历史。契约：`contracts/review-console.md` §3.4.4 | 见 `git log` |
| 2026-11-15 | **整片 / 区间人声分离**：`separation_range()` 统一算窗口（只填一端取片头/片尾、长片自动分段），区间「替换选区」补请求层校验（缺起点 422，不再误清整表）。契约：`contracts/review-console.md` §3.4（结果处理三档） | 见 `git log` |
| 2026-11-15 | **双引擎复核与工作流重构 S1–S4**（原 P1-7）：删批量复核入口、第二版本进第二列做 diff、双源 AI 润色、导航按工作流重排。记录：[双引擎复核与工作流-需求-2026-11.md](双引擎复核与工作流-需求-2026-11.md) | 见 `git log` |
| 2026-11-15 | svelte-check 存量类型错误从 10 降到 6（基线文件同步下调） | 见 `git log` |
| 2026-11-14 | 中文引擎（SenseVoice / FireRed）首轮标定：修 sherpa 相对时间戳当绝对时间（SenseVoice CER 69.41%→6.80%）、`_extend_to_marks` 双重 start（39 字/5.8s 条）、空格切点与 `E / SIM` 劈词；新增能量对齐（FireRed 边界 F1 0.511→0.543）与 jieba 词边界兜底（词内切点 3.7%→1.0%）；默认参数 sensevoice 10s/14 字、firered 20s/14 字。记录：[转录标定-中文-2026-11.md](转录标定-中文-2026-11.md) | 见 `git log` |
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
