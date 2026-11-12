# AI 提案与 AI 优化台（M1–M4）

> 从 `AGENTS.md` 拆出（2026-11-13）。提案契约、模型调用、译文平行轨、Agent 技能。配套开发文档：[AI优化与翻译-开发文档-2026-11.md](../AI优化与翻译-开发文档-2026-11.md)。总索引见 [AGENTS.md](../../AGENTS.md)。

---

### 3.7 AI 提案与 AI 优化台（2026-11 M1，后续里程碑会扩展）

- **时间码由结构保证，不靠提示词**：提案里只有 `{i, text}`，**没有时间戳**。应用时
  `start/end` 一律取自当前 `review_cues`，提案里的任何时间字段都不参与。任何把时间码塞进
  模型载荷、或从提案读时间码的实现都算破坏契约（见 `docs/AI优化与翻译-开发文档-2026-11.md` D-1）。
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
- **密钥存储不要用 `safeStorage`**（2026-11-11 定稿，见开发文档 §11.4）：keychain 条目的
  ACL 认的是代码签名要求，而本项目以 DMG 分发、ad-hoc 签名，**每次发版 cdhash 都变，
  用户升级后 Key 全部失效**，且没有 Developer ID 无从修复。现在用
  `desktop/main/aikey.cjs`：32 字节主密钥存 `{dataDir}/.ai-key`（0600），
  `preferences.json` 里只放 `aik1:` 密文。
  改这块时守住三条：**0600 权限**、**旧 `v10` blob 要能识别并报 `broken`**、
  **绝不把明文写进任何文件或日志**。用例：`node --test desktop/test/aikey.test.cjs`。
- 只有将来改用 **Developer ID 签名 + 公证** 发布时，才值得切回 `safeStorage`；
  切之前先读开发文档 §11.4 的三方案对比。
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
#### 3.7.3 Agent 技能（2026-11 M4）

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
  改算法就同时改文档和用例，否则测试红。
- 安装器 `desktop/main/skill.cjs` 只用 fs（不引 electron），因此能被 `node --test` 覆盖；
  安装是"先删再拷"，`references/paths.json` 由渲染层传入的真实目录覆盖写入。
- 目标目录由**主进程**决定，不接受渲染层传进来的路径。

- **手动粘贴通道（2026-11 补充）**：`GET /api/ai/prompt` 组提示词（里面**带** SRT 与时间戳，
  为的是让模型逐条对齐），`POST /api/ai/from-srt` 解析回复时**只按顺序取文本，
  序号与时间戳全部丢弃**，时间轴仍用我们自己的 cue。条数不符整批拒绝（422）。
  改这块时不要把解析结果里的时间戳写回字幕——那会直接破坏 D-1。
