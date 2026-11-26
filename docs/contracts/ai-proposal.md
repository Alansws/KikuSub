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
| **A11** | 手动分批时复制 / 回填只含本批；润色条数不符仍 422，翻译严格开关关闭时按时间轴对齐 | `tests/test_translation_align.py`、`desktop/test/cueBatch.test.mjs` |
| **A12** | 断句重排局部替换只动本段，范围外尾部译文随条数平移；⌘Z 一次退回 | `tests/test_reshape.py` |
| **A13** | 补译只写显式下标：名单外的译文逐字节不变，`before` 不符 409 零写入，一步 ⌘Z 退整批 | `tests/test_ai_gap.py` |
| **A14** | 译文标点清理只改真正变过的条目 base，未改的「原文已改」标记保留；两轨一次提交一步撤销 | `desktop/test/punctuation.test.mjs`、`tools/shots/verify_punct_clean.mjs` |

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
- 写轨只有三条路：`POST /api/translations`（应用整版 / 局部应用）、
  `POST /api/translations/gap`（补译回填，见 §3.7.14）与草稿恢复。三条都**只动轨**；
  前两条走 `core.i18n.merge_translation_texts()` 合并——只写本次显式列出的下标，其余
  条目逐字节保留；草稿恢复是整轨写回。译文编辑与字幕共用**统一工作区历史**
  （`set_translation` / `patch_translation` / `drop_translation` / 整轨替换都 `_record`），
  ⌘Z 会按时间退回到对应状态。`translation_undo[lang]` 仅保留给检查器里的「撤销译文」
  按钮（一次退回上一版），不再是全局 ⌘Z 的存储。
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
- **2026-11-25：局部转写保轨 + 单句补译**：
  - 局部转写（`/api/jobs` 的 `apply=replace_range`）改走
    `Session.replace_review(keep_translations=True)`：条数变了也不丢轨。
    `core/i18n.remap_track()` 先按 `(start, end, text)` 整条配对，再按时间重叠 1:1
    配对（搬译文、保留旧 base），其余留空（待译）。整片 / 追加转写仍然整轨丢弃。
  - **空译文 = 待译，不算过期**：`stale_indices(cues, base, texts)` 跳过空文本，
    `track.pending` 单独计数。前端 `lib/translationStatus.ts` 是同一口径的本地实现。
  - `POST /api/ai/translate-cue {index, lang}`：**只回文本**，不落盘、不进历史、
    不改字幕。用 `_arbitrate_target()`（默认本机 LM Studio），材料只有前后各 4 条
    原文 + 邻居已有译文；提示词与 `{text, note}` 校验在 `core/ai_translate_cue.py`
    （失败带 `STRICT_HINT` 重问一次）。采纳由前端调既有
    `PATCH /api/translations/{lang}/{index}`。
  - 鉴权与 `/api/ai/arbitrate` 完全相同：覆盖地址时读 `X-AI-Arbitrate-Key`，否则
    `X-AI-Key`；`is_local_url` 放行无 Key 的本机服务。

#### 3.7.3 双源润色（2026-11 新增）

- **B 版来源不影响提案契约**：第二版可以由另一引擎整片转写产生，也可以由
  `POST /api/alt-review/import` 直接导入一份工作流里已做好的 SRT/VTT；两者是同一个
  `AltReview`（`source.kind` 区分 transcription / import），`digest_b` 只依赖 B 的文本。
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
- **分段轨是「换一段看」，不是状态徽章（2026-11-15 修复）**：点分段只画这一段的字幕，
  表格 / 复制提示词 / 粘贴回填是同一个范围——和断句重排页一致；段外的行既不在这轮
  回填里，也没有理由混在同一张表里（用户报障：点分段表格纹丝不动）。解析成功后
  **停在这一段**看 diff，不自动跳到下一段（跳走等于让刚回填的结果立刻消失）；换段要
  清空粘贴框，否则上一段的回复可能被贴进这一段。整片生成 / 技能 / 导入的提案按契约
  本来就覆盖 A 的全部条目，段轨状态直接视为「已有建议」；只有手动粘贴通道要逐段攒。
- **不变**：翻译仍只吃定稿后的 A 一列；第二版不进 50 步历史；随包技能不需要重写。

#### 3.7.3.1 双引擎复核的「对照范围」（2026-11-26 真机报障）

第 1、2 章字幕已在核对台，第 3 章用「两版一起 + 替换选区」跑完时，A 是**累积**的
（1–3 章 636 条、00:13–55:36），B 只有这一趟的区间（220 条、35:58–55:36）。旧口径
按整片对齐，于是前两章 430 条全变成红色「仅 A」、差异计数与侧栏徽标失真，
而右上角唯一的「整列覆盖」一按就把前两章丢光。

- **纯函数在 `core/dual_scope.py`**（无 IO / 无模型）：`cue_span` / `cues_in_window` /
  `is_partial_b` / `interval_chapters` / `match_chapter` / `default_focus` /
  `scope_options` / `resolve_focus` / `hidden_counts` / `replace_window` / `would_trim`。
  三个范围：`all`（整片）、`b`（B 自己的跨度）、`ch:<id>`（工程里的**区间章节**；
  时刻点没有跨度，不能当范围）。
- **智能默认**：`is_partial_b` 为真（B 的跨度没盖住 A，差 > 1s）时默认聚焦 B 所在区间；
  能匹配到覆盖率 ≥85%、两端不出章 +2s 的章节时**用章节名**（用户看到的是「章节三」，
  不是「35:58–55:31」）。B 盖住整片时默认仍是全片。
- **统计与徽标只算当前范围**：`GET /api/alt-review?scope=auto|all|b|ch:<id>` 先切片
  再对齐，`stats.a_count / b_count / badge` 都是范围口径；响应新增 `scope`
  （含 `options` / `hidden_a` / `hidden_b` / `would_trim` / `replace_mode` /
  `replace_count`）、`total_a`、`total_b`。**范围只影响对齐与统计**，`cues` 永远是整份 B
  （切范围不必重拉）。
- **下标必须指回全片**：`build_review(a_cues, b_cues, a_map=…, b_map=…)` 让
  `a_indices` / `b_indices` 仍是整份字幕的下标——「采用 B」与「回核对台定位」作用在
  全片第 N 条，错一位就会采纳到邻句上（`tests/test_dual_scope.py` 有断言）。
- **写回默认只替换当前范围**：`POST /api/alt-review/replace-primary` 的
  `mode="auto"` 给了 `start`/`end` 就按 `range`，否则 `all`。`range` 走
  `dual_scope.replace_window`：只换窗口内的 A，窗口外一条不动，`keep_translations=True`
  按位置搬移译文，仍然只压一步历史（⌘Z 一次整批退回）。`all` 在 B 只覆盖局部
  （`would_trim > 0`）时返回 **409**，必须 `confirm_trim=true` 才放行——这是
  「绝不允许误操作清空第 1、2 章」的最后防线，老客户端只发 `{}` 同样被拦。
- **界面**：`views/DualView.svelte` 顶部是「范围胶囊（B 所在区间 / 各章节 / 全片）+
  横幅」；文案由 `lib/dualScope.ts` 的纯函数生成（`scopeBanner` / `replaceLabel` /
  `replaceConfirmText`，12 条单测）。按钮文案分两档：范围对照是**「用 B 替换当前范围」**
  （纸白键 + 蓝铅笔图标，安全动作），只有 B 盖住整片才是「用 B 覆盖核对台」（朱红边）。
  二次确认必须写出「窗口外的 N 条（其它章节）一条不动」或「范围外还有 N 条会被丢掉」。
- **回归**：`tests/test_dual_scope.py`（17 条：636/220 现场、默认聚焦章节三、
  徽标不被前两章污染、下标回指、范围替换后前两章原样、整列覆盖被 409 拦下）+
  `tools/shots/verify_dual_scope.mjs`（真实界面 16 项，含 ⌘Z 退回）。

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

#### 3.7.5 结构建议（Phase 1，2026-11）

- **独立车道**：结构建议不是润色提案，单独 `{output_dir}/{stem}.ai-structure.json`，
  不经过 `ai_proposal.apply_polish()`，也不改 D-1。润色提案仍然只认 `{i, after}`。
- **外部模型只给 ops**：`{"ops":[...]}`。**不要**要求模型输出 `version/kind/digest`；
  网页版模型算不出本地哈希、抄也容易错。`version/kind/source.digest/source.count/revision`
  全部由服务端在 `POST /api/ai/structure/from-json` 时本地绑定。
- **下标基准**：所有 `from/to/i/after` 都是**应用前当前字幕的 1-based 原序号**。
  apply 一次从原列表生成新列表，只压 1 步历史；禁止边应用边重算下标。
- **支持的操作**：`merge`、`retime`、`replace_text`、`insert`、`delete`。
  - `merge`：`from/to`（含两端），可选 `text`；缺省用 `core.subtitles.join_cue_texts()`
    拼接原句，时间取区间 `min(start)…max(end)`。手工合并与结构建议共用这条拼接口径。
  - `retime`：`i/start/end`，只改时间不改文本；必须 `0 ≤ start < end`，且不能与相邻句重叠。
  - `replace_text`：`i/after`，只改文本不改时间；`after` 不能为空（删整条用 delete）。
  - `insert`：`after/start/end/text`；`after=0` 表示插在第 1 条之前（允许）；
    必须给 `start/end/text`，且不能与相邻句重叠。
  - `delete`：`i`。
  - **不做 split**：需要拆分的句子保留原样。Phase 2/3/4（整段 SRT 反推、本地语法检测、
    润色改时间轴开关）明确不做。
- **冲突**：合并区间重叠/区间内再改删、同一条重复操作、insert 落在合并区间内部、
  retime/insert 时间重叠或越界 → 对应 op 标红且不可勾选；apply 对**选中子集**重新
  校验，有冲突整批 409，字幕零改动。
- **译文保护**：存在非空译文轨时，`merge/insert/delete` 会改变条数 → 409 并提示先处理
  译文；`replace_text/retime` 不改条数，仍允许。**不自动丢弃译文轨。**
- **应用后丢弃**：apply 成功即删除结构建议文件；剩余未选中的 ops 下标已经不可信，
  下一轮重新粘贴。`⌘Z` 一次退回整批。
- **接口**：`GET /api/ai/structure`（恢复预览）、`POST /api/ai/structure/from-json`
  （解析+绑定+落盘）、`POST /api/ai/structure/apply`（原子应用）、
  `DELETE /api/ai/structure`、`GET /api/ai/structure/prompt`（复制结构检查提示词）。
- **纯函数**：解析/校验/冲突/原子应用都在 `core/ai_structure.py`；路由不得另写一份。
  用例：`tests/test_ai_structure.py`、`tests/test_server_structure.py`。

#### 3.7.6 断句重排（整份换稿，2026-11）

第三条车道，和上面两条**不共用文件、不共用应用路径**：

| 车道 | 能改什么 | 落点 |
| --- | --- | --- |
| 润色提案（3.7.3） | 只换文本，条数与时间轴固定 1:1 | `apply_polish()` |
| 结构建议（3.7.5） | 只改模型点名的几处（ops） | `apply_selected()` |
| **断句重排** | 条数、切分、时间码、文字都能变 | `Session.replace_range()` |

- **只收标准 SRT**（序号 + `-->` 时间码 + 文本）。纯文本一律 422「缺少时间码」——
  **不做「按原稿重算时间轴」**：时间码就是模型给的，程序只体检、不替模型改数。
- **体检不拦路**：重叠 / 倒序 / 超长（>9s 或 >24 字）/ 越界（分段时超出本段 ±1s）/
  空白 / 与原稿完全一致，都只标注，允许照样应用。只有「不是一份字幕」（空、负数、
  结束早于开始、超过 5000 条）才 422。
- **条数腰斩要二次确认**：新稿条数 < 原段 50% 或 > 200% 时，主按钮变成两步确认
  （再点一次才真覆盖）。这是唯一会拦一下的地方：漏粘半份 / 粘进示例内容时会在这里
  被发现。正常重排（208→127）不触发。
- **应用锚点是原稿索引区间** `(from_index, to_index)`，不是模型给的时间边界：分段时
  两段的交界由原稿的切法决定，模型的时间漂移不该误删邻段。分段计划第一次需要时算一次即
  **冻结**，之后每段按「前面已覆盖段的条数差」平移（`currentRangeFor()`），段轨上的
  `1–141` 不会自己跳数字。
- **冻结键（2026-11-15 补齐）**：计划身份 = 媒体身份 + 做法（整份重写 / 只改几处）
  + **第二版的身份**（`createdAt`，不是 B 的条数）+ 有没有稿。**不含 `source`、不含
  A/B 的条数**。单源 ↔ 双源只决定提示词里带不带 B 参考，不决定工作单元；把 `source`
  放进冻结键的后果是：覆盖过两段后点一下「单源」再切回「双源」，整页会对着**已经改过的
  表**重新切段（501 条切 4 段、441 条只切 3 段），在途的第三段草稿再也粘不回去。这是
  2026-11-15 用户报障的根因，回归用例 `desktop/test/reshapePlan.test.mjs`。
- **已开工不再静默重切**：只要有一段被覆盖，原稿 / 第二版 / 字幕身份的任何变化都只
  挂「分段计划已失效」横幅（`reshape.stale`），由人选择「恢复上一版分段」或「重新定
  计划」；此时复制提示词、解析、覆盖全部暂停。静默重切 = 换坐标系，在途草稿与已覆盖
  区间都会失配。
- **段的身份是原稿起条号**（`segmentKey()`），不是展示区间 `"from-to"`：覆盖后条数会
  变，展示区间会漂；用漂过的区间当 key 会让勾选、草稿、进度全部失配（旧实现里表现为
  「已覆盖 2/3 段」但段轨上一个勾都没有）。
- **外部改动侦测**：`app.cuesRevision` 与「我们自己最后一次动作后的 revision」不一致，
  就是原稿被别处改过（⌘Z、核对台增删、重新导入 / 重新转写、整列覆盖）。未开工 →
  自动按当前稿重切；已开工 → 失效横幅。**⌘Z 撤掉的若是我们自己那次覆盖**（`redo_label`
  是断句重排标签、区间对得上某段 `wasFrom/wasTo`，且按其余各段 delta 推算的条数正好
  等于撤回后的表条数），则把该段的覆盖标记一并退回、状态同步回退，不留脏 delta。
- **进页不重置**：计划与进度只随**换媒体**清空（`syncReshapeMedia()`）。切视图会销毁
  重建组件（`App.svelte` 的 `{#if app.view === 'reshape'}`），任何写在挂载生命周期里的
  `reset` 都会让「复制提示词 → 去核对台 → 回来」丢失整页进度。
- **digest 守卫**：解析时服务端返回整表 `digest`（复用 `source_digest`），apply 必须
  带上；对不上（原稿在解析后被改过）→ 409「请重新粘贴一次」，绝不错位覆盖。**这份
  digest 是整表的，不是区间的**：所以任何「锁定某个区间稍后回填」的能力，都必须拿同一份
  整表 digest 做前置校验，否则会出现「允许锁定、提交必 409」的假可用状态。
- **译文轨（2026-11-20 修订）**：条数变化时不再整轨丢弃。范围外头部 / 尾部译文按
  `delta` 平移并保持索引对齐，范围内新条目译文置空；响应里 `shifted_translations`
  说明哪些轨被平移，界面给一条轻提示。`⌘Z` 同口径整步退回。
- **分段**：A+B 超过 600 条 / 6 万字才切（润色是 300 条），每段 150 条；短片一次跑完、
  一次覆盖。分段覆盖只动本段，其余段原样保留。
- **提示词**：`prompt_store` 的 `reshape_single` / `reshape_dual` 两个分类（内置模板
  在 `core/prompts.py`），「只改几处」仍用 `ai_structure.build_prompt()`。两类模板
  互不顶替：1:1 模板发去整份重写会得到一份不能应用的稿。
- **接口**：`GET /api/ai/reshape/prompt`、`POST /api/ai/reshape/from-text`、
  `POST /api/ai/reshape/apply`。纯函数（解析 / 体检 / 摘要）在 `core/reshape.py`，
  区间替换在 `server/sessions.py`，路由不得另写一份。前端的分段坐标系
  （冻结键 / 平移 / 段身份 / ⌘Z 认领 / 重新分段落位）在 `desktop/renderer/src/lib/reshapePlan.ts`
  （纯函数，`desktop/test/reshapePlan.test.mjs`），`reshape.svelte.ts` 只留状态壳。
  用例：`tests/test_reshape.py`、`desktop/test/reshapePlan.test.mjs`。

#### 3.7.7 单句 AI 辅助（第三版，2026-11-20）

> 触发：核对台里 A/B 两版引擎对同一句的转写不一致时，用户当前只能截图两版和上下文
> 发给外部 AI，再手工改回来。这条车道把「问 AI → 看第三版 → 采用」收进检查器。
> 2026-11-20 扩展：ASR 完全没识别、B 引擎返回空、手动新建空字幕块时，只要能提供
> 听音线索 / 追问记录 / 上下文之一，也能让 AI 还原，不再被「必须 A/B 双版且不一致」拦住。

- **不是提案**：没有 digest、没有提案文件、不经过 `apply_polish()`；它是检查器里的
  第三张卡，采用时走既有 `updateCue()`（服务端一步历史，⌘Z 可退）。
- **只发文本**：`POST /api/ai/arbitrate` 收
  `{text_a, text_b, before[], after[], lang, hint?, history?}`。`hint` 是用户的听音
  线索（空耳 / 罗马音 / 描述，≤400 字）；`history` 是最近的多轮追问
  （`[{role: "user"|"assistant", text}]`）。前后文各最多 3 句、每句最多 200 字；
  **绝不**包含时间轴、音频、截图或整片字幕。
- **2048 context 预算**：`hint` ≤400 字、最多 6 轮追问、单条 ≤260 字；`core/ai_arbitrate.py`
  先按 `MAX_USER_CHARS=1300` 从**最旧**的记录开始裁，再裁上下文，任何材料组合都不会
  把 prompt 撑爆本地 2048 档位。
- **422 放宽**：不再要求 A/B 都非空且不一致。只要 A/B 不一致、仅 A 或仅 B 非空、
  有 `hint`、有 `history`、有上下文之一即可请求；只有 A、B、hint、上下文**全部为空**
  才返回 422。两版一致但用户想复核也允许。
- **提示词动态适配**：按实际材料走双版对照（dual）/ 两版一致复核（same）/ 单版纠偏
  （single）/ 无识别纯靠上下文 + 听音线索还原（blind），并把 `hint`、`history` 作为
  独立段落组织；输出仍是 `{"text": "...", "note": "..."}`，保留 `/no_think` 与本地
  assistant 前缀。
- **上下文口径**：前端按 `start` 排序后找到当前句的位置，**排除当前句索引**再取前后
  各 3 句。不能用 `end <= cue.start` / `start >= cue.end` 过滤——转写选区的
  `padStart/padEnd` 会让邻句轻微重叠，重叠条件会漏掉边缘邻句。
- **分语种提示词**：`core/ai_arbitrate.build_prompt()` 按 `lang` 选日语 / 中文模板；
  中文素材不得套日语助词/活用规则，日语素材也不按中文语序重写。未知语种走通用模板。
  听音线索只用于定位发音，最终输出必须是素材同语言的文本。
- **结果校验**：只收 `{text, note}`；`text` 为空、超长（>300 字）、含 `-->` 或时间码
  → 重问一次（附 `STRICT_HINT`），仍失败返回 502，不产生半份结果。结果不落盘，
  只存在当前会话内存；A/B 文本或时间变了就自动失效。
- **界面常驻**：`components/ArbitrationCard.svelte` 挂在 `SecondOpinionCard` 内部、
  **不在 `has` 分支里**；只要选中任意字幕行（含空字幕块、B 未跑或返回空）就用。
  B 引擎返回空时明确提示「另一引擎未识别到内容，可补充听音线索直接让 AI 推断」。
  A/B 一致不隐藏入口，按钮文案按材料自适应（让 AI 判定 / 辅助修正 / 根据线索推断）。
- **听音线索输入**：AI 按钮上方是紧凑输入框（≤400 字，⌘↩ 快捷发送）；出结果后标签
  变为「补充线索 / 追问」，并出现**独立的「发送追问」按钮**：只有输入框非空且用户明确
  点它时，才把这条线索追加进 `history`。右侧边栏只展示**最新一轮**结果卡（含 TTS
  朗读、复制与采用），不把长历史塞进窄边栏。
- **重判与追问彻底分离（2026-11-20 用户报障）**：`arbitration.svelte.ts` 的 `runArbitration`
  按 `mode` 分四路——`initial` / `followup` / `rejudge` / `auto`。`rejudge` 与 `auto`
  **永远不发送 `history`**，请求体只带当前 A/B、前后文与（若输入框非空）本次新写的
  `hint`；输入框为空时 `hint=""`。已有追问时主按钮文案变为「清空追问并重判」，绝不
  再把上一轮追问或偏掉的 AI 回复喂回模型。`followup` 是唯一携带历史的路径。
- **撤销 / 回退**：浮窗里每条用户追问右上角有「撤销这轮及之后」，底部还有
  「↩ 撤回上一轮追问」。两者都在前端内存截断该轮及之后的 `messages`，并把右侧结果卡
  同步回截断后最后一条 AI 回复；不重新请求模型。撤到只剩第 1 轮干净结果时，状态与
  刚判完首轮完全一致。纯函数 `truncateFromUser()` / `lastUserPosition()` 在
  `lib/arbitration.ts`，单测在 `desktop/test/arbitration.test.mjs`。
- **多轮对话浮窗**：`components/ArbitrationDialog.svelte` 由卡片右上角「展开对话」
  打开；可拖动 / 可缩放（参考质检浮窗，默认避开右侧「试听原声」）。浮窗内展示可折叠
  上下文（前 3 / 后 3 句）与 A/B、完整历史、底部多行追问框；**每一条** AI 历史回复
  都自带「朗读」「复制」与「采用」，采用同样走 `updateCue()`。
- **只留一个对话入口**：右侧 AI 卡标题栏的「展开对话」是唯一入口；结果卡不再放
  「查看对话 / 继续追问」这类重复按钮，窄边栏保持利落。
- **可选中 / 可复制**：`SecondOpinionCard` 的 A/B 文本、`ArbitrationCard` 的 AI 文本
  与理由、`ArbitrationDialog` 的上下文与每一轮台词/理由都显式 `user-select: text`，
  允许划选局部假名或整句；A 卡、B 卡、AI 判定卡与浮窗每条 AI 回复的「朗读」旁都有
  `CopyTextButton`，一键复制并短暂显示「已复制」。AI 结果与当前稿一致（按钮显示灰色
  「当前稿」）时，复制入口仍保留。
- **会话缓存**：对话按「媒体 + 起止时间」缓存在内存，切换句子不丢正在磨的对话；
  该句时间 / A / B 被外部改写后线程判旧，界面提示「已失效」并要求重置，自动判定等
  非 UI 路径也会从新快照重开，绝不把旧答案混进新请求。采用后同步线程快照，继续追问
  不会立刻失效。
- **模型覆盖**：`settings.json` 的 `ai_arbitrate_base_url` / `ai_arbitrate_model` 为空
  时逐字段跟随全局 AI 配置；非空时用它们。覆盖 Key 与全局 Key **分开加密**：
  `aikey` 的 `scope='arbitrate'` 存 `aiArbitrateKey`，请求头是
  `X-AI-Arbitrate-Key`；覆盖地址是本机/局域网时允许空 Key，且**不**把全局 Key
  转发给本机服务。
- **本地兼容**：`core/ai_client.is_local_url()` 认定 loopback / RFC1918 / `.local` /
  `host.docker.internal`；`AiConfig.allow_no_key=True` 时 `ensure_ready()` 允许空 Key，
  `_post()` 连空 `Authorization` 都不发。
- **稳健解析**：`json_from_text()` 先剥 `<think>…</think>`、`<|…|>` 特殊 token 与
  Markdown 围栏，再兜底取 `{…}`；`_extract_content()` 在 content 为空时回退
  `reasoning_content`。本地后端不支持 `response_format`（400/404/422）时去掉该字段
  重发一次，不占重试次数。
- **Qwen 推理模型**：模型名含 `qwen` / `think` 时，`build_prompt(no_think=True)` 会在
  user 末尾追加 `/no_think`；否则 LM Studio 里的 Qwen3.8 常把答案全写进
  `reasoning_content`、content 为空。本地模型还会带 assistant 前缀 `{"text": "`，
  让模型直接续写 JSON（实测 Qwen3.8 27B 从「只出推理」变为稳定返回 JSON、约 2–5 秒）；
  云端模型不带前缀。本地模型默认加载 2048 context：本功能最多几百到一千多字，2048
  已足够，也最省内存。
- **本地上下文档位**：`settings.json` 的 `ai_local_context` 只支持 2048 / 4096 / 8192，
  默认 **2048**。设置页只在判定目标是 **本机 loopback LM Studio** 时显示档位与
  「加载 / 重载本地模型」按钮；远程 API、局域网地址或非 LM Studio 服务不显示/不执行。
  重载走 `POST /api/ai/local-model/load`：先 `POST /api/v1/models/unload` 卸掉该模型的
  已加载实例，再 `POST /api/v1/models/load` 带 `context_length` 加载；按钮立即生效。
  判定前只做一次轻量 status 探测，**只有模型未加载或档位不符才校准一次**；模型已在
  目标档位时是纯 no-op，绝不每个请求重载 27B。实现集中在 `core/ai_local_model.py`，
  不污染 `ai_client.py`。
- **自动判定（P2-4）**：`settings.json` 的 `ai_auto_arbitrate` 默认 `false`。开启后，
  **只**在 B 引擎复核完成且 A、B 均非空且文本不一致时自动触发一次；同一媒体 + 同一句
  + 同一 B 文本只自动跑一次，避免选中/重渲染造成重复调用。空白字幕、手动输入线索、
  单版或两版一致都不会自动触发。切换句子、改 A/B、卡片卸载或点取消都会通过
  `AbortController` 中断在途请求。不做提示词库第六类，也不做 QaPanel 入口。
- **取消**：前端用 `AbortController` 真正中断 fetch；服务端那条短请求会自行结束，
  结果被丢弃。判定请求**不占** `JobManager` 单槽，转写进行中也能用。
- **设置页分级（2026-11-21，界面重构 Step 6）**：设置 → AI 与技能顶层只留
  「启用 AI 优化 / 服务地址 / 模型 / API Key / 连接测试」与底部「Agent 技能」；
  单句判定覆盖、自动判定、本地上下文档位与分块参数都收进
  `components/settings/ai/AiAdvancedFold.svelte`（标题
  「进阶：单句判定独立模型与本地部署」）。默认开合由纯函数
  `lib/settings/aiFold.ts` 的 `advancedAiInUse()` 决定：判定服务地址 / 判定模型 /
  判定 Key 任一已填（含解不开待重填）或 `ai_auto_arbitrate` 已开就默认展开——既有高级
  配置不会因为折叠而消失。它要等两把 Key 的「有没有」都问过主进程（`aiState.keyChecked`）
  才生效，否则「只存过判定 Key」的配置会被异步返回前的空状态误判；用户点过折叠区之后
  以用户为准，保存 / 清 Key 引起的配置刷新不会把面板弹回去。收起时摘要仍写明
  「跟随全局 / 已单独配置 / 本机 LM Studio · 自动判定开/关」。
  单测在 `desktop/test/settings-ai-fold.test.mjs`。
- **回归**：`tests/test_ai_arbitrate.py`（提示词无时间码 / 分语种 / 动态模式 / 预算 /
  结果校验）、`tests/test_ai_local_model.py`（loopback 限制 / 卸载后重载 / 同档位 no-op）、
  `tests/test_server_ai.py`（本地无 Key、覆盖 Key、502 重问一次、422 放宽、
  hint/history 透传、字幕不变、文档位/自动开关）、
  `desktop/test/arbitration.test.mjs`（上下文 / 分类 / 失效 / 线程键 / 追问裁剪 / 按钮文案 /
  干净重判请求计划 / 撤销截断）、
  `desktop/test/floatBox.test.mjs`（浮窗夹取）、
  `tools/shots/verify_arbitration.mjs`（第三版真实界面）、
  `tools/shots/verify_arbitration_dialog.mjs`（常驻区 / 空识别提示 / 草稿持久 / 浮窗
  拖动缩放 / Esc / 发送追问与清空重判分离 / 请求体无旧 history / 撤销同步结果卡 /
  复制反馈 / 文本可选中 / 单一对话入口）、
  `tools/shots/verify_settings_ai_fold.mjs`（进阶折叠默认收起 / 已配置默认展开 /
  手动开合 / 摘要文案 / 导出页无译文引导 —— 见 §3.8.2 末条）。

#### 3.7.8 片段范围：局部润色 / 局部翻译（2026-11-20）

长片常常只核对一段（例如第 291–581 条）。范围由用户在润色 / 翻译 / 导出页选（全片 /
区间章节 / 自定义起止），三处共用同一份状态；本章只约束 AI 链路。

- **提案的身份**：`source.range = {"from": 291, "to": 581, "count": 291}`。
  - `items` 的 `i` **仍是全片 1 基序号**（291…581），界面直接用全局 `#i` 对行，
    长片分段粘贴也不换坐标系；
  - `source.digest` **只覆盖这一段**的原文（`source_digest(scope_texts)`）：模型看到多少
    就绑定多少。范围外（例如第 1 条）改了字幕不会 409——那本来就不该让这段提案失效；
    范围内改了才 409「源文本已变化」；
  - 没有 `source.range` 的旧提案 = 整片，行为与之前完全一致。
- **生成**：`POST /api/ai/jobs` 的 `from_index` / `to_index`（1 基、含两端）。
  `server/jobs.py` 先切出这一段再交给 `ai_polish.run_polish()` / `ai_translate.run_translate()`，
  两者用 `cue_span` 只调整 `items` 的序号基线与 `source.range`；**分块、结构重问、取消口径不变**。
  双源润色的 `digest_b` 仍绑定**整片第二版**（B 只作参考），B 的时间窗取本段的绝对时间。
- **手动提示词**：`GET /api/ai/prompt` 新增 `range_from` / `range_to`（作用范围）；原有的
  `from_index` / `to_index` 是**当前分段**（长片分段 + 范围可以叠加）。润色与翻译都只把
  这一段写成 SRT；`range_text` 明确「本次只处理片段第 X–Y 条（全片共 N 条）」。
- **粘贴回填**：`POST /api/ai/from-srt` 的 `range_from` / `range_to` 决定提案覆盖哪一段，
  `from_index` / `to_index` 决定这次实际回填的段内区间；段外条目保持原文（分段粘贴语义不变）。
- **应用**：`POST /api/ai/apply` 用 `source.range` 调
  `core.ai_proposal.apply_polish_range()`——它只把全局序号映射成段内序号后**调用
  `apply_polish()`**，段外条目逐字节拼回。仍然是「整批一次历史」：`replace_review()` 一步，
  ⌘Z 一次退回。
- **译文局部合并**：`POST /api/translations` 带片段提案时，按原始索引把这一段译文合并进
  **整片平行译文轨**：范围外已有的译文与空位原样保留，不重排、不清空；没有旧轨时建一条
  整片长度、范围外为空的轨。`base` 只更新这一段（范围外是否过期照旧如实反映），
  `set_translation()` 压一步统一历史。
- **文件位置不变**：片段提案仍写在 `{stem}.ai-polish.json` / `{stem}.{lang}.ai-translate.json`，
  最后一次生成 / 粘贴 / 导入的提案覆盖同名文件；`source.range` 说明它绑定的是哪一段，
  应用 / 校验 / 译文合并都以提案自身的 range 为准（不跟界面当前选择走）。
- **界面**：`components/ClipScopePicker.svelte`（全片 / 区间章节 / 自定义，显示命中条数
  `291 / 899`）+ `lib/clipRange.ts`（与 `core/clip_range.py` 同一套 0.1s 蹭边阈值与章节选项
  规则）。状态只有一份：`store.exporter.clip`，走 `setExportClip()` 进统一历史，
  润色页 / 翻译页 / 断句重排页 / 导出页 / 章节面板「仅处理此片段」读写同一份
  （断句重排的局部替换见 §3.7.11）。
- **回归**：`tests/test_clip_scope.py`（片段 digest 只绑本段、范围外改动不 409、范围内
  改动 409、局部译文合并保留范围外、提示词只含本段、任务链路真按范围生成）、
  `tests/test_clip_range.py`（边界/夹紧/章节平移/文件名标签）、
  `tools/shots/verify_clip_scope.mjs`（三页共用范围、表格只剩 4 行、一键带入）。


#### 3.7.9 手动自由分批（条号子范围，2026-11-20）

在「处理范围」（全片 / 区间章节 / 自定义时间，§3.7.8）之上，润色页 / 翻译页 / 断句重排页
再叠一层**本次处理批次**：

- **默认等于整个处理范围**（例如章节命中 `1 ~ 291`）；不碰批次控件时请求与旧行为一致。
- 用户可以输入起始 / 结束条号，或用「每批 N 条」+「上一批 / 下一批」步进。批次永远夹在
  处理范围内（`desktop/renderer/src/lib/cueBatch.ts` 纯函数，`desktop/test/cueBatch.test.mjs`）。
- **复制提示词、粘贴回填、应用只作用于当前批次**：批次激活时提案的 `source.range` 就是这批，
  `items` 的 `i` 仍是全片序号；范围外条目一个字节都不动。
- **润色恒为严格 1:1**：复制出去几条，粘回来必须几条，否则整批 422。翻译页的宽严由下面的
  开关决定，开关不作用于润色。
- **批次基于实时索引切片**：表格直接按当前 `rows` 的 `[from-1, to)` 切片，批次指纹只含
  媒体 / 范围 / 批次 / 总条数、不含文本。所以中途改前面某句的文字不会让批次失效或漂移；
  处理范围变小时批次跟着夹紧。
- **手动批次优先于自动智能分段**：一旦进入手动批次，`planAiSegments()` 不再切段、也不把
  页面锁回 150 条一段；点「整段」回到自动分段。断句重排同理：局部范围 / 批次就是这一轮的
  工作单元，不再叠加自动分段。
- **界面**：`desktop/renderer/src/components/ai/BatchRangeBar.svelte` 三页共用；状态分别在
  `desktop/renderer/src/lib/aiWorkspace.svelte.ts`（润色 / 翻译）与
  `desktop/renderer/src/lib/reshape.svelte.ts`（断句重排）。

#### 3.7.10 翻译的时间轴对齐（2026-11-20）

翻译页「外部粘贴回填」默认**允许带时间轴的译文条数与原文不同**，只要求 SRT 带时间戳：

- **严格条数开关默认关闭**：关闭时，条数相同仍按顺序对齐（旧行为）；条数不同则调用
  `core.proposal_srt.align_translation_cues()`，按**时间戳区间交集**把每条译文映射到原句槽位。
  打开开关后恢复旧的等条数强校验（422）。
- **合并覆盖**：一条译文跨原句 #5、#6 时，译文写入 #5，#6 置空并标 `merged`；#6 的
  `after` 是空串，校验层对 translate 允许空槽位（不把日文原文填进译文轨）。后续条目从
  #7 起继续对齐（游标只前进，不回头补空位）。
- **异常状态**：起止任一端与原文偏差 > 0.5s 标 `drift`；整条落在本批时间窗之外计入
  `out_of_range` 且不写入；没有匹配到译文的原句标 `missing`。翻译页表格按行高亮并显示
  状态标签，页头横幅给出计数。
- **纯文本仍然拒绝**：没有时间轴就无法判断该写哪一句，条数不同时整批 422。
- **对齐结果随提案保存**：`proposal.alignment = {from,to,pasted,rows,counts,warnings}`，
  切页 / 重开仍能还原高亮；`items` 仍是契约里的 `{i, before, after, note}`，不新增时间字段。
- **应用只合并本批**：提案的 `source.range` 是本批区间，`POST /api/translations` 按原始索引
  把这一批译文写进平行轨，范围外译文 / 空位原样保留；一步统一历史，⌘Z 可退。
- **回归**：`tests/test_translation_align.py`（合并 / 偏差 / 范围外 / 空缺 / 纯文本 /
  严格开关 / 空槽位应用）、`tools/shots/verify_batch_and_align.mjs`（真实界面）。

#### 3.7.11 断句重排的局部范围（2026-11-20）

断句重排页接入与润色 / 翻译 / 导出**同一份** `ClipScopePicker`（`store.exporter.clip`），
并可叠加条号子范围：

- **应用锚点仍是原稿索引区间**：范围命中 `[from_index .. to_index]`，`Session.replace_range()`
  只替换这一段；范围外的前后字幕原样保留。
- **局部范围 / 手动批次优先于自动分段**：选定局部范围时不再自动切段；段轨只显示这一格
  「本次处理」。未覆盖的粘稿在范围变化时作废并提示；已覆盖后改范围 → 失效横幅，必须
  「重新定计划」，不静默重切。
- **范围外译文保持索引对齐（2026-11-20 修复）**：`replace_range()` 在条数变化时不再整轨
  丢弃译文，而是按 `delta` 平移范围外头部 / 尾部译文；范围内新条目译文置空（文本 1:1
  相同的覆盖保留原译文），`base` 同步新原文。统一历史仍是一步 ⌘Z 全退。
- **越界警告**：新稿时间戳明显超出本段时，`core.reshape.diagnose(range_start, range_end)`
  的 `out_of_range` 会在页面上挂高亮横幅；体检不拦路，覆盖仍只替换本段。
- **回归**：`tests/test_reshape.py`（尾部译文平移 / 只动本段）、
  `tools/shots/verify_batch_and_align.mjs`（选择范围 → 越界警告 → 覆盖 → 条数 6→5、
  尾部译文平移 toast）。

#### 3.7.12 三页统一工作条与「执行通道」（2026-11-21）

翻译 / 润色 / 断句重排共用 `components/ai/AiBatchToolbar.svelte`，头部固定**两行**：

- 第 1 行「处理什么」：标题 + 页内模式（断句重排的做法 / 翻译的目标语种）+ 模板 +
  处理范围 + 右侧状态（来源徽标、⋯ 菜单、提示词库入口）。
- 第 2 行「怎么跑」：`[ 自动 API | 外部手动 ]` **二选一分段开关** + 该通道的动作链 + 本次批次。
- 长片的智能分段轨只在**多段**时以紧凑单行（`SegmentRail compact`）出现，已覆盖计数挂在轨头；
  单段不额外占一行。
- 模板 / 范围 / 批次仍复用既有组件，状态仍由 `aiWorkspace` / `reshape` 持有；低频的
  重新加载 / 另存 / 丢弃收进 `components/ai/ProposalMenu.svelte`，两页不再各写一份。

「自动 API」与「外部手动」是两条**互斥**的工作流：切换后只显示选中通道的动作，不再把
「生成建议」和「复制提示词」并排挤在同一行。断句重排没有 in-app 生成接口，它的「自动 API」
明确置灰并给说明，只能走外部手动。

- **通道状态**：`lib/aiWorkspace.svelte.ts` 的 `ai.channel` / `setAiChannel()`。
  `loadAiSetup()` 探到本机 AI 没启用 / 没 Key 时默认落在**能用**的外部手动；用户自己切过
  （`channelTouched`）之后不再自动改写。
- **来源徽标**：不再用「外部粘贴」（和按钮「粘贴回复」撞语义），统一 `aiEntryLabel()`：
  本机生成 / 命令行 Agent（`entry=cli`）/ Agent 文件 / 外部回复。
- **digest 失效禁用应用**：`ai.digestMatch === false` 时，`components/ai/AiApplyBar.svelte`
  的主按钮与「更多应用」一律禁用，告警与按钮旁都写「请先重新生成」。禁止一边红字告警、
  一边留着可点的红色主提交键。
- **空态引导**：无提案时按当前通道给 1–2 步引导卡（`.aiw-blank-*`），翻译页不再是一片空白；
  本机 API 未就绪时柔和引导「去设置」或「改用外部手动」。断句重排的「只改几处」在粘稿前
  也用同一套引导块说明第 3 步，而不是一行小字。
- **回归**：`tools/shots/capture_ai_toolbar.mjs`（三页两行头 / 第 1 行不折行 / 翻译模板
  单一入口 / 失效禁用 / 空态卡）、`tools/shots/verify_reshape_flow.mjs`（分段计划冻结）、
  `tools/shots/verify_batch_and_align.mjs`（批次与时间轴对齐）。

#### 3.7.13 外部 CLI 与提案状态轮询（2026-11-21）

- **CLI 只提交、不应用**：`kikusub propose polish|translate` → `POST /api/ai/proposal`；
  `propose structure` → `POST /api/ai/structure/from-json`（模型只给 `{"ops":[...]}`，
  digest/revision 本地绑定）；`propose reshape` → `POST /api/ai/reshape/proposal`。
  三个入口都走 `core/ai_proposal` / `core/ai_structure` / `core/reshape` 的既有校验；
  CLI 不自己算 digest、不调用任何 `/apply`，失败就整份拒绝。
- **断句重排也落盘**：`{output_dir}/{stem}.ai-reshape.json`
  `{version, kind:"reshape", entry:"cli", source:{count,digest,range:{from,to,total}}, cues:[...]}`。
  `GET /api/ai/reshape/proposal` 返回 `stale`（digest 与当前字幕不符）、体检与 `text`（SRT），
  供渲染层一键填回粘贴框；应用仍走既有的 `/api/ai/reshape/apply`（digest 校验在服务端）。
- **状态轮询**：`GET /api/proposals/status` 只 stat 四类文件（polish / 多语种 translate /
  structure / reshape），返回 `{items:[{kind,lang,path,mtime_ns,size}], revision}`；**不读正文**。
  渲染层每 2 秒轮询一次、窗口聚焦立即拉一次（`lib/externalProposals.svelte.ts`）。
- **不覆盖草稿**：润色/翻译有未提交的 `ai.edits` / 取消采纳时只弹提示、不重载；结构建议只在
  面板打开时刷新；断句重排只提示，由用户点「载入到粘贴框」。轮询失败静默重试，不打扰用户。
- **来源徽标**：`entry: "cli"` 显示「命令行 Agent」；旧文件方式 `entry: "skill"` 仍显示「Agent 文件」。
- **验收**：`tests/test_server_proposals.py`（状态 / reshape 提案 / stale）、
  `tools/shots/verify_external_proposals.mjs`（写提案 → 2 秒内提示并自动载入润色页）。

#### 3.7.14 补译批次（gap fill，2026-11-25）

用户的核对工作流：分章节转录 → 双语逐句听、逐句改 → 一章过完只剩十几条没有译文
（局部转写新加的行，或者人工删掉的坏译文）。为了这十几条重翻整章，会把已经核对过的
译文一起覆盖。补译批次就是为这条工作流单开的一条**一次性回填通道**。

- **不走提案**：不生成 `*.ai-translate.json`（那会覆盖整章的翻译建议）、不绑定
  `source.digest` 提案契约、不改 CLI / 技能的 schema。`core/ai_gap.py` 是唯一实现。
- **复制只含待译条目**：`GET /api/ai/prompt?...&indices=285,287`。SRT 的序号是
  **全片条号**（不是 1~N），时间戳沿用原文；前置说明（走 `{{RANGE}}` 注入口，用户模板
  不用改）写明「只输出这些条目、序号原样保留、一条不多一条不少」；文末附
  **上下文块**（每条待译句前后各 4 条原文 + 邻居已有译文，纯文本、最多 120 行、
  标明「仅参考，不要输出」）。返回 `{indices, sparse:true, digest}`。
- **回填严格 1:1**：`POST /api/ai/gap-from-srt {indices, text, digest}`。先按序号落位
  （集合完全一致时）；序号被改写但条数一致时按顺序落位并给 warning；条数不一致整批 422
  并点名缺哪条；空译文条目会被解析器丢弃 → 同样报「缺 #N」。**不做时间轴对齐**——
  整段翻译的对齐会猜槽位，补译的每一条都有明确下标，猜错就是把 A 句译文写进 B 句。
- **应用只写显式下标**：`POST /api/translations/gap {lang, items:[{i, before, after}]}`。
  逐条校验 `before` 必须等于当前原文（复制之后原文改过 → 409，零写入）、`after` 非空、
  条号去重 / 越界 422；合并走 `core.i18n.merge_translation_texts(skip_empty=True,
  sync_unchanged_base=True)`，**名单外的槽位不进入写循环**，`base` 只对写入的条目重设；
  一次 `set_translation` = 一步统一历史。
- **提案应用的空槽位不再清掉已有译文（同一轮修正）**：`POST /api/translations` 的
  `proposal` 通道现在 `skip_empty=True`（直接给 `texts` 数组仍是「每格都是最终值」）——
  模型把两条合并成一条时，被合并槽位的 `after` 是空串，只表示
  「本批没有这一条」，不表示删掉用户已核对的译文；响应里的 `kept_empty` 是提示数。
  真正要清空一条译文仍走逐条 `PATCH`（空文本）。
- **逐条取消采纳生效**：`/api/translations` 接受 `accept`（全片 1 基序号），只写被勾选的
  条目；翻译页的 pin 不再是「点了没反应」。
- **入口两个、状态一份**：检查器译文轨行的「补译 N 条」（一键复制并切到翻译页）与翻译页
  顶部的补译卡片；状态在 `desktop/renderer/src/lib/gapFill.svelte.ts`，待译集合由
  `desktop/renderer/src/lib/gapBatch.ts`（零运行时 import，有 parity 单测）计算，
  默认范围 = 当前处理范围（章节），「原文已改」要显式勾选才纳入。
- **四道锁**：① 只复制 / 解析这 N 条；② 按全片条号落位、不做时间轴猜测；
  ③ 服务端只接受显式下标（不是前端裁剪）；④ `before` 校验 + 空值不覆盖 + 一步历史，
  toast 报「写入 N / 保留 M」。
- **回归**：`tests/test_ai_gap.py`（纯函数 / prompt / 解析 / 只写名单 / 409 / 一步历史 /
  空槽位保护 / accept）、`tests/test_i18n.py`（merge 口径）、
  `tools/shots/verify_gap_fill.mjs`（真实界面：复制 → 少翻一条报错 → 取消勾选只写一条 →
  补最后一条 → 已核对译文不变）。
