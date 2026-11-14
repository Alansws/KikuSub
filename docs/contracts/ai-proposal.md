# AI 提案、润色与翻译（M1–M4）

> 从 `AGENTS.md` 拆出（2026-11-13）。提案契约、模型调用、译文平行轨、Agent 技能。
> **本文件是 AI 这条线的唯一现行契约**；总索引见 [AGENTS.md](../../AGENTS.md)。
> 原始的里程碑拆解与逐阶段执行记录已归档在
> [docs/archive/AI优化与翻译-开发文档-2026-11.md](../archive/AI优化与翻译-开发文档-2026-11.md)
> （写于动工前，**禁止照它改代码**，只在需要"为什么当初这么定"时读它）。

---

## 0. 冻结决定与验收（改 AI 链路前先过这两张表）

### 0.1 冻结决定 D-1～D-6

改其中任何一条 = 先改本节，再改代码。

| 编号 | 决定 | 理由 / 落点 |
| --- | --- | --- |
| **D-1** | 时间戳由**结构**保证，不靠提示词：模型只收发 `{i, text}`，`start/end` 一律取自当前 `review_cues` | 「应用前后时间码逐条精确相等」的唯一可靠保证（见下面 §3.7 第一条）。**双源例外说明**：双源润色会把带时间戳的 A/B 作为**对齐参考**放进提示词，但输出与应用仍只认 `{i, text}` 和 A 的 cue。 |
| **D-2** | 一个提案层、两个生成入口（in-app / skill），前端**不关心**提案是谁生成的 | 界面不必为来源开分支 |
| **D-3** | 译文存平行轨 `Session.translations[lang]`，**永不**写进 `review_cues.text` | 见 §3.7.2 |
| **D-4** | 双语两种排版**不能混用**：交付文件每语种一条（`bilingual_entries`），烧录/叠加层一条两行（`bilingual_cues`） | 2026-11 修订；用户报障过重新导入被 `nowrap` 压成一行 |
| **D-5** | 应用 = **整批一次**历史（27 处改动也只压一次栈） | 逐条压栈会让人没法用 |
| **D-6** | 模型输出永远"列满本块全部条目"，不做"只返回改动项" | 校验规则统一、diff 能显示"AI 没动的条" |

### 0.2 验收断言 A1–A8（改 AI 链路后逐条过）

| 编号 | 断言 | 验证 |
| --- | --- | --- |
| **A1** | 应用前后 `(start, end)` 逐条**浮点精确相等** | `tests/test_ai_proposal.py` |
| **A2** | 源指纹不符 → 409，字幕零变化 | `tests/test_server_ai.py` |
| **A3** | 条数/序号不符 → 422，字幕零变化 | `tests/test_server_ai.py` |
| **A4** | 应用 = **一次** undo | pytest + 手动 ⌘Z |
| **A5** | 双语导出 = 每语种一条单行 cue（2n 条、时间码相同），重新导入仍是 2n 条、不含 `\n` | `tests/test_i18n.py` |
| **A6** | 原文/译文/双语三态切换，画面字幕行数正确 | 手动 |
| **A7** | 退出清理不把 `*.{lang}.srt` / `*.bilingual.srt` 当碎片 | `desktop/test/files.test.cjs` |
| **A8** | API Key 不出现在任何日志、`settings.json`、WS 快照里 | 人工 grep 日志 + 代码审查 |
| **A9** | 双源提案应用后 `(start, end)` 仍逐条浮点精确相等 | `tests/test_ai_dual.py` |
| **A10** | 双源提案只改 B 的 digest → 409，字幕零变化 | `tests/test_ai_dual.py` |

---

### 3.7 AI 提案、润色与翻译（2026-11 M1，后续里程碑会扩展）

- **时间码由结构保证，不靠提示词**：提案里只有 `{i, text}`，**没有时间戳**。应用时
  `start/end` 一律取自当前 `review_cues`，提案里的任何时间字段都不参与。任何把时间码塞进
  模型载荷、或从提案读时间码的实现都算破坏契约（D-1）。
- **唯一实现**：`core/ai_proposal.py` 负责 digest、结构校验与 `apply_polish()`。
  前端**不得**自己算 digest，也**不得**另写一份校验；`/api/ai/apply` 与将来的生成任务
  必须调同一个 `validate_proposal()`。
- **应用 = 整批一次历史**：走一次 `Session.replace_review()`，`⌘Z` 一次全退回。
  **禁止**逐条改（27 处改动压 27 次栈会让人没法用）。
- **失败不动字幕**：digest 不符 → 409，结构不符 → 422，`session.review_cues` 一个字节都不改。
- **文件位置**：`{output_dir}/{stem}.ai-polish.json`、`{stem}.{lang}.ai-translate.json`。
  外部 agent 带来的提案走 `POST /api/ai/proposal/import`（校验通过才落到标准位置），
  原生对话框是 `window.kikusub.pickProposal()` —— 不要复用 `pickSubtitle`（只认 srt/vtt）。
- **`AiView` 只认提案**，不关心是 in-app 还是外部 skill 生成的：这是"一个提案层、两个入口"的
  全部意义（D-2）。改界面时不要为某个来源开分支。
- 验收脚本：`python tools/make_fake_proposal.py <srt>` 造一份假提案；
  用例在 `tests/test_ai_proposal.py` / `tests/test_server_ai.py`。
- 译文**不写进** `review_cues.text`（D-3），它将来是平行轨；`/api/ai/apply` 只处理
  `kind=polish`，翻译提案会被 422 拒绝。

#### 3.7.1 调用模型（2026-11 M2）

- 客户端在 `core/ai_client.py`：**纯 urllib，不引 openai SDK**（sidecar 是打包产物，
  少一个依赖少一份体积）。`chat_json()` 只管传输与 JSON 解析，分块在 `core/ai_polish.py`。
- **密钥只走请求头 `X-AI-Key`**：渲染进程从 `window.kikusub.aiKey.get()`（主进程解出
  明文）取出来，随请求发一次。服务层**不读不写不记**；`settings.json` 里没有也不要加
  `ai_api_key` 字段。日志只允许 host / model / 状态码 / 耗时。
- **密钥存储不要用 `safeStorage`**（2026-11-11 定稿，三方案对比见归档件 `docs/archive/AI优化与翻译-开发文档-2026-11.md` §11.4）：keychain 条目的
  ACL 认的是代码签名要求，而本项目以 DMG 分发、ad-hoc 签名，**每次发版 cdhash 都变，
  用户升级后 Key 全部失效**，且没有 Developer ID 无从修复。现在用
  `desktop/main/aikey.cjs`：32 字节主密钥存 `{dataDir}/.ai-key`（0600），
  `preferences.json` 里只放 `aik1:` 密文。
  改这块时守住三条：**0600 权限**、**旧 `v10` blob 要能识别并报 `broken`**、
  **绝不把明文写进任何文件或日志**。用例：`node --test desktop/test/aikey.test.cjs`。
- 只有将来改用 **Developer ID 签名 + 公证** 发布时，才值得切回 `safeStorage`；
  切之前先读归档件 `docs/archive/AI优化与翻译-开发文档-2026-11.md` §11.4 的三方案对比。
- 生成走 `JobManager.start_ai_polish()`（与转写共用单槽），进度复用 `/ws/jobs/{id}`。
  `ai_client` 里带 key 的 `AiConfig` **只能作为线程参数**，绝不能塞进 `JobRecord`。
- 结构不合规（缺条 / 非 JSON）只**重问一次**（附 `STRICT_HINT`）；仍失败就整份放弃，
  绝不产出"半份提案"。改动率超 40% 会出现在 `warnings` 里，界面据此提示。
- 取消只能落在**分块之间**（urllib 阻塞不可中断），这是已知限制，不要假装能秒停。

#### 3.7.2 译文平行轨（2026-11 M3）

- 译文**永远不写进** `review_cues.text`（D-3）。它存在 `Session.translations[lang]`，
  与 `review_cues` **逐条对齐**，并带一份 `base`（生成时的原文快照）用来算过期。
- 写轨只有两条路：`POST /api/translations`（应用一整版）与草稿恢复。两者都**只动轨**。
  译文编辑现在与字幕共用**统一工作区历史**（`set_translation` / `patch_translation` /
  `drop_translation` / 整轨替换都 `_record`），⌘Z 会按时间退回到对应状态。
  `translation_undo[lang]` 仅保留给检查器里的「撤销译文」按钮（一次退回上一版），
  不再是全局 ⌘Z 的存储。
- 条数必须相等、`i` 必须连续、digest 必须匹配；**不通过就整批拒绝**，
  绝不落一份对不齐的轨（`test_server_translations.py`）。
- 双语分两种排版，**不能混用**（D-4，2026-11 修订）：
  - `core/i18n.bilingual_cues()` = **一条 cue 两行**，只给画面叠加层与烧录硬字幕用
    （ffmpeg 字幕精灵按 cue 取块，一条两行才能一起排版）。
  - `core/i18n.bilingual_entries()` = **每语种一条独立 cue**、共享同一时间轴，给
    `.bilingual.srt/.vtt` 交付文件用。官方双语 SRT（如诸神字幕组）就是这个写法；
    重新导入核对台时每条都是单行，不会被 `white-space:nowrap` 挤成「日文 中文」一行。
  - 字幕文件导出（`/api/cues/export`、成片附带 SRT）走 `bilingual_entries()`；
    烧录/叠加层走 `bilingual_cues()`。两处各写一遍同样禁止。
- 旧版双语文件（同一条 cue 两行）导入时按 `.bilingual.srt/.vtt` 文件名拆开：
  `core/subtitles.split_multiline_cues()`；普通 SRT 的多行 cue 不拆（只影响显示，
  表格用「 / 」连接、画面叠加层按 `\n` 分行）。
- 三态导出：`POST /api/cues/export` 的 `track`（`source|target|both`）+ `lang`；
  文件名后缀 `.lang` / `.bilingual`。**新增后缀必须同步 `desktop/main/files.cjs`
  的 `TRANSLATION_SUFFIX`**，否则退出清理会把交付物当碎片默认删除。
- 核对台三态与双语行高：`ReviewView` 的行高是 `$derived(app.track === 'both' ? ROW_H*2 : ROW_H)`，
  **固定双行高**；禁止改用自动测量（会和虚拟滚动的绝对定位打架）。
- 暂存必须连译文一起写（`{stem}.autosave_draft.i18n.json`）；恢复时条数不符的轨直接丢弃。
- **结构性编辑与译文对齐（2026-11 修复）**：删一句原文必须同时删掉 `translations[lang].texts/base`
  同下标条目；插入补空占位；切割复制一条；合并拼接。`Session.delete_cue/delete_cues/insert_cue/
  split_cue/merge_cues` 是唯一入口，路由不要自己改两张表。
- **人工改译文 = 已同步**：`Session.patch_translation` 把 `base[index]` 更新成当前原文，
  「这一条的原文改过了，译文可能需要同步」才会随这次保存消失。双语下同时改原文和译文时，
  前端必须**先提交原文、再提交译文**，否则 base 会落在旧原文上，提示永远清不掉。
- **换片清空**：`POST /api/session/bind` 检测到 media id 变化时调用 `reset_for_media()`，清空
  字幕、译文、历史与来源；前端 `openMedia` 随后 `loadTranslations()`。这是「导入新视频后
  上一部片的译文永远占着、软件不可用」的修复。核对台右栏也提供「删除译文」。
- **切回三态要定位**：`ReviewView` 监听 `app.track/trackLang`，变化时把 `play.selected` 落到
  当前时间的字幕并 `revealRow()`；双语是双行高，必须等 DOM 更新后再滚。
- **原文轨 / 译文轨分别导入（2026-11 新增）**：原文走 `POST /api/cues/import`；译文走
  `POST /api/translations/import`（`path` + `lang`），只换 `translations[lang]`，时间轴仍取自
  当前原文。条数相同时按顺序对齐；条数不同时用 `core.subtitles.align_translation_texts()`
  按时间重叠挂回（「仅译文」导出会跳过空译文，天然少条），挂不上就整批 422。
  删除原文用 `POST /api/cues/clear`（连同无法再对齐的译文轨，一步历史）；删除译文仍走
  `DELETE /api/translations/{lang}`。转写页两张文件卡、核对台「⋯」与检查器译文区都复用
  这三个入口，不要再各写一套导入逻辑。
#### 3.7.3 双源润色（2026-11 新增）

- **提案契约扩展但保持向后兼容**：双源润色时 `source` 额外带 `count_b` 与
  `digest_b`；单源提案**没有**这两个字段，照旧只校验 A。`build_proposal(texts_b=…)`
  是唯一构造入口，`validate_proposal(data, texts, texts_b=None)` 是唯一校验入口。
- **校验顺序**：结构（422）优先，其次 A digest（409），最后 B digest（409）。
  带 `digest_b` 的提案在「当前没有第二版」或「B 文本已变」时一律 409，
  `review_cues` 一个字节都不改。**B 的条数不要求等于 A**（两个引擎断句本来就可能
  不同），只校验 `digest_b`；提案的 `items` 条数仍然必须严格等于 A。
- **应用仍走 `apply_polish()`**：只按 `{i, after}` 覆盖 A 的文本，时间码取自 A。
  三种采用粒度（逐条 / 全部差异 / 整列）都只是 `accept` 子集不同，**一次历史**。
- **提示词分类**：`core/prompts.py` 分 `polish_single` / `polish_dual` / `translate`；
  旧 `prompts.json` 的模板没有 `category` 时归入 `translate`。分类各自记住选中项
  （`selected` / `selected_polish_single` / `selected_polish_dual`）。
- **应用内分块（Q9）**：A 块用全局序号 + 时间戳；B 只取 `[t0-2s, t1+2s]` 内
  的上下文，避免整片两次 fork 造成 token 爆炸。
- **外部复制 / 粘贴分段**：`GET /api/ai/prompt` 支持 `mode/from_index/to_index`；
  `POST /api/ai/from-srt` 支持同一区间回填。解析仍只按顺序取文本，序号可以是全局
  `k..m` 或本段相对 `1..X`；条数不符整段拒绝，文案必须给出
  「本段期望第 k–m 条（共 X 条），实际解析到 Y 条」。分段边界由
  `desktop/renderer/src/lib/aiSegments.ts` 的纯函数在 A/B 静音间隙最大处选择。
- **不变**：翻译仍只吃定稿后的 A 一列；第二版不进 50 步历史；随包技能不需要重写。

#### 3.7.4 Agent 技能（2026-11 M4）

- 技能包在 `desktop/resources/skill/kikusub-subtitle/`，装到 `~/.agents/skills/`（DSH 会扫描的
  用户级技能根）。`KIKUSUB_SKILL_ROOT` 可覆盖根目录，测试用它。
- **不要把目标根改回 `~/.claude/skills/`**：那是 Claude Code 的根，DSH 的 `skill-filesystem`
  只扫 `.dsh/skills` / `.agents/skills`（项目级）与 `~/.dsh/skills` / `~/.agents/skills`（用户级）。
  装错根的表现是目录都在、`SKILL.md` 也合法，但 `/` 菜单里没有这个技能。根目录的唯一实现是
  `desktop/main/skill.cjs` 的 `defaultTargetDir()`，`main.cjs` 只负责传 home。
- `SKILL.md` 里读 `references/paths.json` 优先用宿主给的技能目录，兜底只列 `.agents` / `.dsh`
  两处；不要再往文档和代码里加 `~/.claude`（本项目不面向 Claude Code）。
- **技能不碰字幕文件**：只读 SRT、写 `{output_dir}/{stem}.ai-polish.json` 或
  `{stem}.{lang}.ai-translate.json`。任何让 agent 直接改 SRT 的做法都是回退。
- `references/digest.md` 里有一个固定自测向量，`desktop/test/skill.test.cjs` 会校验它——
  改算法就同时改文档和用例，否则测试红。提案的机器可读 schema 在
  `references/proposal.schema.json`（外部 agent 与 `tools/make_fake_proposal.py` 都按它造件）。
- 安装器 `desktop/main/skill.cjs` 只用 fs（不引 electron），因此能被 `node --test` 覆盖；
  安装是"先删再拷"，`references/paths.json` 由渲染层传入的真实目录覆盖写入。
- 目标目录由**主进程**决定，不接受渲染层传进来的路径。

- **手动粘贴通道（2026-11 补充）**：`GET /api/ai/prompt` 组提示词（里面**带** SRT 与时间戳，
  为的是让模型逐条对齐），`POST /api/ai/from-srt` 解析回复时**只按顺序取文本，
  序号与时间戳全部丢弃**，时间轴仍用我们自己的 cue。条数不符整批拒绝（422）。
  改这块时不要把解析结果里的时间戳写回字幕——那会直接破坏 D-1。
- **粘贴结果必须能活过切页（2026-11 修复）**：`/api/ai/from-srt` 只返回提案、不落盘；
  前端解析成功后调用 `POST /api/ai/proposal` 把它写成标准提案文件，否则切到翻译页
  再回来时 `GET /api/ai/proposal` 会 409，页面被清空。应用时 `/api/ai/apply` 同时带上
  **内联 `proposal`**，不完全依赖磁盘上是否已有文件。手动粘贴的提案 `entry=manual`、
  `model=manual-paste`，没有逐条理由（`note` 一律为空，校验也不再刷「没有写理由」）。
