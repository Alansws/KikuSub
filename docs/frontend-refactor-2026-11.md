---
created: 2026-11-25 20:35
updated: 2026-11-26 14:10
---
# KikuSub 前端重塑（2026-11）

> **第二阶段 Batch 3 完成（2026-11-26）。** 配色升级为「明暗 × 六套色板」的正交体系，
> 设置页新增「界面配色」，18 个派生令牌改 `color-mix` 动态计算；6 × 2 = 12 种组合全量实测
> ≥4.5:1，`KikuSub-Next.app` 已重打，第二阶段未推送提交已推 GitHub。详见 §8.12。
>
> **状态：第一阶段封板（2026-11-26）。** 用户已确认把本分支作为「前端优化第一阶段完结版」
> 封板，推送 GitHub 新分支存档、暂不合入 `main`、现役旧版继续使用。
> **封板记录（能力边界 / 双开工具 / 第二阶段接续建议）见 §8.9。**
>
> **Step 8 三修完成（2026-11-26）。** 第三次真机试用又报回三条**配色/布局**缺陷，
> 本轮全部落地：暗色改**纯中性深炭黑阶梯 + 下沉暗槽**（§7.11 一）、
> 蓝色换 **Studio 皇家钴蓝**（二）、导入页删掉冗余灰条并按「一块台本纸 + 两条发丝线」重排（三）。
> 全量验证 25 个 `verify_*.mjs` 绿，Phase2 外壳 54 项（含 5 条新增的**明度方向**断言）绿。
>
> 以下是 Step 7 的记录：
>
> **Step 7 视觉终局完成（2026-11-26）。** Step 3、4.1、4.2、4.2.1、4.3、5、6 均已验收；
> 用户在真机上跑完 24 分钟全片后提出 6 条视觉/交互整改，本轮全部落地：
> 暗色改 FCP 式四阶碳灰（§7.10 一）、亮色翻转成纸白台面 + 凹陷填充（一）、
> 标题栏外观一键直切（二）、侧栏去 ①②（三）、朗读面板重排（四）、导出页三处细节（五）、
> 单栏页面居中（六）；顺带修掉紧凑模式四条从未生效的死样式（七）。
>
> 以下是 Step 6 的记录：
>
> Step 3、4.1、4.2、4.2.1、4.3、5 均已验收；
> 用户用 `KikuSub-Next.app` 跑通真实片源后报回 **1 个崩溃 Bug + 4 处界面/排版问题**，
> 本轮全部根治：ASR 空闲卸载租约（§7.9 一）、导出页/转写页去套娃（§7.9 二 1-2）、
> 朱红质检徽标（二 3）、朗读 ⚙ 面板 348px 溢出（二 4）、检查器底部收尾区（二 5）。
> `tools/shots/verify_*.mjs` 27 个脚本全绿（新增 `verify_tts_panel_fit`，`verify_review_overlays` 的
> menu / dialog 两个模式另各跑一次也绿）。
>
> 本轮不是“把现有页面修漂亮”，而是换一套**界面语言 + 页面骨架 + 任务顺序**。
> 视觉世界叫 **Cue Script（录音台本）**；完整令牌与组件规则见根目录 [DESIGN.md](../DESIGN.md)，
> 产品事实见 [PRODUCT.md](../PRODUCT.md)。

## 0. 新会话从这里开始

**5 分钟读法**：§0.1 看红线 → §1 看当前状态 → §2 看不可动摇的用户路径 → §7 看下一步 → §8 跑验收命令。
**不要做**：不要动 `core/`、`server/`；不要打开任何窗口（§8.3）；不要覆盖用户本机现役的
`KikuSub.app` 或其 `settings.json` / `userData`（§0.1）。
**产物位置**：本文是主台账；截图在 [images/refactor-2026-11/](images/refactor-2026-11/)；原型在
工作区 `.impeccable/prototype/`（不在仓库内，不随包发布）。

### 0.1 铁律：与现役旧版双开共存，绝不覆盖

用户的日常主力是**本机当前已安装的旧版 KikuSub**。重构产物必须能在同一台 Mac 上并行存在、
各自双击打开；任何一步都不得污染旧版的安装、配置或运行数据。**四条硬约束**：

1. **不覆盖已安装的 `.app`。** 严禁向 `/Applications/KikuSub.app`、`build/pack/KikuSub.app`
   或任何现役打包路径写入。未来构建试用版必须换**独立的产物名与独立 bundleId**
   （`KikuSub-Next.app` / `com.github.kikusub.next` 之类），让新旧两款可长期共存。
   本仓库现有的打包脚本默认产物就是现役名，**未经用户逐次确认不得运行**。
2. **配置与运行数据隔离。** 新界面的状态（外观偏好、界面缓存、预留的布局记忆）不得写进旧版
   正在使用的 `settings.json`、`presets.json`、Electron `userData` 目录或 `~/.agents/skills/`。
   验证与并行体验一律走**独立数据根**：`KIKUSUB_DATA_DIR` / `KIKUSUB_PREFERENCES_PATH` /
   `--user-data-dir`（见 `tools/shots/` 下各脚本），默认指向系统临时目录。
   渲染层新增的偏好只进 `localStorage`（每个 `--user-data-dir` 天然隔离），不进共享配置文件。
3. **Git 保护。** 第一阶段在 `feat/ui-redesign`；第二阶段从 `feat/ui-redesign-p2` 继续，
   后者可以推远端备份。`backup/pre-ui-redesign-2026-11` 与
   `archive/pre-ui-redesign-2026-11-25` 是两个只读锚点，**不删除、不移动、不 rebase**；
   不推 tag、不碰 `main`。
4. **不卸载、不重装、不改名旧版。** 不执行 `defaults write`、不改旧版的 Launch Services 注册、
   不动它的签名与图标。新旧共存靠新产物的独立标识实现，不靠改旧版。

> **现成机制（2026-11-26）**：`bash tools/pack/build_trial.sh` 产出
> `build/pack-next/KikuSub-Next.app`（bundle id `com.kikusub.desktop.next`，数据根
> `~/Library/Application Support/KikuSub-Next`），实现上面第 1–2 条；正式发版脚本的默认
> 产物与身份一字未改。机制与试用注意事项见 §7.8 与
> [desktop-lifecycle §3.6](contracts/desktop-lifecycle.md)。

## 1. 当前状态

| 项 | 状态 | 证据 / 位置 |
| --- | --- | --- |
| 备份分支 | ✅ 已建 | `backup/pre-ui-redesign-2026-11` @ `74fd5dc` |
| 备份标签（非 `v*`） | ✅ 已建 | `archive/pre-ui-redesign-2026-11-25` |
| 开发分支 | ✅ 已切 | `feat/ui-redesign` |
| 产品事实 | ✅ 已写 | [PRODUCT.md](../PRODUCT.md) |
| 视觉世界 / 设计系统 | ✅ 已写，按拍板更新 | [DESIGN.md](../DESIGN.md) |
| 高保真原型 | ✅ 8 张分页图 + 1 张对比图 | [images/refactor-2026-11/](images/refactor-2026-11/) |
| macOS HIG 审查 | ✅ 初版 | §6 |
| 机械检测 | ✅ 已跑 | `impeccable detect`；见 §5.4 |
| 用户拍板（§9） | ✅ 已确认（2026-11-25） | §9 已冻结为决定，不再是待问项 |
| 旧版共存 / 数据隔离铁律 | ✅ 已写入 | §0.1 |
| **Step 3A 令牌** | ✅ 完成 | `app.css` 换成 Cue Script；外观模型 `auto/light/dark` + `data-cue-font` |
| **Step 3B 外壳** | ✅ 完成 | 整幅标题栏 44px、侧栏 232/52 四段、底栏 24px 只读、菜单补齐 |
| **Step 3C 转写页样板间** | ✅ 完成 | 01/02/03 + 44px 页边 + 右栏 + 任务条；见 §5.6 |
| **Step 3 验收修正** | ✅ 完成 | 日间蓝提纯为钴蓝 `#0B63E5`；分段选中态改白色凸起胶囊；选中卡片改纸白 + 蓝边；见 §7.3.1 |
| **Step 4.1 纯结构拆分** | ✅ 完成 | ReviewView 2583 → 1769；查找 / 浮层 / 纯计算分到 lib 与 components；0.000000% 像素差；见 §7.4 |
| **Step 4.2 核对台精修** | ✅ 验收通过 | 44px cue 页边接通、检查器去重、走带/浮层精修；ReviewView 1769 持平；见 §7.5 |
| **Step 4.2.1 译文轨状态条** | ✅ 完成 | 两行散件并成一条 24px 状态条 + `⋯` 菜单；CuePane 748→629；见 §7.5.1 |
| **Step 4.3 组一 准备与复核** | ✅ 完成 | 导入页「继续当前工程」卡；双引擎复核收进台本纸；见 §7.6 |
| **Step 4.3 组二 原文加工** | ✅ 完成 | 侧栏 ① ② 编号；AI 三页 note 槽与互相指路；见 §7.6 |
| **Step 4.3 组三 交付** | ✅ 完成 | 「暂无译文轨」收敛成一次；成片预览按监看器；导出完成补回核对台；见 §7.6 |
| **Step 4.3 组四 辅助/边界** | ✅ 完成 | 设置页去彩图标；内核未连接可手动重启；修 `.sb-item` 类名撞车；见 §7.6 |
| 生产验证 | ✅ 全绿 | `check` / `check:svelte`（4/4 基线）/ `build` / `test:main`（**405**）/ `pytest -q`（**1096** passed / 2 skipped）/ `verify_phase2_shell`（**64** 项）/ 全量 `verify_*.mjs` 见 §8.12 |
| **章节端点排雷** | ✅ 完成 | `verify_chapter_edge` 10/10；测试前置 + `ChapterTrack.visible` 两处修复，见 §7.8 |
| **双开试用版** | ✅ 已打包 | `build/pack-next/KikuSub-Next.app` / `com.kikusub.desktop.next` / 独立数据根；见 §7.8 |
| **真机崩溃 Bug（Anime Whisper 第二版）** | ✅ 已根治 | 空闲卸载与跑片竞态；`EngineIdleReleaser.hold()` 租约 + 解码自愈兜底；见 §7.9 一 |
| **Step 6 去套娃 / 执行栏 / 徽标 / 溢出** | ✅ 完成 | 导出页与转写页零白框套娃；转写页 Docked 执行栏三态；质检朱红胶囊；朗读面板两行布局；见 §7.9 二 |
| **Step 7 色板重写（FCP 碳灰 / 纸白台面）** | ✅ 完成 | 暗色四阶 `stage→canvas→inspector→paper→raise`；亮色 `canvas=#FFF` + `well` 凹陷填充；新增两条命名规则；见 §7.10 一 |
| **Step 7 标题栏一键直切** | ✅ 完成 | `flipAppearance()` 两态翻转，`auto` 只留设置；补一条单测；见 §7.10 二 |
| **Step 7 侧栏去 ①②** | ✅ 完成 | `ordinal` 字段整条删除；页内指路保留文案；见 §7.10 三 |
| **Step 7 朗读面板重排** | ✅ 完成 | 去重复标题与 `×`、`管理` 换铅笔、两行等分网格、面板退成 well；见 §7.10 四 |
| **Step 7 导出页细节 + 居中** | ✅ 完成 | 发丝线呼吸、裸蓝字改 `.btn.soft`、单栏页面 `--measure-page` 居中；见 §7.10 五/六 |
| **Step 7 死样式修复** | ✅ 完成 | 紧凑模式 `.player/.table-area/.transport` 从父组件搬回各自组件；ReviewView 1764；见 §7.10 七 |
| **第二阶段 Batch 1 导入页融合** | ✅ 完成 | 删「继续核对 / 换片…」卡，恢复大拖放区主视觉；顺序回到 拖放区 → 代理说明 → 导出文件夹 → 最近打开；按钮去 `…`；见 §8.10 |
| **第二阶段 Batch 2 令牌治本 + AI 三页** | ✅ 完成 | `--well-line` 亮 0.14 / 暗 0.13；页内工具栏回 `--canvas` + 发丝线；`--font-cue` 日语优先；锁轴 / 重排 / 双语三页去灰带、粘贴区与表格精修；新增 22 条控件可见性断言；见 §8.11 |
| **第二阶段 Batch 3 六套双模色板 + 打包推送** | ✅ 完成 | `data-palette` 与 `data-theme` 正交；6 套 × 2 明暗；18 组派生令牌改 `color-mix`；设置页「界面配色」6 张卡；Canvas 2d `color-mix` 解析；12 组合全量对比度；见 §8.12 |
| 骨架回归 | ✅ 全绿 | `verify_phase2_shell`（46 项）+ `verify_transcribe_flow`（21 项） |
| 核对台 | ✅ 4.2.1 完成 | 页边 / 表格 / 检查器 / 走带 / 浮层按 Cue Script 重排；整轨区并成一行；见 §7.5 / §7.5.1 |
| 旧文档指针 | ✅ 已加 | [ui-refactor-plan.md](ui-refactor-plan.md) / [界面设计优化分析-2026-11.md](界面设计优化分析-2026-11.md) 顶部 |

### 1.1 这轮和上一轮的区别

上一轮（[ui-refactor-plan.md](ui-refactor-plan.md)）是**在既有“青空”皮肤上做 8 个单点优化**；
这一轮是**替换视觉世界 + 重排任务顺序**。两者的关系：

- 上一轮已完成/已作废的项不再重做；它的 Step 1–8 大多已经落地（侧栏分组、专家抽屉、AI 三页统一工作条、
  双引擎去噪、导出/设置收敛）。
- 上一轮未做的 7 条视觉差距（控件高度、圆角、字阶令牌率、动效、断句重排布局、检查器末行、
  设置值列）不再单独开题，统一收进本轮的设计系统。
- 旧文档保留为历史记录，**不按它继续改代码**。

## 2. 底线：用户的功能逻辑顺序

### 2.1 灵魂路径

```
导入 → 转写 → 核对台 → 双引擎复核
                     → 原文加工：① 锁轴润色 → ② 重排润色
                     → 交付：③ 双语翻译 → 导出
```

三个原则：

1. **每一步只回答一个问题**：我现在在哪、这一步要做什么、做完之后去哪。
2. **主操作永远在内容里**，不在底栏、不在“更多”菜单里；底栏只放只读状态。
3. **顺序不是装饰**：侧栏分组、页面标题、下一步按钮、空态文案必须说同一件事。

### 2.2 命名决定

| 旧名 | 新名 | 它真实做什么 | 风险 |
| --- | --- | --- | --- |
| 润色 | **锁轴润色** | 1:1 改文字，条数与时间码不动；`apply_polish()` 保护时间轴 | 低 |
| 断句重排 | **重排润色** | 可改条数、断句与时间码；整段替换 SRT，带体检与越界警告 | 高（动轴） |
| 翻译 | **双语翻译** | 生成/回填译文平行轨，不改原文 | 中 |

**为什么“锁轴 / 重排”这两个词是对的**：它们把“改不改时间轴”这个真正的分界说出来了。
用户不需要先理解 digest、SRT 替换或结构校验，只需要知道“这一页会不会动我的轴”。

### 2.3 合并还是两页：建议两页

用户提出的“1 和 2 合并成一个「原文润色」页内切换”是合理的直觉，但**本轮建议两页**，理由按重要性排序：

1. **数据契约不同。** 锁轴是 1:1，服务端只接受同条数的文本；重排是整段 SRT 替换，
   条数、切分、时间码都可变。把它们塞进一个页面的两个模式，等于把两套校验、两套失败态、
   两套历史入口装进同一个组件，最容易出现“以为在润色，其实在重排”。
2. **风险等级不同。** 重排会动轴；它需要体检、越界警告、条数腰斩二次确认。锁轴不应该
   继承这些红色警告，否则用户会以为“改个字也有风险”。
3. **工具不同。** 锁轴的核心是 A/B/AI 三栏逐条对照；重排的核心是粘 SRT、分段计划、体检。
   两者的主视区、头部、底部应用条不是同一套。
4. **用户的心智是递进，不是二选一。** 绝大多数人先做锁轴；只有“断句本身错了”才进重排。
   两页 + 编号 + 互相指路，比一个模式开关更符合这个顺序。

**落地方式**（不是两个孤立页面）：

- 侧栏同一组 `03 原文` 下：`锁轴润色`、`重排润色`，标题旁标 `①` / `②` 或直接写“先锁轴，后重排”。
- 锁轴页头写“只改文字，不动时间轴”；右上角一个安静的入口：“需要改断句？→ 重排润色”。
- 重排页头写“会改条数与时间码”；右上角反向指路：“只改文字？→ 锁轴润色”。
- 如果未来数据显示 90% 的用户只用其中一页，再评估合并；现在不合并。

### 2.4 导航：四段，快捷键不动

| 段 | 项 | 快捷键 | 说明 |
| --- | --- | --- | --- |
| 01 准备 | 导入 | ⌘1 | 继续当前工程，或换片 |
|  | 转写 | ⌘2 | 产出 / 范围 / 引擎 / 开始 |
| 02 核对 | 核对台 | ⌘3 | 视频 + 波形 + 字幕表 + 检查器 |
|  | 双引擎复核 | ⌘4 | A/B 差异，只呈现真正不同的行 |
| 03 原文 | 锁轴润色 | ⌘5 | 只改文字 |
|  | 重排润色 | ⌘6 | 可改断句与时间码 |
| 04 交付 | 双语翻译 | ⌘7 | 译文平行轨 |
|  | 导出 | ⌘8 | 字幕 / 成片 |

**关键决定：⌘1–⌘8 的顺序不变**。只改名称与分组（“AI 处理”拆成“原文”和“交付”），
因为主进程菜单、`shortcuts.svelte.ts`、设置页快捷键说明和用户肌肉记忆都绑在这个顺序上。
`重排润色` 仍在 `锁轴润色` 后面，正好符合用户的自然顺序，不需要顺延。

### 2.5 逐页巡检：用户此刻的问题 → 页面怎么回答

| 步骤 | 用户此刻的问题 | 现状断点 | 本轮改法 |
| --- | --- | --- | --- |
| 导入 | “我上次干到哪了？换片还是继续？” | 导入页的主视觉仍是“拖入文件”；已有工程时没有“继续”主操作 | 顶部**继续当前工程**卡（上次位置 / 继续核对），拖入降为第二动作；底部“从导出文件夹继续” |
| 转写 | “这次产什么？跑哪段？用哪个引擎？跑完去哪？” | 完成后主 CTA 只有双引擎场景的“查看差异”；普通完成没有“去核对台” | 右侧“现在的稿”常驻**去核对台**；完成态在结果条里再给一次；上次这一趟可一键载入 |
| 核对台 | “这一句对不对？时间轴要不要动？下一句在哪？” | 检查器 348 px 偏挤；表格被右栏挤窄；视频和表面比例不够稳 | cue margin 统一状态 + 检查器去重 + 外框留白压到 16px（Step 4.2 落地，见 §7.5）。**原计划的「舞台行 + 388 px 检查器 + 全宽表格」没有采纳**：它会把字幕列再让出 40px，1080 最小窗口下只剩 124px；是否改成舞台行留给后续评估 |
| 双引擎复核 | “哪几行真的不一样？要不要采用 B？” | 标点噪声已默认过滤；但页头/行内动作与核对台不是同一骨架，行内试听/采用还能更轻 | 保留“忽略标点”；差异行右侧轻量试听/采用；页头与核对台同骨架 |
| 锁轴润色 | “AI 改了什么？会不会动我的轴？怎么退回？” | 与“断句重排”名字太像；锁轴/重排的真正差别只写在正文里 | 改名；页头锁图标 + “时间轴锁定”；A/B/AI 三栏同基线；应用条写明“条数不变” |
| 重排润色 | “改完条数会变吗？时间码会不会错位？” | 名字不说明风险；入口与锁轴混在一起 | 改名；页头明写“会改条数与时间码”；体检/越界警告前置；与锁轴互相指路 |
| 双语翻译 | “译文和原文怎么对？补译会不会覆盖已核对？” | 与“原文润色”混在 AI 处理组；补译入口不够显眼 | 归入“04 交付”；原文/译文/双语三态清楚；补译只写待译条 |
| 导出 | “我该导字幕还是成片？设置会不会丢？” | 页面很长；同一句“暂无译文轨”出现两次；主操作不够跳 | 先给“字幕 / 成片 / 仅封装”三条清楚路径；无译文时一次提示；底部说明收敛 |

> **2026-11-26 更新**：导入页那一行的「顶部继续当前工程卡，拖入降为第二动作」已在
> 第二阶段 Batch 1 撤销——导入页回到大拖放区主视觉，见 §8.10。其余行仍是现行口径。

### 2.6 跨页接力（这次必须修）

- 转写完成：`状态条 + 去核对台`，不是只给“查看差异”。
- AI 采纳：回到核对台时定位到刚改的那一条，并保留滚动位置。
- 导入：已有工程时先给“继续核对”，再给“换片”。
- 导出：从核对台/双语翻译进入时，带上当前范围与轨道；导出成功后给“打开文件夹 / 回到核对台”。
- 任何失败：错误信息说“哪一句 / 哪个文件 / 怎么恢复”，不弹无信息的 modal。

## 3. 视觉世界：Cue Script

### 3.1 七个候选（按与产品的共振排序）

| # | 世界 | 为什么共振 | 它长什么样 |
| --- | --- | --- | --- |
| 1 | **光学声轨** | 产品的核心是声音与时间；声轨是电影里“声音的形状” | 银盐灰黑、连续波形、一条扫描线 |
| 2 | **字幕校对本** | 产品就是一张校对本：时间码、原文、译文、朱笔 | 冷纸、墨、蓝铅笔、朱笔 |
| 3 | **录音台本** | 配音/字幕前期都用它：条号、时间、台词、备注、检印 | 淡蓝纸、墨、页边记号、朱印 |
| 4 | **新干线运行图** | 时间是连续轴，车次是块，章节是站 | 纸底、墨线、信号红/绿、密集刻度 |
| 5 | **电影片头倒计时** | 帧、秒、片头对位；天然适合播放头 | 黑白、圆环、帧号 |
| 6 | **日语组版 / 原稿纸** | 日文字体、行距、ruby、栏线 | 纸、墨、红色栏线 |
| 7 | **节目表 / EPG** | 时间 × 频道的网格，适合长片 | 密集网格、频道色 |

**被分配的是 #3（录音台本）**。它不是我的第一选择（#1 光学声轨更像“电影”），
但 concept-seed 的分配价值就在这里：它逼我从“最像电影”的直觉里退一步，选一个**更贴近字幕工作本身**的物件。
录音台本同时具备纸、墨、页边、检印四种材料，能给出一套在亮/暗两种光线下都成立的系统，
而且不会滑向“暗色 NLE + 琥珀”的现成答案。

### 3.2 挑战者判定（六个 catalog 世界）

| 挑战者 | 判定 | 保留的一条纪律（donation） |
| --- | --- | --- |
| 登机牌 + 登机口翻牌 | declined | **变更状态要留住**：一句被改过的字幕，在被看到之前一直带标记 |
| 暗色开发者控制台 | declined | **危险动作要隔离**：删除/覆盖离开主按钮，隔一条发丝线和 16 px 空气 |
| 机场黄色导视 | declined | **每个路口只给下一个决定**：右栏只回答“现在去哪”，不是功能清单 |
| 同人展目录 | declined | **整格密度 + 已访问标记**：表格是密集的，但每行都有页边记号 |
| 植物图谱 | declined | **同基线对比**：原文/建议/采用后三栏必须逐行对齐 |
| 可变字体样本 | declined | **实时数字读数**：时间码、缩放、帧率始终是等宽、即时更新的 |

这些纪律都进了设计：cue margin、隔离的删除、右栏“下一步”、三栏对齐、等宽读数。

### 3.3 世界只借四件事

按 Operate 模式的限制，世界只提供**字体、色板、密度、一个签名动作**；导航与控件仍是 macOS 标准件。

- **字体**：系统 SF / PingFang / Hiragino；时间码 SF Mono。
- **色板**：冷纸、墨、蓝铅笔、朱笔；不用琥珀，不用霓虹。
- **密度**：30 px 表格行、11 px 数据、1 px 发丝线、页边 44 px。
- **签名动作**：**cue margin**。左缘 44 px 是台本的页边：已核打勾、AI 蓝铅笔、待核朱点；
  当前句在页边落一道 2 px 朱线，编号转朱。它同时是状态、导航和“校对本”的记忆点。

**为什么不是概念 A/B/C**：那三套是 11-24 的探索稿，用户明确不喜欢；它们也都滑向了
“暗色 NLE + 浮层卡片”的现成答案。本轮不参考它们的配色与布局。

**为什么不是 Final Cut / Linear / IINA 的皮肤**：它们是 craft bar（工艺水平），不是 world。
我们借它们的克制、密度、键盘优先，不借它们的紫/靛/蓝皮肤。

### 3.4 明暗不是“主题”，是房间

- **Light / 日间校样**：冷纸桌面、纸面、墨、蓝铅笔。用于白天、校对、导出前的通读。
- **Dark / 夜间配音间**：近黑画布、暖纸白文字、电影画面是唯一亮面。用于晚上、长时间核对。
- **Mincho / 明朝校样**：同一套 light 纸面，只把 `--font-cue` 换成 Hiragino Mincho；
  它是**字幕字体偏好**，不是第三套配色。

**已拍板的外观模型（2026-11-25，替代原来的三主题）**：

| 层 | 取值 | 默认 | 落点 |
| --- | --- | --- | --- |
| 外观（appearance） | `auto` / `light` / `dark` | `auto`（跟随系统） | 设置 → 外观；`nativeTheme.themeSource` 同步 |
| 字幕字体（cue font） | `sans` / `mincho` | `sans`（黑体） | 同一页的独立一行，与明暗正交 |

- 明暗**不再占用主题位**：`html[data-theme]` 只有 `light` / `dark` 两个值，由「外观偏好 ×
  系统外观」解析得出；第三套「明朝墨」配色作废，明朝只改 `--font-cue`。
- HIG（`dark-mode.md › Best practices`：“Avoid offering an app-specific appearance setting.”）
  的落法：**默认跟随系统**，手动覆盖是设置里的显式选项而不是工具栏上的常驻开关；
  解释文案写明「一般不用动它」。
- 迁移：旧版 `localStorage['kikusub.theme']` 的 `mincho` → `appearance: 'auto'` +
  `cueFont: 'mincho'`；`cool` 同理；`light` / `dark` → 同值 appearance。旧值读完即迁，不双写。

## 4. 设计系统摘要

完整规则见 [DESIGN.md](../DESIGN.md)。这里只放执行时最常查的几张表。

### 4.1 表面与颜色

| 角色 | Light | Dark | 用途 |
| --- | --- | --- | --- |
| Canvas | `#EDF1F5` | `#0B0E11` | 桌面/画布 |
| Panel | `#F7F9FB` | `#12161A` | 侧栏、工具栏、检查器 |
| Sheet | `#FFFFFF` | `#171C21` | 字幕表、输入框 |
| Ink | `#15191C` | `#ECE8DF` | 主文字 |
| Graphite | `#4A545C` | `#B3B8B8` | 次级文字 |
| Blue pencil | `#0B63E5` | `#84A9E6` | 操作/选中/AI |
| Vermilion | `#B8412F` | `#E07A66` | 更正/待核/当前句 |
| Approved | `#356B52` | `#7FB89B` | 已核/通过 |
| Attention | `#7E5416` | `#D2A15E` | 低置信/提醒 |
| Hairline | `#CCD5DC` | `#2A3238` | 1 px 分隔 |

实测对比度（Step 3 落地后由 `verify_phase2_shell.mjs` 在真实渲染器里算，不是估的）：

| 令牌 | 浅色 on 纸面 | 深色 on 纸面 |
| --- | --- | --- |
| `--ink` 正文 | 16.75:1 | 14.86:1 |
| `--ink-2` 次级 | 7.33:1 | 9.06:1 |
| `--ink-3` 11px 标签 | **6.02:1** | **6.75:1** |
| `--accent-text` 蓝铅笔 | 5.06:1 | 7.62:1 |
| `--danger` 朱笔 | 5.19:1 | 6.18:1 |
| `--line` 发丝线 | 1.33:1（可见即可，非文字） | 1.54:1 |

Step 3 把 `--ink-3` 从 `#5E6A72`（5.45:1）压深到 `#566168`（6.35:1 on 台本 / 6.02:1 on 纸面），
深色从 `#858F96`（5.2:1）提到 `#959FA8`（6.37:1）：11px 数据不再贴着 4.5 的底线。

**2026-11-25 验收修正后的日间实测**（同样由 `verify_phase2_shell.mjs` 在真实渲染器里算）：

| 令牌 | on 台本 `#FFFFFF` | on 纸面 `#F7F9FB` | on 画布 `#EDF1F5` |
| --- | --- | --- | --- |
| `--accent-text` `#0B63E5` | **5.34:1** | **5.06:1** | **4.71:1** |
| `--on-accent` 白字落主按钮 | — | — | **5.34:1** |
| `--ink-3` `#566168` | **6.35:1** | **6.02:1** | 5.60:1 |

三段都 ≥4.5:1。旧 `#2D5FA6` 虽然对比更高（6.24），但低彩度叠在冷灰底上会显脏；
新值把彩度提上来、明度保持在「可读且不发灰」的区间，并用同一组实算守住 AA。

### 4.2 字阶

| 角色      | 字号/行高          | 用途              |
| ------- | -------------- | --------------- |
| Display | 22/30 · 620    | 页面标题            |
| Heading | 15/22 · 600    | 分区标题            |
| Body    | 13/19 · 400    | 正文、控件           |
| Cue     | 21/30 · 500    | 检查器当前句；表格 13/20 |
| Data    | 11/16 · mono   | 时间码、时长、计数       |
| Label   | 11/16 · 0.07em | 列头、阶段、快捷键       |

### 4.3 形状与间距

- 圆角：3（徽章/记号）/ 5（控件）/ 7（面板/表）/ 10（窗口/画面）。
- 间距：4 / 8 / 12 / 16 / 24 / 32。
- 控件：24 / 28 / 32 / 36；表格行 30；cue lane 22；波形 84。
- 表面：canvas / panel / sheet 三层；**不做卡片套卡片**；分隔用 1 px 发丝线，不用 5% 灰。
- 动效：120 ms hover、160 ms 选中、200 ms 抽屉；逐帧/切割/播放零过渡；尊重 reduced-motion。

### 4.4 组件语法

- **按钮**：Primary（蓝底白字，一屏一个）/ Secondary（纸底 + 发丝线）/ Ghost / Danger（朱字，隔离）。
- **分段**：一个统一控件；灰槽 + 纯白凸起胶囊 + 0.5 px 环 + 极轻投影 + 深墨文字。选中不涂蓝底；蓝色只给主操作、单选圆点与最关键指示器。
- **徽章**：低置信/待核/已核/AI；颜色 + 文字，不靠颜色单独承载。
- **输入**：纸面、1 px 发丝线、聚焦蓝环；时间码输入用 mono。
- **导航**：四段、30 px 行、5 px 圆角；选中 = tint + 1 px 边，不用单侧竖条。
- **检查器**：42 px tabs、发丝线分区、没有嵌套卡；删除在底部单独隔离。
- **底栏**：只读状态（引擎、条数、媒体、缩放、暂存状态、质检计数）；不放主操作。

## 5. 高保真原型

### 5.1 怎么生成的

- 原型是工作区 `.impeccable/prototype/` 下的**静态 HTML/CSS/JS**（不是生产 Svelte，不随包发布）。
- 截图用 **headless Chrome**，1440×900、2× Retina、无窗口；不启动 Electron、不弹窗。
- 字幕内容取自 README 的《言叶之庭》演示台词（20:15–20:52 的 10 条）与真实片段时间轴；
  画面取自工作区 `测试用_言叶之庭.mkv` 的 20:30 桥下场景（仅作为原型素材，不随包分发）。
  生产验收仍用 `tools/shots/seed.json` 的 12 条占位句。
- 8 张分页图 + 1 张 before/after 已转成 JPG 放进仓库：[images/refactor-2026-11/](images/refactor-2026-11/)。

### 5.2 先看这张：现在 vs 提案

![现在（左）与提案（右）](images/refactor-2026-11/before-after-review.jpg)

左边是当前 README 的核对台；右边是提案的日间校样。看四件事：
视频是否成为画面主角、表格是否拿到整幅宽度、右栏是否只回答“当前这一句”、页边是否开始承担状态。

### 5.3 分页截图

| 页面 | Dark | Light | 看什么 |
| --- | --- | --- | --- |
| 核对台 | [review-dark.jpg](images/refactor-2026-11/review-dark.jpg) | [review-light.jpg](images/refactor-2026-11/review-light.jpg) | 舞台行 + 全宽表格；cue margin；检查器 A/B；波形/播放头 |
| 转写 | [transcribe-dark.jpg](images/refactor-2026-11/transcribe-dark.jpg) | [transcribe-light.jpg](images/refactor-2026-11/transcribe-light.jpg) | 01 产出 / 02 范围 / 03 引擎；右侧“去核对台”；底部任务条 |
| 锁轴润色 | [polish-dark.jpg](images/refactor-2026-11/polish-dark.jpg) | [polish-light.jpg](images/refactor-2026-11/polish-light.jpg) | 锁定轴；三栏同基线；diff 的蓝/朱；应用条 |
| 导入 | [import-dark.jpg](images/refactor-2026-11/import-dark.jpg) | — | 继续当前工程优先；拖入第二；从导出文件夹继续 |
| 设计系统板 | — | [system-light.jpg](images/refactor-2026-11/system-light.jpg) | 色板/字阶/组件/cue margin/四段导航 |

### 5.4 机械检测结果

`impeccable detect` 对 `index.html` + `styles.css` 的最终结果（2026-11-25）：

- `low-contrast`：**0**（`--text-4` 已提亮；`.del` 去掉透明度）。
- `undersized-ui-text`：**0**（状态栏“暂存”改成只读文案后清零）。
- `tiny-text`：**0**（正文 13、数据 11，均高于 macOS 最小 10 pt）。
- `cramped-padding`：**5**，全部是表格行 / 视频画面 / 分段控件 / 三栏表这类“本来就不该有内边距”的容器。
- `numbered-section-labels`：**0**（`01/02/03` 只出现在有顺序含义的任务条，不作为装饰）。

这些判断不是“忽略告警”，而是按 Operate 模式的密度/表格语义逐条判定。

**Step 3 的检测口径变了**（2026-11-25）：`impeccable detect` 对 `.css` / `.svelte`
只跑正则规则，元素级规则（`tiny-text` / `low-contrast`）需要解析后的页面。
生产界面必须在 Electron 里才成立（依赖 preload），所以这一轮**用更强的证据替代**：
`tools/shots/verify_phase2_shell.mjs` 在真实渲染器里读计算样式、按 WCAG 公式算比值，
逐项断言正文 ≥7、11px 标签 ≥4.5、蓝铅笔 ≥4.5、发丝线 ≥1.25（数值见 §4.1）。
元素级 detector 留给 Step 5：届时用打包产物 + `--screenshot` 路径做一次完整扫描。

### 5.5 原型没有覆盖的

- 真实键盘焦点环、VoiceOver 顺序、菜单栏命令、reduced motion/transparency。
- 加载/失败/取消/模型下载/代理生成/Sidecar 冷启动等边界态。
- 长片（2 小时、500+ 条）滚动性能、虚拟列表、列宽拖拽。
- 这些不是“设计没做”，而是**必须在真实 Electron 里验证**，留给 Step 3–5。

### 5.6 Step 3 生产截图（真实 Electron，无窗口）

这些不是原型，是 `--screenshot` 从真实应用里取帧（1440×900 @2x，转 JPG）。
生成命令：`bash tools/shots/capture_matrix.sh --theme light|dark|mincho --states "transcribe review"`
（沙箱里加 `KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox`）。

| 看什么 | 图 |
| --- | --- |
| 转写页·日间校样（1360×838） | [step3-transcribe-light.jpg](images/refactor-2026-11/step3-transcribe-light.jpg) |
| 转写页·夜间配音 | [step3-transcribe-dark.jpg](images/refactor-2026-11/step3-transcribe-dark.jpg) |
| 转写页·最小窗口（1080×680，右栏必须在） | [step3-transcribe-light-1080.jpg](images/refactor-2026-11/step3-transcribe-light-1080.jpg) |
| 外壳 + 核对台（本轮未动核对台本身） | [step3-shell-review-light.jpg](images/refactor-2026-11/step3-shell-review-light.jpg) |
| 设置 → 外观与朗读（外观三选一 + 字幕字体） | [step3-appearance-light.jpg](images/refactor-2026-11/step3-appearance-light.jpg) |
| 明朝字幕字体（同一套浅色，只换字幕字） | [step3-cue-mincho.jpg](images/refactor-2026-11/step3-cue-mincho.jpg) |

> **2026-11-25 验收修正后全部重拍。** 日间强调蓝由钢青 `#2D5FA6` 换成钴蓝 `#0B63E5`，
> 分段选中态改为「纯白凸起胶囊 + 极轻投影 + 深墨」，选中卡片改为「纸白底 + 1px 蓝边框」，
> 三层日间表面同步提亮（画布 `#EDF1F5` / 纸面 `#F7F9FB` / 台本 `#FFFFFF`）。
> 重拍命令仍是 `capture_matrix.sh --theme light|dark|mincho --states "transcribe review"`；
> 设置页走 `capture_settings_matrix.sh --only light-appearance`。

看四件事：① 标题栏是否横跨整窗、面包屑是否说清「第几段 / 哪一页 / 这一页什么状态」；
② 三个步骤是否在同一条纸上、左侧 44px 页边是否承担了段号；③ 右栏是否只回答「我现在有什么」；
④ 底栏是否只剩读数。明朝那张要对比字幕（检查器大句 + 表格日文）已经换成 Hiragino Mincho，
而配色、字号、行高一个都没动。

## 6. macOS HIG 审查（apple-design）

审查对象：截图 + 设计系统；框架是 Electron，按 macOS 桌面原则翻译。以下引用均来自
`~/.dsh/skills/apple-design/references/hig/`。

| # | 结论 | 依据 | 处理 |
| --- | --- | --- | --- |
| 1 | 大屏上减少嵌套、保持舒适密度 | `designing-for-macos.md › Best practices`：“Leverage large displays to present more content in fewer nested levels…” | 舞台行 + 全宽表格替代“右侧栏挤窄表格”；不做卡片套卡片 |
| 2 | 工具栏只放一个主操作，且在右侧 | `toolbars.md › Item groupings`：“Only specify one primary action, and put it on the trailing side of the toolbar.” | 顶栏右侧只留“导出”主按钮；其余进 More |
| 3 | 工具栏的每个命令都要能在菜单栏找到 | `toolbars.md › Platform considerations › Desktop (macOS)`：“Make every toolbar item available as a command in the menu bar.” | ✅ Step 3 已补：「文件 → 暂存工作草稿 ⌘S / 恢复工作草稿… / 字幕与代理（导入原文·译文 / 压制代理 / 删除两轨）」「显示 → 撤销历史…」；顺手修了 `menu:punct` 在 preload 里没转发、菜单「清理标点…」是死键的旧 bug |
| 4 | 侧栏不超过两级；别把关键动作放底部 | `sidebars.md › Best practices`：“In general, show no more than two levels…”；“Avoid putting critical information or actions at the bottom of a sidebar.” | 四段是一级；底部只留提示词库/设置，导出不在这里 |
| 5 | 底栏只放只读信息，不放关键动作 | `windows.md › Platform considerations › Desktop (macOS)`：“Avoid putting critical information or actions in a bottom bar…” | 原型已把“暂存”从底栏移除，改成只读“草稿未暂存 · ⌘S”；保存进菜单/工具栏 |
| 6 | 表格要有清楚的选中反馈、可读的列头与截断策略 | `lists-and-tables.md › Best practices`：“Provide appropriate feedback when people select a list item.”；“Use descriptive column headings…” | 选中行 tint + 页边朱线；列头 11 px；长文本省略号；保留 30 px 行高 |
| 7 | macOS 默认 13 pt、最小 10 pt；正文 4.5:1 | `accessibility.md › Vision` 表；`dark-mode.md › Dark Mode colors` “no lower than 4.5:1” | 正文 13、数据 11；浅/深实测均 ≥4.5；小字 7:1 目标留给 Step 3 |
| 8 | 不要自定义窗口外观 | `windows.md › Best practices`：“Avoid creating custom window UI.” | 生产用原生 `hiddenInset` + 原生红绿灯；原型里的红绿灯只是截图示意 |
| 9 | 不建议应用自己提供明暗开关 | `dark-mode.md › Best practices`：“Avoid offering an app-specific appearance setting.” | **建议正式版跟随系统 Auto**；设置只留“字幕字体：黑体/明朝”。需你拍板（§9） |
| 10 | 系统字体优先；键盘/焦点/VoiceOver 必须可用 | `typography.md › Using system fonts`；`accessibility.md` | 用系统 SF/PingFang/Hiragino；Step 3 补 `:focus-visible`、菜单命令、VoiceOver 标签 |

**已知未验证**：菜单栏、键盘全路径、焦点环、VoiceOver、reduced motion/transparency。
静态截图不能证明这些；Step 3/5 必须在真实 Electron 里逐项验收，不能写“已通过”。

## 7. 五步路线与状态

| Step | 内容 | 状态 | 验收 / 产物 |
| --- | --- | --- | --- |
| 0 | 备份 + 分支 + 产品事实 | ✅ | 备份分支/tag；`feat/ui-redesign`；[PRODUCT.md](../PRODUCT.md) |
| 1 | 方案 + DESIGN.md + 高保真原型 | ✅ | 本文；[DESIGN.md](../DESIGN.md)；8 张截图；HIG 审查；detector |
| 2 | 用户拍板（§9 三问） | ✅ 已拍板 | 用户 2026-11-25 确认；见 §9 |
| 3 | 令牌 + 外壳 + 样板间（转写页） | ✅ 完成 | `app.css` 令牌/基础控件；标题栏/侧栏/底栏；转写页整页；§7.3 验证全绿 + §5.6 截图 |
| 4 | 核对台拆分 + 精修；AI 两页；其余页 | 🟡 4.1 / 4.2 完成，4.3 待做 | 4.1：ReviewView 2583 → 1769，0.000000% 像素差（§7.4）；4.2：页边 / 检查器 / 走带 / 浮层（§7.5） |
| 5 | 终局审计 + 动效 + 基线 | 待做 | `check` / `check:svelte` / `build` / `verify_*` / `capture_matrix`；基线刷新 |

### 7.1 Step 3 的具体顺序

1. **3A 令牌与基础控件**：把 `app.css` 的 `html[data-theme]` 令牌换成 Cue Script；
   按钮/分段/输入/徽章/焦点环统一；外观模型落地（`auto` / `light` / `dark` + `cueFont`）。
2. **3B 外壳**：整幅标题栏 44px（红绿灯安全区 87px）、侧栏 232/52、四段导航、
   底栏 24px 只读；同步主进程菜单与快捷键标签。
3. **3C 样板间：转写页**：按截图重排 01/02/03 + 右栏 + 底部任务条；这是“功能顺序”的第一块试金石。
   同时把 44px cue margin 的**几何与语义**沉进 `app.css`（核对台接线留到 Step 4）。
4. **验收**：`npm run check` + `check:svelte` + `build`；`capture_matrix.sh` 截转写页明暗两套；
   `read_image` 自查；停下等确认。

**本轮刻意不碰**：`ReviewView.svelte` 与核对台内部（表格 / 检查器 / 波形 / 舞台）、
`PolishView` / `ReshapeView` / `TranslateView` / `ExportView` 的布局（只改页面标题文案）、
`core/` 与 `server/`。

### 7.3 Step 3 落地记录（2026-11-25）

**3A 令牌与外观**

- `desktop/renderer/src/app.css` 整体重写：冷纸/纸面/台本三层表面、蓝铅笔/朱笔两色、
  1px 发丝线、尺寸骨架（标题栏 44 / 底栏 24 / 侧栏 232·52 / 检查器 348（当时写 388，见 §7.5）/ 行 30 /
  cue 页边 44 / 波形 84）、字阶（13/19 正文、11/16 数据与标签）、圆角 3/5/7/10。
  新增 `--rule`（实色发丝线）、`.cue-sheet` / `.cue-margin` / `.cue-mark` 三个 cue 页边原语
  ——**只落几何与语义，核对台接线在 Step 4**。
- 外观模型：`lib/themes.ts` 收敛为 `light | dark` + `AppearanceId = auto|light|dark` +
  `CueFontId = sans|mincho`；`lib/appearance.ts` 放读取/迁移/写 DOM 的纯函数（8 条单测）；
  `lib/appearanceState.svelte.ts` 放响应式状态与落地，并把解析值镜像回 `app.theme`
  （核对台波形只认它，避免动 `ReviewView.svelte`）。
- 主进程：`window:set-theme` → `window:set-appearance`（`nativeTheme.themeSource` 在 auto 时
  真正设为 `system`）；偏好落 `preferences.appearance`，旧 `preferences.theme` 只读迁移。
- 设置 → 外观与朗读：三张外观卡（跟随系统 / 日间校样 / 夜间配音）+ 两张字幕字体卡；
  旧的 `ThemePicker` / `ThemePreviewCard` 删除。`theme-preview.test.mjs` 改成对账两块外观 +
  断言「明朝只允许声明 `--font-cue`」。

**3B 外壳**

- `App.svelte`：`titlebar` 升到 `.shell` 顶层（横跨整窗），下面才是 `sidebar + main`；
  原生红绿灯永远落在标题栏左侧 87px 安全区里，侧栏不再为它让位。
- `Toolbar.svelte` → 标题栏：文档（片名 + 规格 + 代理状态）/ 面包屑（段号 + 页名 + 本页状态）/
  动作区（引擎胶囊、核对台动作、撤回/重做/历史、外观、检查器）。
- `Sidebar.svelte`：四段 `01 准备 / 02 核对 / 03 原文 / 04 交付`，段标等宽小字；
  名字与分组来自新文件 `lib/viewMeta.ts`（标题栏面包屑、菜单、快捷键面板共用一份）。
- `StatusBar.svelte` 24px 只读；`DraftDock` 只报「已暂存 20:22 · 12 条」，
  暂存 / 恢复进「文件」菜单（⌘S）。
- `main.cjs`：红绿灯 `y` 18 → 16（44px 标题栏中线 22 = 灯中线），菜单视图名同步新命名。

**3C 转写页样板间**

- `TranscribeView.svelte`：`PageHeader`（转写 + 任务报告/快捷键）+ 三步（左侧 44px 页边的
  `01/02/03`）+ 320px 右栏 + 吸附任务条；不再使用卡片。
- `EngineChoiceCards` → `EngineChoiceList`（两行主力 + 其他引擎 chips）；
  `RunDock` / `TranscriptState` / `ExpertParamsDrawer` 按新令牌重排。
- 所有既有行为保持不变：产出三档、写入方式、区间、绝对时间轴、人声分离、格式、
  双引擎流向、专家参数折叠、任务报告入口。分段控件补 `aria-pressed`。

**验证（全部无窗口）**

```text
npm run check          ✅
npm run check:svelte   ✅ 5/5（基线持平）
npm run build          ✅
npm run test:main      ✅ 378 passed（新增 appearance 8 条、theme-preview 2 条）
pytest -q -m "not integration"  ✅ 1058 passed / 2 skipped
node tools/shots/verify_phase2_shell.mjs     ✅ 43 项（结构/对比度/舞台/紧凑模式）
node tools/shots/verify_transcribe_flow.mjs  ✅ 21 项（产出/区间/跨页/章节/推荐）
```

**顺手修的旧问题**

- 菜单「清理标点…」是死键：主进程发了 `menu:punct`，`preload.cjs` 的 `onMenu` 从来没转发。
- `capture_settings_matrix.sh` 不带 `--user-data-dir`，截图会写用户真实的
  `~/Library/Application Support/KikuSub`（违反 §0.1）；已隔离，并支持 `KIKUSUB_SHOT_ELECTRON_ARGS`。
- `capture_matrix.sh` / `capture_ai_workbench.mjs` 的 `--theme mincho` 改走
  `data-cue-font`（旧参数名与文件名后缀保留）。

**明确留给后面**

- 核对台：表格 44px 页边接线、检查器、波形（Step 4，先纯拆分）。
- AI 三页 / 导入 / 导出 / 双语 / 设置其余页的视觉（Step 4）；设置左侧页签仍用旧的彩色图标。
- 元素级 `impeccable detect`（需要打包产物，Step 5）。
- 真实键盘全路径 / VoiceOver / 菜单逐项点击（无窗口条件下做不到，Step 5 用静默断言补）。

### 7.3.1 Step 3 验收修正（2026-11-25）

用户看过真实截图后确认骨架、标题栏安全区、三步结构与信息主次都通过，只提一个视觉问题：
**日间模式的蓝「脏脏的、暗暗的、不够通透」**。按三条意见在执行层修正，不换世界：

1. **提纯并提亮日间强调蓝。** `--accent` / `--accent-text` 从低彩度钢青 `#2D5FA6` 换成
   专业钴蓝 `#0B63E5`，`--accent-hover` 用 `#0952C4`。真实渲染器实算：**5.34:1 on 台本、
   5.06:1 on 纸面、4.71:1 on 画布、白字落主按钮 5.34:1**。日间三层表面同步提亮去浊：
   画布 `#E7ECEF → #EDF1F5`、纸面 `#F4F6F6 → #F7F9FB`、台本 `#FCFDFC → #FFFFFF`；
   发丝线 `#C8D1D6 → #CCD5DC`。`verify_phase2_shell.mjs` 新增三条断言（台本 / 画布 /
   主按钮白字）把 ≥4.5 冻住。
2. **分段控件回到 macOS HIG 语法。** `.seg` 选中态不再往灰槽里涂 10% 半透明蓝，改为
   **纯白凸起胶囊 + 0.5px 环 + 1px 极轻投影 + 深墨文字**；`--seg-thumb` /
   `--seg-thumb-shadow` 收进令牌，亮暗两套各自成立。转写页的 `主稿 / 覆盖整片 / 整片 / SRT`
   与工具条紧凑切换共用这一套，蓝色只留在主按钮、单选圆点和最关键指示器上。
3. **选中大卡片改纸白 + 蓝边。** `EngineChoiceList` 的 `.engine.on` 从整行灰蓝底改为
   `--raise` 纸白底 + 1px `--accent` 内描边，文字回到深墨；`Qwen3` 行保持透明，
   只在单选圆点保留蓝色。`--bento-bg-on` 同步从 4% tint 改为纸白（设置页外观卡 /
   引擎卡同样受益）；`APPEARANCE_SHOTS` 与 DESIGN.md 的浅色值一起对账更新。

**验证（全部无窗口）**：`npm run check` / `check:svelte`（5/5）/ `build` / `test:main`（378）
/ `verify_phase2_shell`（46 项，含新增 3 条对比度断言）全绿；`step3-*.jpg` 六张全部重拍，
`read_image` 逐张自查。截图路径见 §5.6。

### 7.2 Step 4 的红线

- **4.1 先拆分，不改 CSS**：✅ 已完成（§7.4）。顶部运控 / 右栏检查器 / 波形工具条此前已是子组件；
  本轮把剩下的查找会话、右键菜单、新建音色浮层与纯 cue 计算分出去；`tests/test_big_file_budget.py` 只降不升。
- **4.2 再精修**：✅ 已完成（§7.5）。按转写页样板重排核对台：44px 页边接通、检查器去重、
  走带与浮层统一；核心区尺寸/行高/单击阈值/`duration/69` 一行没动。
- **4.3 AI 两页**：锁轴先做（风险低），重排后做（风险高）；三栏同基线、diff 蓝/朱、应用条。
- **4.4 其余页**：双引擎、双语、导出、设置、导入；最后补空态/失败/加载。

### 7.4 Step 4.1 落地记录：ReviewView 纯结构拆分（2026-11-25）

**目标**：只拆结构，不碰视觉；守住红线 11（两个大文件只降不升）与红线 6（交互零回归）。
拆前 **2583** 行，拆后 **1769** 行（−814，−31.5%）；`store.svelte.ts` 3217 未动。

**两个 commit**

1. `b65b53e` 纯逻辑先抽（单独 commit，行为不变）：
   - `lib/reviewCues.ts`：二分查时间、画面分块拼行、硬换行拆分 / 表格单行化；
     新增 6 条 `node --test`（`time === end` 不算命中、双语分块、译文缺失回退等）。
   - `lib/reviewViewport.ts`：`snapshotOf()` 收口现场快照；
     `lib/waveformCanvas.ts`：`binsForWidth()` 收口包络采样点数。
2. `2b964fb` 结构拆分（本记录的上一条 commit）：
   - `components/review/ReviewContextMenu.svelte`：右键菜单（切割 / 合并 / 添加 /
     新建音色 / 试听）；打开位置与「合并目标」仍由 ReviewView 判定。
   - `components/review/ReviewVoiceDialog.svelte`：「以此句音频新建音色」浮层，
     含命名 / 参考文本 / 提取请求 / 焦点管理。
   - `lib/reviewFind.svelte.ts`：查找替换整轮会话（命中 / 跳过 / 当前处 / 替换全部）；
     纯计算仍在 `lib/findMatches.ts`。
   - `lib/portal.ts`：两个浮层共用的 body portal（修过「菜单离鼠标太远」）。
   - `tests/test_big_file_budget.py`：ReviewView 预算 **2583 → 1769**。
   - `desktop/test/svelte-check-baseline.json`：**5 → 4**（find props 类型推断收敛，只降不升）。

**验收（全部无窗口，独立 `--user-data-dir`）**

| 项 | 结果 |
| --- | --- |
| `npm run check` | ✅ |
| `npm run check:svelte` | ✅ **4/4**（基线 4，较 5 下调 1） |
| `npm run build` | ✅ |
| `npm run test:main` | ✅ **384**（378 + reviewCues 6） |
| `pytest -q -m "not integration"` | ✅ **1058 passed / 2 skipped**（31 deselected） |
| `verify_review_transport.mjs` | ✅ 全部通过 |
| `verify_reshape_flow.mjs` | ✅ 全部通过 |
| `verify_review_overlays.mjs --mode menu/dialog` | ✅ **12 项 × 2**（新增） |
| 拆分前后像素 | ✅ **0 / 4,558,720 = 0.000000%**（PSNR `inf`；转写页同样 `inf`） |

像素比对方法：同一 `capture_matrix.sh --theme light --states "review transcribe"`、
同种子、1440×900、`--delay 8000` 让工具栏过渡落定；PNG 解码成 RGB24 后逐字节比较。
`--delay 4500` 偶发 13 个像素的工具栏描边过渡差，属于截图时机而非代码；8s 后稳定为 0。

**明确不做**：不动核对台的布局、颜色、行高、单击阈值、`duration/69`、50 步历史；
这些留给 Step 4.2。新组件只搬现有 DOM / CSS，默认页面与浮层截图已 `read_image` 目检。

### 7.5 Step 4.2 落地记录：核对台视觉精修（2026-11-25）

**目标**：把核对台做成真正的 Cue Script 录音台本——44px 页边承担状态、检查器只回答
「这一句现在怎么办」、走带与时间轴回到干净钴蓝 + 白色胶囊、外框留白压到最小。
**红线 6 一条没动**：单击跳转 vs 4px 框选、进度条 click-to-seek、`duration/69` 缩放、
50 步统一历史、`Esc` 只清选区不丢行——下面的回归脚本逐个看住。

**1）页边（签名动作）接通字幕表**

- 表头与每一行共用 `--cue-margin-w`（44px）一列，右缘一条 1px `--rule` 竖线；
  记号 + 序号都在这一列里。当前句落 2px 朱线、序号转朱（朱笔 = 更正 / 待核 / 当前句，
  DESIGN.md 的颜色分工）。
- 三种记号全部来自真实状态（`lib/reviewMargin.ts`，8 条 `node --test`）：
  **待核朱点** = 质检队列里未处理的那一句；**已核打勾** = 对应的质检项已处理；
  **蓝铅笔** = 这一行已经有译文。优先级 `warn > ok > ai`，一条字幕只留一个记号。
- **蓝铅笔只在「原文」模式下画**：双语 / 译文模式里译文已经摊在表里，再点一遍等于每行盖章；
  原文模式里它才是信息（不看译文也知道哪几句译过）。
- 记号来源是质检队列 + 译文轨，**没有新造状态**；`coverage` / `missed` 这类
  「那里本来就没有字幕」的项匹配不到行，页边自然不画（队列总数仍在页签计数里）。

**2）表格成为一张台本纸**

- `.table-area` 用 `.cue-sheet` 原语（纸白 + 1px `--rule` + 7px 圆角），左右只留 16px；
  表头 28px / 11px 标签，时间码 11px mono + `tabular-nums`，行线 `--line`。
- 列宽 `44 | 84 | 84 | 46 | 1fr | 44`（≤1400：78/78/46/40，≤1220：72/72/44/34）；
  页边 + 序列号并成一列后，正文比改造前还宽了 10px。
- 表头里复用了 `.c-text` 类的那一格要显式回到 11px 标签色（否则会继承台本字与正文墨）。

**3）检查器按主次重整（distill）**

- 删掉底部「生效参数（设备 / 引擎 / 版本 / 参数）」与「输出（文件 / 条数 / 字数）」：
  设备与引擎在底栏、条数与字数在底栏、文件名在标题栏——同一组读数出现三次。
  留下的三件事：**质检速览**（只在有漏检 / 低置信时一行）、**当前字幕的来源**
  （只在导入 / 恢复草稿时出现）、**任务报告入口**（参数与版本完整的一份在报告里）。
- 页签 42px，选中 = 深墨 + 2px 蓝铅笔底线（不再涂 `accent-soft`）；计数是等宽数字。
- 检查器里的分段控件删掉本地 `accent-soft` 覆盖，回到全局「灰槽 + 纯白凸起胶囊」。
- 复核 / AI 两块的 CTA 从通栏蓝底横幅改成二级按钮（纸面 + 发丝线、左对齐），
  一屏唯一的实心蓝仍是「更新此行」；AI 行上方的虚线分隔改 1px 发丝线。

**4）走带 / 时间轴 / 浮层**

- 走带、时间轴、字幕表统一 16px 页边（原来走带与表格是 26px、时间轴 26px，
  播放按钮和波形左缘本身也没对齐）；`.timeline` 内边距 6→2、走带 margin 6→4、
  表格 margin 6→4。
- 走带控件全部 `flex: 0 0 auto` + `nowrap`：1080×680 下「全景 / 聚焦 / 跟随中」
  曾被压成竖排三行；≤1220px 先让出缩放滑杆（± 与倍率读数仍在）。
- 跟随开关改成「白色凸起胶囊 + 蓝点」（与分段控件同一套语法），不再涂一层蓝底。
- 播放头浮标不再盖住刻度标签（`paintRuler` 新增 `avoid` 区间）：原来 4.72s 处
  会读成「00:04.72005」；刻度标签字号 12→11px（Data 档）。
- 右键菜单 = 原生菜单形状（4px 内边距、28px 行、悬停整行强调色 + 白字）；
  「新建音色」= 360px 小表（10px 圆角、15/600 标题、28px 输入框、取消在左主操作在右）；
  选区工具条 = 纸白浮条 + popover 阴影（不再是铺满一行的蓝底）。
- 浅色下手画面投影从 `0 18px 40px rgba(0,0,0,.42)` 改成
  `0 10px 28px rgba(21,25,28,.14)`：深色投影在浅灰画布上读成一圈黑边。

**5）顺手修掉一个真 bug（查找栏）**

Step 4.1 把查找栏抽进 `ReviewTable` 时，`bind:value={findState.query}` 变成了单向
`value=`：⌘F 能打开、能打字，但**命中永远是 0**（输入框里的字没有写回状态）。
现在输入框走 `setQuery` / `setReplacement`（`lib/reviewFind.svelte.ts`），
真实界面验证：输入「雨」→ 2/2 → Enter 跳到第 4 条并高亮。

**验收（全部无窗口，独立 `--user-data-dir`）**

| 项 | 结果 |
| --- | --- |
| `npm run check` | ✅ |
| `npm run check:svelte` | ✅ **4/4**（基线 4） |
| `npm run build` | ✅ |
| `npm run test:main` | ✅ **392**（384 + reviewMargin 8） |
| `pytest -q -m "not integration"` | ✅ **1058 passed / 2 skipped**（31 deselected） |
| `verify_review_transport.mjs` | ✅ 全部通过（逐帧 / 倍速 / 磁吸 / 缩放记忆） |
| `verify_cue_selection.mjs` | ✅ 9 项（单击 vs 4px 框选 / ⇧ / Esc 不丢行） |
| `verify_review_defaults.mjs` | ✅ 18 项（50× 默认态 / 操作区不溢出 / 底栏只读草稿） |
| `verify_review_viewport.mjs` | ✅ 7 项（切页回来恢复现场） |
| `verify_review_overlays.mjs` | ✅ 12 项 × menu + dialog |
| `verify_cue_clipboard.mjs` | ✅ 18 项 |
| `verify_arbitration.mjs` | ✅ 全部通过 |
| `verify_phase2_shell.mjs` | ✅ **46 项**（外壳 / 舞台 / 对比度 / 紧凑模式） |
| `verify_reshape_flow.mjs` | ✅ 全部通过 |
| ReviewView 行数 | **1769**（持平，预算不下调；新逻辑全在 `lib/reviewMargin.ts`） |

**验收口径修正（既有陈旧断言）**：`verify_review_defaults.mjs` 里「底栏有暂存入口」
从 Step 3 起就是红的——底栏在 3B 已改成只读状态条、暂存进了「文件」菜单（⌘S），
但断言还在找 `.draft-dock` 与暂存按钮。本轮把断言改成「底栏有只读草稿状态 +
底栏没有按钮」，与 `verify_phase2_shell` 的「底栏里没有 .btn」同口径。

**Step 4.2 生产截图（真实 Electron，无窗口）**

| 看什么 | 图 |
| --- | --- |
| 核对台·日间校样（1360×838，页边 / 表格 / 检查器） | [step4-review-light.jpg](images/refactor-2026-11/step4-review-light.jpg) |
| 核对台·Dubbing booth（同一屏的暗色） | [step4-review-dark.jpg](images/refactor-2026-11/step4-review-dark.jpg) |
| 选中态：页边朱线 + 选区工具条（纸白浮条） | [step4-review-select.jpg](images/refactor-2026-11/step4-review-select.jpg) |
| 最小窗口 1080×680（走带不折字、页边仍成立） | [step4-review-1080.jpg](images/refactor-2026-11/step4-review-1080.jpg) |
| 双语态（60px 行高；铅笔不再出现） | [step4-review-both.jpg](images/refactor-2026-11/step4-review-both.jpg) |
| 查找栏（本次修好的绑定 + 命中高亮） | [step4-review-find.jpg](images/refactor-2026-11/step4-review-find.jpg) |
| 右键菜单·暗色（原生菜单形状） | [step4-review-menu-dark.jpg](images/refactor-2026-11/step4-review-menu-dark.jpg) |
| 「以此句音频新建音色」小表 | [step4-review-dialog.jpg](images/refactor-2026-11/step4-review-dialog.jpg) |

截图命令（沙箱里加 `KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox`）：用独立
`--user-data-dir` + `KIKUSUB_DEV_SEED`（12 条字幕 + 4 条质检项 + 译文轨 + 600s 素材），
`KIKUSUB_DEV_EVAL` 负责切原文 / 点行 / 开查找 / 开右键菜单，`--delay 6500` 等布局落定。

**明确不做（留给 4.3 / 4.4）**

- 质检待核面板、章节面板的内部排版（Step 4.4）。
- 双引擎复核页、AI 三页、导出、设置、导入的视觉（4.3 / 4.4）。
- 检查器宽度仍 348px：DESIGN.md 里那句 388px 是「舞台行（视频 + 检查器）」那一版布局的
  数值，而当前外壳是「检查器整列 + 表格」——390 会把 1080 窗口的字幕列压到 124px。
  这一步只改外观不动外壳，所以宽度留到「是否把检查器并进舞台行」一起评估。

### 7.5.1 Step 4.2.1 验收整改：译文轨状态条（2026-11-25）

**用户原话**：核对台右栏「当前条目」里，分段控件与时间码之间那块「译文轨状态与操作区」
很零乱——左上 `12 条 全部同步`，右下错层散着 `导入译文 / 撤销译文 / 删除译文` 三个裸
文本链接，红色「删除译文」很刺眼，且与下方单句编辑区缺少层次。

**改法（`impeccable distill`：低频动作退到菜单、同一块只说一遍）**

| 改造前 | 改造后 |
| --- | --- |
| 一行读数（左对齐）+ 一行三个裸链接（右对齐，含朱红） | **一条 24px 单行状态条**：读在左、入口在右 |
| `删除译文` 常驻在单句编辑器上方 | 收进 `⋯` 菜单，与其它项之间隔一条发丝线 |
| 没有译文轨时：显示模式行右端一个裸链接 | 条上左 `暂无译文` + 右一个 `导入译文…` 次级按钮 |
| 与 `#1` 编辑区之间隔着一整块杂讯 | 一条发丝线（`.cue-card` 上边线），上 8px / 下 12px |

- **状态词带色、不只靠色**：`全部同步` = success、`N 条待译` = 蓝铅笔（只是没翻，不是
  错误）、`M 条原文已改` = warn；两态同时出现时按「原文已改 → 待译」拼接，超长省略并
  带 `title`。`补译` 只在真有缺口时出现（打开补译批次并复制待译条目）。
- **菜单用核对台同一套原生形状**（4px 内边距 / 28px 行 / 悬停整行蓝底白字）；
  `Esc` 在这一层 `stopPropagation`，只关菜单、不清核对台选区（红线 6）。
- **`⋯` 用几何图标**（`Icon name="more"`，三颗实心点），不用文本字形 `⋯`——
  字体基线会把它顶到行顶，2× 截图里读成一撮浮尘（第一版实拍后改的）。

**验收（全部无窗口，独立 `--user-data-dir`）**

| 项 | 结果 |
| --- | --- |
| `npm run check` | ✅ |
| `npm run check:svelte` | ✅ 4/4（基线 4） |
| `npm run build` | ✅ |
| `verify_review_defaults.mjs` | ✅ **20 项**（新增「状态条只有一行」「删除译文不在常驻区」） |
| `verify_translation_flow.mjs` | ✅ 24 项（读数选择器改 `.track-bar .tb-status`） |
| `verify_gap_fill.mjs` | ✅ 11 项（顺手修好脚本里的旧页签名 `翻译` → `双语翻译`） |
| `verify_cue_selection` / `verify_review_transport` / `verify_review_viewport` / `verify_cue_clipboard` / `verify_review_overlays`（menu+dialog） / `verify_arbitration` | ✅ |
| `CuePane.svelte` | 748 → **629**；新组件 `TrackBar.svelte` 303 |
| `ReviewView.svelte` / `store.svelte.ts` | 1769 / 3217（一行未动） |

**截图**：[step4-trackbar-light.jpg](images/refactor-2026-11/step4-trackbar-light.jpg)（有译文轨 +
菜单展开）、[step4-trackbar-dark.jpg](images/refactor-2026-11/step4-trackbar-dark.jpg)（暗色）、
[step4-trackbar-empty.jpg](images/refactor-2026-11/step4-trackbar-empty.jpg)（暂无译文）。

### 7.6 Step 4.3 落地记录：剩余页面按用户旅程收口（2026-11-25）

顺序按用户真实动线：**准备与复核 → 原文加工 → 交付 → 辅助与边界**。每完成一组各自成
commit（`desktop` 层），台账与契约随后同步。

**组一 · 准备与复核（导入 + 双引擎复核）**

- **导入页补上「继续当前工程」**（修断层）：已有工程时顶部先是一张 760px 卡——封面 /
  文件名 / `时长 · 条数 · 报告状态` / 主按钮「继续核对 ⌘3」（没字幕时「去转写 ⌘2」）+
  安静的「换片…」；拖入降为一条 40px 带（仍可直接把文件拖进窗口）。没有工程时才回到
  原来的大拖放区。
- **双引擎复核收进一张台本纸**：对照表用 `.cue-sheet`（纸白 + 1px `--rule` + 7px 圆角，
  左右 16px 页边），表头回到 11px 标签字；页头 `.canvas` + 16px 页边，与核对台同骨架。
  行内「试听 / 采用 B」命中区 20 → 22px、字 11 → 11.5px，仍然安静。

**组二 · 原文加工（锁轴 ① / 重排 ②）**

- 侧栏「03 原文」两页加**段内编号** `①` `②`（mono 11px、第三级墨色）。编号只做可见标记，
  不进 `label` / `aria-label`，脚本按名字匹配不受影响。
- `AiBatchToolbar` 新增 **note 槽**（标题下一行）：写清这一页动不动时间轴，并给同组下一页
  的入口——锁轴「只改文字，条数与时间码 1:1 不动 → 去 ② 重排润色」、重排「会改条数与
  时间码，整段替换前先过体检 → 去 ① 锁轴润色」、翻译「译文走平行轨，原文与时间轴都不动
  → 回核对台」。三页共用同一个位置，切页不跳。

**组三 · 交付（双语翻译 + 导出）**

- 「暂无译文轨」从两段各一句收成**页头一条**（原文案还带着改名前的「AI 处理 → 翻译」），
  右侧直接给「去双语翻译」；两段的译文 / 双语按钮照旧置灰。
- 成片预览按**监看器**做：10px 视窗圆角、近黑底、内描边 + `--shadow-video`，与核对台
  画面同一套处理。
- 导出完成卡补「回到核对台」，交付闭环不用再回侧栏找路。

**组四 · 辅助与边界（提示词库 / 设置 / Harden）**

- 设置页左侧四个类别去掉高饱和彩块（蓝 / 紫 / 橙 / 青），改成与主侧栏同一套线图标：
  未选中 `--ink-3`、选中转蓝铅笔。
- 提示词库右上角三颗按钮改用现名（锁轴润色 / 重排润色 / 双语翻译）；导出页与设置页
  AI 文案里残留的旧页名一并改掉。
- **Harden**：①「内核未连接」遮罩多一颗「重启内核」（主进程 `sidecar:restart`，把崩溃
  自动重连的 3 次计数清零再拉一次，退出中拒绝）；② 底栏读数 `.sb-item` → `.st-item`，
  修掉与侧栏导航的类名撞车（设置页布局回归一直点到「Anime Whisper」的真正原因）；
  ③ 长路径 / 截断沿用既有 `title` + ellipsis（导出位置、模型目录、导入工程名均核对过）。

**顺手修好的脚本（Step 3B 改名后的存量红）**

| 脚本 | 原因 | 处理 |
| --- | --- | --- |
| `verify_gap_fill` | `nav('翻译')` 匹配不到「双语翻译」 | 改现名，11 项全绿 |
| `verify_clip_scope` | `sidebar('润色'/'翻译')`、章节按钮 `仅处理此片段` | 改现名 / 改「处理此片段」，20 项全绿 |
| `verify_batch_and_align` | `sidebar('润色'/'翻译'/'断句重排')` | 改现名，全部通过 |
| `verify_settings_layout` | 底栏 `.sb-item` 撞侧栏类名 | 底栏改名 `.st-item`（代码修复，非改断言） |
| `verify_settings_ai_fold` | 导出页 hint 从两段收成一条 | 断言改成 `hintCount === 1` + 新文案 |

**Step 4.3 生产截图（真实 Electron，无窗口，明暗各一套）**

| 页面 | 日间校样 | 夜间配音 |
| --- | --- | --- |
| 导入（已有工程 → 继续核对） | [step5-import-light.jpg](images/refactor-2026-11/step5-import-light.jpg) | [step5-import-dark.jpg](images/refactor-2026-11/step5-import-dark.jpg) |
| 转写 | [step5-transcribe-light.jpg](images/refactor-2026-11/step5-transcribe-light.jpg) | [step5-transcribe-dark.jpg](images/refactor-2026-11/step5-transcribe-dark.jpg) |
| 核对台 | [step5-review-light.jpg](images/refactor-2026-11/step5-review-light.jpg) | [step5-review-dark.jpg](images/refactor-2026-11/step5-review-dark.jpg) |
| 双引擎复核 | [step5-dual-light.jpg](images/refactor-2026-11/step5-dual-light.jpg) | [step5-dual-dark.jpg](images/refactor-2026-11/step5-dual-dark.jpg) |
| ① 锁轴润色 | [step5-polish-light.jpg](images/refactor-2026-11/step5-polish-light.jpg) | [step5-polish-dark.jpg](images/refactor-2026-11/step5-polish-dark.jpg) |
| ② 重排润色 | [step5-reshape-light.jpg](images/refactor-2026-11/step5-reshape-light.jpg) | [step5-reshape-dark.jpg](images/refactor-2026-11/step5-reshape-dark.jpg) |
| 双语翻译 | [step5-translate-light.jpg](images/refactor-2026-11/step5-translate-light.jpg) | [step5-translate-dark.jpg](images/refactor-2026-11/step5-translate-dark.jpg) |
| 导出 | [step5-export-light.jpg](images/refactor-2026-11/step5-export-light.jpg) | [step5-export-dark.jpg](images/refactor-2026-11/step5-export-dark.jpg) |
| 提示词库 | [step5-prompts-light.jpg](images/refactor-2026-11/step5-prompts-light.jpg) | [step5-prompts-dark.jpg](images/refactor-2026-11/step5-prompts-dark.jpg) |
| 设置 | [step5-settings-light.jpg](images/refactor-2026-11/step5-settings-light.jpg) | [step5-settings-dark.jpg](images/refactor-2026-11/step5-settings-dark.jpg) |

命令：`bash tools/shots/capture_matrix.sh --out /tmp/final-light --size 1360x838 --seed
tools/shots/readme-seed.json --states "import transcribe review translate export prompts settings"`
（暗色加 `--theme dark`）；AI 三页用
`node tools/shots/capture_ai_workbench.mjs --theme light --states "polish-dual,reshape-draft,dual"`。
全部走独立 `--user-data-dir` / `KIKUSUB_DATA_DIR`，不写现役 App 的任何目录。

**明确不做 / 待评估**

- 检查器 348px → 388px 与「舞台行」改造：仍按 §7.5 的结论留在后续评估。
- ~~`verify_chapter_edge`：8/10（右缘 rAF 推进两项）~~ → **10/10（2026-11-26 已解决，
  见 §7.8）**。根因是测试前置把视窗留在全景，加上 `ChapterTrack.visible` 在拖动中把
  被拖条目筛掉；后者是 22eec77（重构前）就存在的真实缺陷，不是本轮引入。

## 8. 验收矩阵

### 8.1 每步必跑

```bash
cd desktop
npm run check
npm run check:svelte
npm run build

# 文档改动
cd ..
pytest -q tests/test_docs_health.py

# 视觉（无窗口）
bash tools/shots/capture_matrix.sh --out /tmp/kikusub-shots
# 或单页
KIKUSUB_DEV_SEED=tools/shots/seed.json KIKUSUB_SHOT_DELAY=6000 \
  npx electron . --screenshot=/tmp/kikusub-shot.png

# 核对台浮层（Step 4.1 起）
node tools/shots/verify_review_overlays.mjs --mode menu
node tools/shots/verify_review_overlays.mjs --mode dialog

# Step 6 起的专项回归（都走无窗口截图路径）
node tools/shots/verify_tts_panel_fit.mjs            # 朗读 ⚙ 面板 348px 不溢出（11 项）
node tools/shots/capture_transcribe_states.mjs       # 执行栏三态 + 进度条（17 项）
node tools/shots/capture_review_inspector.mjs        # 徽标 / 面板 / 底部收尾区（11 项）
```

### 8.2 视觉验收

- 1360×838（默认）与 1080×680（最小）各看一眼；100% 缩放；不做 200%。
- 日间校样 / 夜间配音两套都看；明朝字体另截一张（同一套 light，只换 `--font-cue`）。
- 每页至少覆盖：默认、选中、空态、失败/离线、长文本截断。
- 截图落盘后 `read_image` 自查；不用“手点一遍”当开窗理由。

### 8.3 红线复述

- `ReviewView.svelte`（1769）/ `store.svelte.ts`（3217）只降不升；先拆逻辑/子组件。
  2026-11-25 Step 4.2 的核对台精修一行没进这两个文件（页边纯逻辑在 `lib/reviewMargin.ts`）。
- 单击 vs 4 px 框选、`duration/69` 缩放、50 步统一历史、`setExport*`、无窗口、无 200%。
- 主题只走 `html[data-theme]` 令牌；组件不写主题色；分隔线不用 5% 灰。

### 7.7 Step 5 终局验证（2026-11-25）

| 项 | 结果 |
| --- | --- |
| `npm run check` | ✅ 0 error |
| `npm run check:svelte` | ✅ 4/4（基线 4，未上升） |
| `npm run build` | ✅ |
| `npm run test:main` | ✅ **392** |
| `pytest -q -m "not integration"` | ✅ **1058 passed / 2 skipped**（31 deselected） |
| `impeccable detect`（构建产物） | ✅ **0 anti-patterns**：删掉进度条的两条无限循环高光、导出进度条的渐变填充、存储条的斜纹底 |
| 键盘 | ✅ `⌘1…⌘8` 依次切到 导入/转写/核对台/双引擎复核/① 锁轴/② 重排/双语翻译/导出；`⌘F` 打开查找（输入框就位）、`Esc` 关闭；`Esc` 不清当前行 |
| 对比度 | ✅ `verify_phase2_shell`（明暗两套：正文 ≥7:1 / 11px ≥4.5:1 / 蓝铅笔 ≥4.5:1 / 底栏 ≥4.5:1） |
| 动效 | ✅ 高频编辑零过渡；进度条只保留「确定填充」与「不确定呼吸」；`prefers-reduced-motion` 全停 |
| `tools/shots/verify_*.mjs` | ✅ Step 5 时 25/26；**2026-11-26 复跑 27/27 全绿**（含 2 个浮层模式，见 §7.8） |
| `capture_matrix.sh` | ✅ 10 个状态 × 明暗两套；基线已按新外观刷新（21 张） |

**基线更新**：`docs/images/shots/baseline/` 全部 21 张换成新外观（10 个状态 + AI 三页的
light/dark/mincho + 设置两页 1440×900），`capture_matrix.sh --compare` 从此以新外观为准。

**2026-11-26 复跑（§7.8）**：`npm run test:main` 401、`pytest -q` 1089 passed / 2 skipped、
`tools/shots/verify_*.mjs` 27/27、`check:svelte` 4/4（基线 4）。

**README 展示图**：**本轮不动** `README.md` / `README_EN.md` 的成品图。理由：那些图是
main 分支面向用户的承诺，而 `feat/ui-redesign` 还没合入；等验收通过、合并前用
`KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox bash tools/shots/capture_matrix.sh --seed
tools/shots/readme-seed.json --delay 12000 --states "import transcribe review translate export settings"`
重出一次即可（命令与种子都已在 tools/shots/README.md 里）。

### 7.8 Step 5 收尾：章节端点排雷 + 双开试用版（2026-11-26）

**一、`verify_chapter_edge` 的 2 项失败：先修测试前置，再修真实缺陷**

原先的 `8/10` 是「拖到右缘 rAF 推进」与「推进时抓手钉在右缘」。排查结论分两层：

1. **测试前置被改坏（67e8434）**：为了在 18× 视窗里验证「单击旗标仍跳转」，脚本先点
   「全景」把现场拉回来；但全景的 `viewSpan = duration = 60`，`clampStart` 没有可推进
   的空间，rAF 推进器本来就不该动。pan 阶段复用同一现场，两条断言必红。**这不是产品问题。**
2. **恢复窄窗后暴露真实缺陷（22eec77，重构前就有）**：`ChapterTrack.visible` 用**已落库**
   的 `item.start/end` 做半屏裁剪，拖动中的端点只存在 `drag` 状态里。压住右缘平移超过
   半屏后，这一条被筛掉，`chapter-track` 整块卸载，`drag` 与抓手一起消失——真实用户
   松手会丢失这次拖动，不只是测试点不到。`git merge-base --is-ancestor 22eec77 74fd5dc`
   可确认它在备份锚点之前，本轮重构没有碰过 `ChapterTrack.svelte`。

修复：

- `components/ChapterTrack.svelte`：`visible` 强制保留 `drag.id` 对应的条目，注释写明
  边缘自动平移会越过已落库区间的裁剪线。
- `tools/shots/verify_chapter_edge.mjs`：`flagClick` 之后重新放大到窄窗，恢复 pan 阶段的
  前置现场；10 条断言一条没放宽。
- 结果：**10/10**（本机 Node 26，无窗口截图路径）。

**二、双开试用版 `KikuSub-Next.app`**

- 新脚本 `tools/pack/build_trial.sh`；`build_app.sh` 增加构建期环境变量
  （`KIKUSUB_APP_NAME` / `KIKUSUB_BUNDLE_ID` / `KIKUSUB_PACK_DIR` /
  `KIKUSUB_DATA_DIR_NAME` / `KIKUSUB_ISOLATION`）。**默认值一字未改**，正常发版仍产出
  `build/pack/KikuSub.app` + `com.kikusub.desktop`。
- 产物：`build/pack-next/KikuSub-Next.app`；bundle id `com.kikusub.desktop.next`；
  CFBundleName / 主可执行文件 / 包内 `package.json` 的 productName 均为 `KikuSub-Next`。
- 隔离：包内 `Contents/Resources/app-isolation.json` 由 `desktop/main/isolation.cjs`
  读取；主进程在 `ready` 前设定 `app.setName` 与 `userData` / `sessionData`，单实例锁
  跟着 userData 走。用户数据根同时切到 `~/Library/Application Support/KikuSub-Next`，
  `settings.json` / `presets.json` / `preferences.json` / `.ai-key` / `outputs` 全在
  这一处；建立不起独立根时**拒绝启动**，绝不回落到共享目录。
- 模型：装配不建 `Application Support` 的模型软链；首次启动向导里把模型目录指向现有
  `models/` 即可共享权重，不必重下。
- 全局副作用只剩两处（试用说明里必须写）：设置页「安装命令行工具」仍会改
  `~/.local/bin/kikusub`，「一键配置技能」仍会覆盖 `~/.agents/skills/kikusub-subtitle`。
  试用时**不要点**；其余读写都在 `KikuSub-Next` 数据根内。
- 无窗口验证：用 `KIKUSUB_ISOLATION_ROOT=/tmp/...` 把隔离根挪到临时目录后跑
  `KIKUSUB_NO_WINDOW=1 KIKUSUB_SHOT=...`，首启向导截图显示「数据与输出目录：/tmp/...」；
  现役 `build/pack/KikuSub.app` 与 `~/Library/Application Support/KikuSub` 的文件元数据
  及关键配置 sha256 前后零差异，现役进程 PID 未变。

**三、2026-11-26 复跑**

| 检查 | 结果 |
| --- | --- |
| `npm run check` | ✅ 0 error |
| `npm run check:svelte` | ✅ 4/4（基线 4，未上升） |
| `npm run build` | ✅ |
| `npm run test:main` | ✅ **401** |
| `pytest -q` | ✅ **1089 passed / 2 skipped** |
| `tools/shots/verify_*.mjs` | ✅ **27 / 27 全绿**（含 2 个浮层模式） |

### 7.9 Step 6 真机实测收口（2026-11-26）

用户用 `KikuSub-Next.app` 跑完整业务流（双开正常、旧版 `KikuSub.app` 毫发无损）后，
在真实片源上报回 **1 个功能崩溃 Bug + 4 处界面/排版问题**。本轮逐条根治。

#### 一、崩溃 Bug：`'NoneType' object is not callable`（第二版 + Anime Whisper）

**真机复现**：Qwen3-ASR + CTC 整片转出 246 条主稿 → 转写页把产出切到「第二版（对照）」→
引擎选 Anime Whisper（期间改过 2 项专家参数）→ 点「生成第二版」→ **转录即将落盘时**
底部报 `! 转写失败 'NoneType' object is not callable`。

**定位**：`~/Library/Application Support/KikuSub-Next/outputs/logs/kikusub.log`
（2026-11-26 00:36:08）拿到了精确 traceback：

```
File "server/jobs.py", line 960, in _run_transcribe
File "core/pipeline.py", line 433, in run_transcription
File "core/pipeline.py", line 417, in _run_engine
File "core/transcribe.py", line 1839, in transcribe_file
File "core/transcribe.py", line 1991, in _decode
File "core/transcribe.py", line 1708, in _decode_chunk
TypeError: 'NoneType' object is not callable
```

`core/transcribe.py:1708` 是 `res = self._pipe(...)`。同一秒的日志给出了凶手：

```
00:36:08,322 [kikusub-asr-idle] core.transcribe: Anime Whisper 权重已卸载（让位给对齐层）
00:36:08,322 [kikusub-asr-idle] core.engine_idle: ASR 引擎空闲卸载 | whisper | 空闲 181s
```

**根因**：`core/engine_idle.py` 只按「最后一次 `touch`」判空闲（默认 180s），而
`server/jobs.py` 的 `_run_transcribe` **只在任务跑完时** `touch`。本次 whisper 的上一次
`touch` 是 00:33:07（更早一次「另一引擎复核」结束时），整片任务 00:33:57 开始后
81 秒就到了 180s 阈值——空闲巡检线程把**正在解码的**权重卸了，`_pipe` 变 None，
下一段解码就是那句 `NoneType`。与「第二版」「改过参数」「PyInstaller sidecar」都无关：
单引擎整片、只要前 180s 内有过一次复核、且本轮跑超过 180s 就会中。Qwen 的 `unload()`
同理。

**修复**（`core,server` 一层）：

1. `core/engine_idle.py` 新增**租约**：`hold(key)` / `acquire` / `relinquish` / `busy`。
   `sweep()` / `release_others()` / `release_now()` 一律跳过有租约的引擎；租约退出时
   `touch`，空闲窗口从「这轮结束」重新计时（原来是从「这轮开始」的旧时间戳算）。
2. `server/jobs.py`：`_run_transcribe`、`_run_compare`、`_run_dual` 的两遍都用
   `with self._idle.hold(...)` 包住真正跑片的那一段。
3. `core/transcribe.py::_decode_chunk` 加一道自愈兜底：`_pipe is None` 时重新 `load()`
   一次再解码（真被外力卸掉也把这一趟跑完，而不是整片判死），仍失败才抛可读错误。

**回归**（两条，都先证明「没有修复会红」）：

- `tests/test_engine_idle_lease.py`（6 例，轻量）：无租约时巡检会卸、有租约时 600s
  也不卸、退出即重新计时、空 key 是空操作、`release_others` 只卸载空闲的、真线程下
  200 轮不漏；
- `tests/test_server_alt_review_idle.py`（服务端整条路径）：主稿存在 → 用 whisper 跑
  「第二版」→ runner 每段推进 70s 并**顺手调一次 `idle.sweep()`**（等价于后台线程）→
  断言任务 `done`、whisper 一次没被卸、第二版落进第二列、主稿一个字没动。
  把 `with hold(...)` 换成 `if True:` 后这条用例立刻复现真机的 `NoneType` 崩溃。

#### 二、界面/排版四项

**1) 彻底消除「灰底叠白框」和「框里套框」（导出页 / 转写页 / 顺查全站）**

- 导出页原来是**灰画布 → 大白框 → 小白框**三层：`.track-note`（白底 + 边框）、
  `.range-row`（白卡）、`.export-card`（白卡 + 1px 边框 + 投影），再在其内部套
  3 个导出形式白卡 + 6 个字幕样式白卡 + 4 个码率白卡。
- 现在 `.export-card` 改名 `.export-body` 并**去掉全部外壳**（无底色 / 无边框 / 无投影
  / 无圆角），页面段落靠**标题 + 1px 发丝线**自然分段；提示条去掉边框与底色退成一行
  说明；导出形式 / 字幕样式 / 码率预设置改成**只保留一层**的描边块：透明底 +
  `--line` 描边，悬停淡底，选中蓝描边 + 极淡蓝底。运行 / 完成状态块也从「白卡 +
  渐变」改成单层淡底（顺带删掉 `linear-gradient`，DESIGN 明确不要渐变）。
- 转写页本来就没有卡片套娃，但底部执行栏是「半透明模糊白条贴片」，见下一条。

**2) 转写页底部执行栏重做成 Docked 栏 + 三态**

- 旧结构：`.dock-wrap` 是 `position: sticky` 摆在滚动内容**内部**，里面 `RunDock` 自己
  带 `background: var(--bg-toolbar)` + `backdrop-filter`，于是那条 90px 高的半透明白条
  贴在灰画布上，两侧还内缩，看起来是一张贴片。
- 现在：`.dock-wrap` 是 pane 的**最后一个 flex 子项**（`flex: 0 0 auto`），通栏、
  `color-mix(paper, canvas)` 的极浅色带 + 一条上发丝线；`.dock-inner` 与
  `.page-wrap` 用同一套几何（1120 内容列 + 32px 内边距），复述文字与上面三步严格同左缘
  （截图断言 ±1px）。`RunDock` 自己不再有任何底色/模糊/圆角。
- 三态：待开始 = 两行（复述 + 说明）；进行中 = 状态行（spinner + 阶段 + 等宽百分比）
  + **4px 水平进度条**（中性槽 + 蓝铅笔实心填充，`aria-valuenow` 同步）+ 复述行，
  主按钮换「中途打断」；失败 = 朱红状态行（原因单行省略、`title` 里有全文）+ 主按钮
  保留（可直接重跑同配置）。`prefers-reduced-motion` 停掉 track 过渡与 spinner。

**3) 「质检待核」数字徽标**：页签里原本是 `--ink-3` 极淡灰等宽数字（代码注释还写着
「计数是读数，不是徽标」）。待核数不是读数而是「还有几句要你动手」，与字幕表页边的
待核朱点同义 → 改成**朱红微胶囊**（`--danger` 文字压在 `--danger-soft` 底上：
日间 4.9:1 / 夜间 5.6:1，均过 4.5），`0` 时仍然不渲染。「章节 3」保持等宽灰数字
（它是纯读数），两者语义由此分开。

**4) 朗读 ⚙ 展开面板 348px 溢出**：真机在有 OmniVoice 克隆音色时展开，
面板宽 363px、撑出检查器右缘 32px 被裁掉（第一个按钮只剩半截）。
根因：`.tts-panel` 是 `flex: 1 0 100%`，basis 只有 306px（348 − 16×2 内边距 − 滚动条），
但 flex 项的自动最小尺寸默认 `min-content`，而那五个按钮的 min-content 加起来 363px，
`flex-shrink: 0` 让它顶着 min-content 溢出。修复：`min-width: 0`（根因）+ 头部只留
「朗读 · 引擎 · 收起」、音色细节读数单独一行 + 动作按钮拆成两行规整布局
（第一行 语速/上传/截取 三等分，第二行 音色库/管理）。
回归：`tools/shots/verify_tts_panel_fit.mjs`（11 条断言，1080×680 视口）：
`scrollWidth <= clientWidth`、面板内每个按钮 / 下拉框的 boundingBox 都在检查器左右缘内、
「音色库 1」与「管理」真的可见。

**5) 检查器底部收尾区**：原来「AI 优化未启用 + 去设置」是一个悬在空白上的白底按钮，
下面「漏检 / 知识库 / 任务报告」散成两段，再下面就是一大块空洞。
现在：`AI 优化未启用 … 去设置 ›` 收成一行（动作退成蓝铅笔文字链接）；
`InspectorMeta` 改成 `.meta-foot` 收尾区——`margin-top: auto` 钉在检查器底缘、
一条上发丝线、**一行收口**（状态 chips 在左、「任务报告 ›」在右、说明最多一行小字）。
空白因此落在内容与收尾区之间（读作留白），而不是吊在最后一行下面。

#### 三、2026-11-26 复跑

| 检查 | 结果 |
| --- | --- |
| `npm run check` | ✅ 0 error |
| `npm run check:svelte` | ✅ 4/4（基线 4，未上升） |
| `npm run build` | ✅ |
| `npm run test:main` | ✅ 401 |
| `pytest -q` | ✅ **1096 passed / 2 skipped** |
| `tools/shots/verify_*.mjs` | ✅ **27 / 27 全绿**（＋ overlays 的 menu / dialog 两种模式；新增 `verify_tts_panel_fit`；`verify_settings_ai_fold` 的 `.export-card` → `.export-body`） |

#### 四、试用版重新打包（红线 9）

Python 改了（`core/` + `server/`），所以按红线 9 先重打 sidecar 再装配：

```bash
bash tools/pack/build_sidecar.sh          # 01:17 完成，包内 sidecar 与构建产物 sha256 一致
bash tools/pack/build_trial.sh            # → build/pack-next/KikuSub-Next.app（1.4G）
```

- 身份未变：`com.kikusub.desktop.next` / 数据根 `~/Library/Application Support/KikuSub-Next` /
  包内 `app-isolation.json` 仍是 `{appName: KikuSub-Next, dataDirName: KikuSub-Next}`。
- 现役隔离：`build/pack/KikuSub.app/Contents/Info.plist` sha256 打包前后一致
  （`f0afca4a…e269e`），`~/Library/Application Support/KikuSub` 未被写入。
- 无窗口冒烟：用 `KIKUSUB_ISOLATION_ROOT=/tmp/…` 把数据根挪到临时目录后跑
  `…/MacOS/KikuSub-Next --no-sandbox --screenshot=…`，首启向导正常出现并显示临时数据根；
  真实数据根未被这次验证写入。
- 装配脚本的既有行为：若 `KikuSub-Next.app` 还有一个在跑的旧实例，`build_app.sh` 会先
  TERM、8 秒不退出再 KILL（否则删包会把它的 cwd 和 sidecar 一起抽掉）。本次装配时确实
  关掉了一个仍在运行的试用版实例；工作草稿是逐次自动落盘的（`*.autosave_draft.srt`），
  重新打开即可接着干。

**新增取证截图**（无窗口，全部 `read_image` 自检过）：

- [step6-transcribe-running.jpg](images/refactor-2026-11/step6-transcribe-running.jpg)（运行中 47% 进度条）
- [step6-transcribe-error.jpg](images/refactor-2026-11/step6-transcribe-error.jpg)（失败态：正是真机那句报错）
- [step6-transcribe-idle.jpg](images/refactor-2026-11/step6-transcribe-idle.jpg)（待开始）
- [step6-review-inspector.jpg](images/refactor-2026-11/step6-review-inspector.jpg)（徽标 + 朗读面板 + 收尾区）
- [step6-review-inspector-dark.jpg](images/refactor-2026-11/step6-review-inspector-dark.jpg)（夜间同屏）
- [step6-export-light.jpg](images/refactor-2026-11/step6-export-light.jpg) / [step6-export-dark.jpg](images/refactor-2026-11/step6-export-dark.jpg)（日/夜）

### 7.10 Step 7 视觉终局：FCP 式深碳灰 + 纸白台面（2026-11-26）

用户用 `KikuSub-Next.app` 实机跑完 24 分钟全片（246 条一次通过，空闲卸载崩溃已根治）后，
对**配色质感、单栏布局与 3 处交互细节**提出 6 条明确整改。这一轮只动渲染层的令牌、页面骨架
与控件语法：**没有碰 `core/` / `server/`，没有新增功能**。

#### 一、色板重写：暗色 = 剪辑台碳灰，亮色 = 纸白台面（§1、§2）

**问题**：暗色四阶只差 5–7 个色阶，缩到一张截图里就是「一块近黑到底」；亮色则是
「冷灰画布 `#EDF1F5` + 纯白卡片」，于是每个分区都读成「灰底上贴了一张白框」。

**决定（DESIGN.md 新增两条命名规则）**：

- **The No White Frame Rule**：白底只允许出现在**台本纸 / 浮层 / 输入框**三类对象上；
  页内分区一律「标题 + 发丝线」或**凹陷填充（well）**。全站不再有白框叠白框、也没有灰底贴白框。
- **The Two-State Switch Rule**：界面里的开关必须一次点击就到达另一面（见 二）。

**亮色令牌（翻转层级）**：`--canvas #FFFFFF`（纸白台面）/ `--paper #F0F2F4`（铬件：
侧栏 / 标题栏 / 底栏 / 时间轴坞）/ `--bg-inspector #F7F8F9`（第三块）/ `--raise #FFFFFF`
（台本纸 / 浮层 / 输入框）/ `--well = --fill`（5% 中性墨，无边框的凹陷填充）/
`--rule #DBE1E6`（白纸上的发丝线）。三块并排时每两块之间都有可读明度差。

**暗色令牌（FCP 式四阶）**：`--stage-bg #0B0D0F`（画面所在的房间，全应用最深）→
`--canvas #1A1C1F`（工作区）→ `--bg-inspector #1F2226`（检查器）→ `--paper #24272B`
（铬件）→ `--raise #2C3136`（台本纸 / 浮层）。相邻两阶差 ~9–11 个色阶：
够分区、不够成条纹。**暗色的凹陷填充是「提一档」**（6.5% 白）——同一个令牌在暗色里
反向工作，因为暗底上「可点的一块」是更亮的一块。

**组件层同步改造**（不再逐处写主题色，全部走令牌）：输入框 / 下拉 / 分段槽 / 选项块 /
设置分组 / 空态 / 模板卡 / 引擎行改成 wells；`.card` 退成凹陷说明块；新增 `.btn.soft`
（Tinted 次级小按钮）；页头 ghost 动作补淡填充（它们原来是裸字）。

#### 二、标题栏外观按钮：一键直切（§3，用户第 2 条）

旧实现 `auto → light → dark → auto` 循环：跟随系统且系统是浅色时，想变暗要点两下。
现在 `flipAppearance(current: ThemeId)` 取**解析后的明暗**翻面，一次点击即到另一面；
`auto` 只留在「设置 → 外观」。图标跟着当前面（☀︎/☾），`title` 直接写「点击切到夜间配音」。
`themes.ts` 的 `nextAppearance` 删除，`test/appearance.test.mjs` 补一条两态直切断言。

#### 三、侧栏去掉 `①` `②`（§4，用户第 3 条）

`viewMeta.ts` 的 `ordinal` 字段整条删除，`Sidebar.svelte` 的 `.sb-ord` 与它的样式一起删掉。
页内两句互相指路保留，但去掉悬空的编号（`断句本身错了？去重排润色 →`）；
`PromptView` 两个按钮的 `title` 改成带快捷键的口径。侧栏回到统一的「干净图标 + 纯净标题」。

#### 四、朗读 ⚙ 面板重排（§5，用户第 4 条）

- 删掉面板里重复的 `朗读` 标题（触发按钮就在上一行）与 `×`；只留一颗 20px 高的
  **「收起」文字按钮**，不再有两个关闭动作叠在一起。
- `管理` 的图标从 `gear`（与触发按钮同一个齿轮）换成 `pencil`（编辑这个音色）。
- 内容改成**等分网格铺满宽度**：第一行 `1.0× | 上传 | 截取`（三列等分），第二行
  `音色库 1 | 管理`（两列等分）；下拉与按钮同高同语言（24px + 一层细描边），
  右侧不再空出一块。
- 面板本体从「白卡 + 描边」退成 **well**（检查器里的白框套白框就此消失）。
- `verify_tts_panel_fit.mjs` 11 项全绿（1080×680、348px 检查器）。

#### 五、导出页三处细节（§6，用户第 5 条）

1. **主按钮下方的发丝线**：`.sec` 原来只有上内边距，下一段的 `border-top` 直接贴住
   「导出字幕」的底边。改成线上下各留生气（上 20 / 下 24），按钮不再撞线。
2. **孤立的裸蓝字链接**：「去双语翻译」收进一条完整的提示条（well + 内嵌 `.btn.soft`）；
   `最近：<文件名>` 从一个蓝链接变成等宽淡灰胶囊（它是读数不是动作）；
   转写页「管理引擎…」由 ghost 改为 `.btn.soft`。同类孤立的页头动作（任务详报 /
   回到核对台 / 去转写页…）统一补淡填充（`PageHeader` 里一条 scoped 规则），
   标题栏里的图标 ghost 仍保持透明。
3. 顺查全站：`.mode / .preset / .style-preset / .appearance-card / .font-card /
   .aiw-card / .aiw-blank-card / .aiw-empty / PromptView 的 .card / .set-group /
   .voice-list / .voice-panel` 全部换成「只保留一层」的语法。

#### 六、单栏页面居中（§7，用户第 6 条）

- 新增 `--measure-page: 1040px` + `--measure-card: 760px` 两个令牌，导入 / 导出 /
  提示词库 / 设置 / 任务详报五个单栏页面统一 `justify-content: center`。
  因为**共用同一个 max-width**，它们在同一窗口宽度下仍然共享同一条左缘——
  原先把「左对齐」当解法的那个理由（各页 1120 / 1000 / 960 三档漂移）不再成立。
- 转写页是唯一的双栏页：正文 1120 居中，页头补一条 `max-width: 1120px` 让它与正文同左缘
  （原来标题比正文左偏一个滚动条宽度）。
- AI 三页（锁轴 / 重排 / 双语翻译）是**满屏网格**，表格保持通栏；它们的页标题行
  页边从 14px 收到 24px，与其它页面同一条左缘；三页的空态（`.aiw-empty` /
  `.aiw-blank-card`）改成居中的 well 块。

#### 七、顺手修掉的一个真实缺陷（滚动条宽度级别的死代码）

`ReviewView.svelte` 的紧凑模式媒体查询里写着 `.player / .table-area / .transport /
.tl-tools` 四条规则，但这些元素都在子组件里——**Svelte 的 scoped 样式跨不过组件边界**，
所以从 Step 4.1/4.2 拆组件起它们就再没生效过（紧凑模式的「播放器按一屏定宽」与
「表格保底 200px」实际上一直没上）。本轮把这四条搬回 `ReviewStage` / `ReviewTable` /
`ReviewTransport`，删掉父组件里的死规则（ReviewView 1775 → 1764，预算 1769 之内）。

#### 八、2026-11-26 Step 7 复跑

| 检查 | 结果 |
| --- | --- |
| `npm run check` | ✅ 0 error |
| `npm run check:svelte` | ✅ 4/4（基线 4，未上升） |
| `npm run build` | ✅ |
| `npm run test:main` | ✅ **402** |
| `pytest -q` | ✅ **1096 passed / 2 skipped** |
| `tools/shots/verify_*.mjs` | ✅ **28/28**（27 个脚本；`verify_review_overlays` 的 menu / dialog 各算一次） |
| `capture_matrix --compare` | ✅ transcribe / review / export / settings 全 `average:inf`；import 45.2dB（该页有运行期时间戳） |
| `verify_phase2_shell` 对比度 | 亮 15.75 / 5.66 / 4.76 / 5.34 / 发丝 1.33；暗 12.03 / 5.71 / 6.28（正文 / 11px / 蓝铅笔） |
| 无窗口截图矩阵 | 10 个状态 × 明暗两套 + 1080×680 最小窗口 + 朗读面板 |

**基线更新**：`docs/images/shots/baseline/` 全部 21 张换成新外观（单独一个 `chore(shots)` commit）。

**新增取证截图**（无窗口，全部 `read_image` 自检过）：

- [step7-dark-review.jpg](images/refactor-2026-11/step7-dark-review.jpg)（碳灰四阶 + 检查器 + 台本表）
- [step7-dark-transcribe.jpg](images/refactor-2026-11/step7-dark-transcribe.jpg)
- [step7-dark-import.jpg](images/refactor-2026-11/step7-dark-import.jpg)
- [step7-dark-export.jpg](images/refactor-2026-11/step7-dark-export.jpg)
- [step7-light-import.jpg](images/refactor-2026-11/step7-light-import.jpg)（纸白台面 + 居中）
- [step7-light-transcribe.jpg](images/refactor-2026-11/step7-light-transcribe.jpg)
- [step7-light-export.jpg](images/refactor-2026-11/step7-light-export.jpg)
- [step7-light-inspector.jpg](images/refactor-2026-11/step7-light-inspector.jpg)（朗读面板重排）

#### 九、试用版重新打包（Step 7 收口）

Python 一行未改，所以 sidecar 不需要重打；只重装前端与装配：

```bash
bash tools/pack/build_trial.sh     # → build/pack-next/KikuSub-Next.app（1.4G，02:19 完成）
```

- 身份未变：`com.kikusub.desktop.next` / CFBundleName `KikuSub-Next` /
  包内 `app-isolation.json` 仍是 `{appName: KikuSub-Next, dataDirName: KikuSub-Next}` /
  数据根 `~/Library/Application Support/KikuSub-Next`。
- **现役隔离核对**（装配前后各取一次）：
  `build/pack/KikuSub.app/Contents/Info.plist` sha256 恒为 `f0afca4a…4269e`；
  `~/Library/Application Support/KikuSub` 的目录 mtime 未变，
  根目录 4 个 `.json` 的 sha256 前后逐字节一致；
  现役进程（PID 44777 及其 helper）在装配后仍在运行。
- **无窗口冒烟**：用 `KIKUSUB_ISOLATION_ROOT=/tmp/trial-smoke/root` 把数据根挪到临时目录后跑
  `…/MacOS/KikuSub-Next --no-sandbox --screenshot=…`，首启向导正常出现，
  且「模型目录 / 数据与输出目录」都指向 `/tmp/trial-smoke/root`（真实数据根未被这次验证写入）。
- 装配脚本的既有行为：若 `KikuSub-Next.app` 还有一个在跑的旧实例，会先 TERM、
  等不到退出再 KILL（本次强制结束了一个仍在运行/停在退出清场里的旧实例）。
  工作草稿是逐次自动落盘的（`*.autosave_draft.srt`），重新打开即可接着干。

### 7.11 Step 8 三修：纯中性炭黑 + 皇家钴蓝 + 导入页去灰砖（2026-11-26）

用户第三次实测 `KikuSub-Next.app`：前几项修复（一键明暗、去 ①②、朗读面板、单栏居中）都好了，
但**暗色质感、蓝色配色、导入页亮色布局**仍有三个明显缺陷。本轮只动渲染层的令牌与导入页骨架：
**没有碰 `core/` / `server/`，没有新增功能**。

#### 一、暗色：彻底去掉「泛白青灰雾感」（§三修 1）

**问题**：上一版暗色是「偏青灰的 `#1A1C1F → #24272B → #2C3136`」，而且把 `--well`
做成了「6.5% 泛白提亮」。二者叠加 → 底色本身带蓝味、凹槽又往白里提，
于是整个界面浮着一层灰雾，和 FCP 检查器「深底 + 暗槽」的关系正好相反。

**决定（DESIGN.md 新增 *The Nobody's-Teal Rule* 与 *The Raise Lifts, the Well Sinks Rule*）**：

| 令牌 | 旧值 | 新值 | 角色 |
| --- | --- | --- | --- |
| `--stage` | `#0B0D0F` | `#0C0C0E` | 画面房间，全应用最深 |
| `--canvas` | `#1A1C1F` | `#161618` | 工作区地面 |
| `--paper` | `#24272B` | `#1D1D1F` | 侧栏 / 标题栏 / 底栏 / **检查器** |
| `--surface`（新） | — | `#242427` | 面板 / 台本表 / 卡片 |
| `--raise` | `#2C3136` | `#313135`（悬停 `#3A3A3F`） | 按钮 / 浮层 |
| `--well` | `rgba(232,230,224,0.065)` | `#121214` + 7% 白细边 | 输入框 / 滑块底槽 / 标签槽 |

- 三阶全部**中性**（R=G，B 只多 2–3）；字也从中性近白 `#EDEDEF` 取代暖纸白 `#E9E6DF`
  （暖字 + 冷底 = 脏）。
- 抬升层多一道 `inset 0 1px 0 rgba(255,255,255,0.06)` 顶边高光 + `#0E0E10` 暗缝；
  凹槽则加 `--well-line` 7% 白细边勾出形状——**不靠提亮区分凹槽**。
- 凹陷的**方向不再随外观翻转**：`--raise` 永远比它所在的层亮，`--well` 永远更暗。
  上一版把「FCP 控件看起来更亮」套到了**所有** well 上，那其实是 FCP **按钮**的语法。

#### 二、蓝色：换 Studio 皇家钴蓝（§三修 2）

上一版 `#0B63E5` 是干净钴蓝，但和中性灰并置时读起来像**网页链接蓝**。新色板把**填充**与
**文字**拆成两个令牌（填充是一块色，11px 图标/链接是一个字，对比度要求不同）：

| 用途 | 浅色 | 暗色 |
| --- | --- | --- |
| 主按钮填充 / 激活勾选 | `#295CE6`（白字 5.57:1） | `#3467EB`（白字 4.90:1） |
| 悬停 | `#1E4ED8`（6.70:1） | `#3B6DEE`（4.56:1） |
| 蓝铅笔 / 链接 / 激活图标 | `#2453D4`（纸白 6.44 / 铬件 5.91） | `#6B96FF`（铬件 5.96） |
| 选中微底 | `rgba(41,92,230,0.08)` | `rgba(52,103,235,0.16)` |

- **偏一处**：需求给的暗色悬停 `#4274F2` 配白字只有 **4.19:1**，压 4 个色阶到 `#3B6DEE`
  （4.56:1）——肉眼不可分辨，但白字回到合规线。`verify_phase2_shell` 有一条断言守着它。
- **浅色中性底去冷青**：`--paper #F5F5F7`（原 `#F0F2F4`）、`--bg-inspector #FBFBFD`
  （原 `#F7F8F9`）、`--well #F2F2F7`、`--rule #E2E2E7`（原 `#DBE1E6`）；
  所有 `rgba(21,25,28,…)` / `rgba(15,23,30,…)` / `rgba(236,232,223,…)` 一次性换成
  中性 `rgba(0,0,0,…)` / `rgba(255,255,255,…)`。

#### 三、导入页：删掉冗余灰条，重排视觉节奏（§三修 3）

**问题**：有片时「继续核对」卡右侧已有「换片…」，下面却又独立铺了一条全宽灰条
「换一个片子：拖进来，或按 ⌘O 选择」+ 5 个大药丸 `[.mkv][.mp4][.mov][.srt][.vtt]`。
功能完全重复，且整页成了「白底上硬堆四条灰砖」。

**改动**：

1. **整条删除 `.dropstrip` 与五个药丸**（标记 + 样式一起删，不留死样式）。
   换片仍有三条路径：卡内「换片…」按钮、整窗口拖放、`⌘O`。
2. 只保留**一句 12px 纯文本**（`.drop-hint`，`--ink-3`）：「可随时拖入 .mkv / .mp4 / .mov /
   .srt / .vtt 替换片源，或按 ⌘O 选择。」
3. **焦点只剩两处**：继续卡是本页**唯一一块台本纸**（`--surface` + 1px `--rule`），
   因为它承载「上次干到哪」+ 唯一主按钮；「最近打开」与「导出文件夹」退成
   **标题 + 发丝线 + 落在台面上的行**（缩略图仍占 `--well`——那里真的该有底色，它是张封面）。
4. **顺序**：继续卡 → 换片提示 → 最近打开 → 导出文件夹 → 播放能力脚注。
   「最近打开」上提（它才是回来后的第二问），播放能力说明下沉到页脚。

#### 四、2026-11-26 Step 8 复跑

| 检查 | 结果 |
| --- | --- |
| `npm run check` | ✅ 0 error |
| `npm run check:svelte` | ✅ 4/4（基线 4，未上升） |
| `npm run build` | ✅ |
| `npm run test:main` | ✅ **402** |
| `pytest -q` | ✅ **1097 passed / 1 skipped** |
| `tools/shots/verify_*.mjs` | ✅ **25/25 全绿**（`verify_phase2_shell` 54 项） |
| `/impeccable doctor` | ✅ 无漂移（配置健康） |
| `verify_phase2_shell` 对比度 | 亮 16.24 / 6.79 / 5.91 / 5.57 / 发丝 1.35；暗 对应项 ≥4.5 全绿 |
| 新增明度方向断言 | 亮色 well 比台面 −0.109、比铬件 −0.023；暗色 well/raise/panel 方向全对 |

**新增/改动的守卫**：

- `verify_phase2_shell.mjs` 加 5 条**亮度方向**断言（亮 well 更暗、亮 raise 不更暗、
  暗 well 沉在画布与铬件以下、暗 raise 与 surface 比 canvas 亮、暗主按钮悬停配白字 ≥4.5）。
  这类「方向」比绝对值更抗漂移：下次谁再把凹槽提亮，测试直接红。
- `desktop/test/theme-preview.test.mjs` 的 `card` 对账从 `--raise` 改读 `--surface`，
  因为缩略图里那张小卡是**台本纸**，不是浮层按钮。

**顺手抓到的一处真缺陷**：`--bg-content` 改读 `--raise` 后，首启向导 / 引擎设置 /
退出面板的**全窗遮罩与卡片同时读它**，于是暗色下卡片溶进遮罩、只剩一圈阴影。
现在遮罩读 `--canvas`（页面地面）、卡片读 `--raise`（真浮层），
实测三层各不相同：scrim `(22,22,24)` / card `(49,49,53)` / 卡片里的凹槽 `(60,60,64)`。
取证走打包产物：`KIKUSUB_ISOLATION_ROOT=/tmp/… KikuSub-Next --no-sandbox --screenshot=…`。

**基线**：`docs/images/shots/baseline/` 需要在下一轮整体刷新（本轮已重拍取证图）。

#### 五、试用版重新打包（Step 8 收口）

Python 一行未改（`git diff HEAD~4 -- core server tools/kikusub` 为空），所以 sidecar 不需要重打；
只重装前端与装配：

```bash
bash tools/pack/build_trial.sh   # → build/pack-next/KikuSub-Next.app（1.4G）
```

- 身份未变：`com.kikusub.desktop.next` / 包内 `app-isolation.json` 仍是
  `{appName: KikuSub-Next, dataDirName: KikuSub-Next}` / 数据根
  `~/Library/Application Support/KikuSub-Next`。
- **现役隔离核对**（装配前后各取一次）：
  `build/pack/KikuSub.app/Contents/Info.plist` sha256 恒为 `f0afca4a…4269e`；
  `~/Library/Application Support/KikuSub` 的目录 mtime 与根下四个 `.json` 的 sha256
  前后逐字节一致；现役进程（PID 44777）在两次装配后仍在运行。
- **无窗口冒烟**：`KIKUSUB_ISOLATION_ROOT=/tmp/trial-shot2/root` 把数据根挪到临时目录后跑
  `…/MacOS/KikuSub-Next --no-sandbox --screenshot=…`，首启向导正常出现且指向临时根，
  真实数据根未被这次验证写入。

#### 六、取证截图（无窗口，全部 `read_image` 自检过）

| 看什么 | 图 |
| --- | --- |
| 暗色导入：一块台本纸 + 两条发丝线，不再有四条灰砖 | [step8-import-dark.jpg](images/refactor-2026-11/step8-import-dark.jpg) |
| 亮色导入：同上（用户红框那条已删除） | [step8-import-light.jpg](images/refactor-2026-11/step8-import-light.jpg) |
| 暗色核对台：深炭黑阶梯 + 下沉台词框 + 蓝铅笔 | [step8-review-dark.jpg](images/refactor-2026-11/step8-review-dark.jpg) |
| 亮色核对台：中性浅灰铬件 + 纸白 + 皇家钴蓝 | [step8-review-light.jpg](images/refactor-2026-11/step8-review-light.jpg) |
| 暗色导出：分区是标题 + 发丝线，选项块是下沉 well | [step8-export-dark.jpg](images/refactor-2026-11/step8-export-dark.jpg) |
| 暗色转写（三修后同一套令牌） | [step8-transcribe-dark.jpg](images/refactor-2026-11/step8-transcribe-dark.jpg) |
| 暗色设置：引擎 Bento / 占用条 / 分段 | [step8-settings-dark.jpg](images/refactor-2026-11/step8-settings-dark.jpg) |

## 8.9 第一阶段完结封板记录（2026-11-26）

> **用户决定：把当前 `feat/ui-redesign` 作为「前端优化第一阶段」的完结版封板**，
> 推到 GitHub 新分支做云端备份与存档，**暂不合入 `main`**，现役旧版 `KikuSub.app` 继续正常使用。

### 一、封板范围：做了什么、没做什么

**做了（Step 3 → Step 8，全部验收过）**

| 层 | 内容 |
| --- | --- |
| 令牌 | `app.css` 重写为 Cue Script：两套外观（light / dark）× 五个表面令牌（`--canvas / --paper / --surface / --raise / --well`）+ 两个中性遮罩（`--scrim / --scrim-soft`），明朝只换 `--font-cue` |
| 外壳 | 整幅 44px 标题栏（红绿灯 87px 安全区）、232/52 侧栏四段导航、24px 只读底栏、菜单补齐 |
| 页面 | 11 个视图全部按新语法落地：导入 / 转写 / 核对台 / 双引擎复核 / 锁轴润色 / 重排润色 / 双语翻译 / 导出 / 提示词库 / 设置 / 任务详报 |
| 核对台 | 44px cue 页边、检查器去重、走带与浮层精修、译文轨状态条、紧凑模式四条死样式修活 |
| 布局 | 单栏页面统一 1040px 居中（导入例外 760px）；转写页唯一双栏 1120px |
| 弹窗 | 全部浮层统一 `--raise` 卡片 + `--scrim` 遮罩；组件里已无 `--bg-content` 残留 |
| 基线 | 21 张像素基线刷新并自洽（`capture_matrix --compare` / `capture_ai_workbench --compare`） |

**刻意没做（第一阶段的能力边界）**

1. **没有合入 `main`，没有打任何 tag。** `main` 停在 `5e4070f`（0.7.0 收尾），
   `backup/pre-ui-redesign-2026-11` 与 `archive/pre-ui-redesign-2026-11-25` 是只读锚点。
2. **没有改 `core/` / `server/` 一行。** 第一阶段是纯渲染层 + 文档；Python 侧只有既有的
   ASR 空闲卸载租约那一处（Step 6）属于缺陷修复。
3. **没有做**：动效体系（只有三处基本过渡）、VoiceOver 全路径审计、reduced-motion 全量覆盖、
   长片（2 小时 / 500+ 条）滚动性能实测、200% 缩放（红线 14 明确不做）。
4. **`README.md` 未更新。** 成品图仍是旧外观，留待正式合入 `main` 时一起换（本阶段明确不做）。
5. **第二阶段未开工的事项**见本节「五、接续建议」。

### 二、双开工具说明（这个封板版怎么用）

| 项目 | 现役旧版 | 第一阶段封板版 |
| --- | --- | --- |
| 产物 | `build/pack/KikuSub.app` | `build/pack-next/KikuSub-Next.app` |
| bundle id | 旧版原值 | `com.kikusub.desktop.next` |
| 数据根 | `~/Library/Application Support/KikuSub` | `~/Library/Application Support/KikuSub-Next` |
| 构建命令 | `tools/pack/rebuild.sh`（**发版用，勿乱跑**） | `bash tools/pack/build_trial.sh` |
| 隔离标记 | — | 包内 `app-isolation.json` = `{appName: KikuSub-Next, dataDirName: KikuSub-Next}` |

**两版可以同时双击打开**：bundle id、数据根、`.app` 路径三者都不同，没有任何共享写入点。
渲染层新增偏好（外观、字幕字体、最近打开、最近打开的视图样式）只进 `localStorage`，
每个 `--user-data-dir` 天然隔离，不进共享的 `settings.json`。

**验证用的无窗口路径**（智能体只用这条）：

```bash
bash tools/pack/build_trial.sh                                   # 重打试用版（不开窗）
KIKUSUB_ISOLATION_ROOT=/tmp/x/root KIKUSUB_NO_WINDOW=1 \
  build/pack-next/KikuSub-Next.app/Contents/MacOS/KikuSub-Next \
  --no-sandbox --user-data-dir=/tmp/x/profile --screenshot=/tmp/x/a.png
```

**隔离核对基线**（每次装配前后各取一次，两次必须逐字节一致）：
`build/pack/KikuSub.app/Contents/Info.plist` sha256 = `f0afca4a…4269e`；
`~/Library/Application Support/KikuSub` 根下 4 个 `.json` 的 sha256
（`preferences` `6b72cdc8…`、`presets` `071b1151…`、`prompts` `1a7b0ab8…`、`settings` `70200051…`）。

> 装配脚本会先 TERM（等不到再 KILL）一个仍在运行的旧 `KikuSub-Next` 实例。
> 工作草稿是逐次自动落盘的（`*.autosave_draft.srt`），重新打开即可接着干；
> **现役 `KikuSub.app` 不受影响**，装配全程不碰它的进程。

### 三、GitHub 分支存档

```bash
git push -u origin feat/ui-redesign      # 只推分支，不推任何 tag
```

**推送前安全核查（2026-11-26 逐项做过，结论留档）**

| 检查 | 结果 |
| --- | --- |
| `.github/workflows/ci.yml` 的触发面 | `on.push.branches: [main, app/macos]` + `on.push.tags: ["v*"]`；推 `feat/ui-redesign` **不触发任何 job**（也不在 PR 里），`release-tag` 闸门不受影响 |
| 是否推 tag | **不推**。`release-tag` 要求「tag == `desktop/package.json` version」且「tag 提交在 `main` 上」，封板版不满足第二条 |
| `git status` | 干净（无未跟踪、无脏文件） |
| 是否含打包产物 | `git ls-files` 里没有 `build/`、`desktop/renderer/dist/`、`node_modules/`、`pack-next`、`.impeccable/`、`.venv/` |
| 最大被跟踪文件 | 210 KB（`desktop/package-lock.json`）；全仓无 >1 MB 的入库文件 |
| 密钥 / 凭证 | 无。唯一命中是 `docs/sprints/…/设计稿.html` 里的占位符 `sk-xxxxxxxx…`（HTML 示意，非真实密钥） |
| 本机隐私路径 | 本分支相对 `main` 的 diff 里 **0 处** `/Users/sws`；历史文档里的旧路径未在本分支新增 |
| `docs/images/` | 全部是 `.png/.jpg`，无 sidecar 文本；图片 EXIF 里无路径；取证图只用 `kikusub-shot-media.mp4` 这种脱敏测试素材 |
| 远端是否已存在该分支 | 否（`git ls-remote --heads` 只有 `app/macos` / `main` / `review/final-polish` / `workbuddy/…`），不会覆盖任何东西 |
| `git push --dry-run` | `* [new branch] feat/ui-redesign -> feat/ui-redesign`，凭证可用 |

- **为什么不推 tag**：`.github/workflows/ci.yml` 的 `release-tag` job 触发条件是
  `startsWith(github.ref, 'refs/tags/v')`，它检查「tag 名 == `desktop/package.json` 的 version」
  且「tag 提交在 `main` 上」。封板版不在 `main` 上，任何 `v*` tag 都会让那条闸门直接红。
  分支推送只触发 `pull_request` / `workflow_dispatch` 以外的默认分支过滤——`on.push.branches`
  只列了 `main` 与 `app/macos`，所以**推 `feat/ui-redesign` 不会触发 CI**，是纯备份。
- **不覆盖远端 `main`**：`git push` 的目标分支显式写成 `feat/ui-redesign`，不带 `--force`。

### 四、认知负担提醒（接手的人先看这三条）

1. **本分支是沙盒，不是主线。** 任何要进用户日常的改动都必须走
   `feat/ui-redesign` → 验收 → 合 `app/macos`/`main` 的既定路线（见 `docs/release.md`）。
2. **令牌只有五个表面档位。** 新写组件时先问「这是画布 / 铬件 / 面板 / 抬升层 / 凹槽」，
   不要新造一个 rgba；`verify_phase2_shell.mjs` 会用**明度方向**断言抓住「凹槽被提亮」。
3. **基线是本分支的自洽基线。** 合入 `main` 前若主线外观不同，需要在那条线上重拍一次，
   不要直接把这 21 张带过去。

### 五、未来开启第二阶段时的接续建议

按投入产出排序，前两条是真正的短板：

1. **合入主线的准备工作**（必须做）：在 `app/macos` 上重放令牌，核对 `docs/contracts/`
   三份契约的差异；把 `README.md` 成品图换成新外观；跑一次
   `bash tools/release/preflight.sh --with-tests`。这一步没有新设计，只有对账与验证。
2. **动效体系**：现在只有三处基本过渡（页面进入、浮层淡入、卡片 stagger）。
   第二阶段可以补「核对台播放 / 跳句时的轴跟随」「提案到达时的行内提示」这一类
   **有语义的动效**，并同步做 `prefers-reduced-motion` 的全量覆盖与审计。
3. **长片与窄窗实测**：24 分钟跑通过了，但 2 小时 / 500+ 条的滚动、拖拽、长列表手感
   没有量化数据；1080×680 之外的窄窗（分屏 900px 以下）只做了结构收缩，没做走查。
4. **可达性补全**：VoiceOver 全路径、键盘焦点全链路、对比度在自定义主题下的兜底。
   `apple-design` 审查里第 10 条（键盘/焦点/VoiceOver 必须可用）目前只做了前半。
5. **可选项**：把 `DESIGN.md` 的五个表面令牌抽成一份 JSON，让原型与实现共用一份源
   （现在是 `theme-preview.test.mjs` 对账兜底，够用但仍是两个来源）。

## 8.10 第二阶段 Batch 1：导入页融合重构（2026-11-26）

> 分支 **`feat/ui-redesign-p2`**（从封板的 `feat/ui-redesign` 切出）。`feat/ui-redesign` 冻结不动、
> `main` 不动、现役 `build/pack/KikuSub.app` 与 `~/Library/Application Support/KikuSub` 零触碰。
> 本批次**不重打 1.4G 的 `.app`**：等几批页面调完再统一打包。

### 一、用户口径（老版 / 本版并排对比后）

用户把老版导入页（图 1）与本版导入页（图 2）并排看过，给了四条：

1. **骨架向老版靠拢**：删掉顶部「继续核对 `⌘3` | 换片…」卡与其下那行 12px 替换提示，
   恢复老版**大虚线拖放区**（拖入视频或字幕 + 图标 + `.mkv/.mp4/.mov/.srt/.vtt`）作为主视觉——
   **无论当前有没有打开的工程，导入页都保持这块拖放区**。要接着干上一部，点「最近打开」或切去核对台。
2. **区块顺序回到老版**：① 拖放区 + MKV/HEVC 代理说明 → ② 导出文件夹 → ③ 最近打开（保留列表 / 网格切换）。
3. **视觉语言沿用第一阶段令牌**：不退回老版发青的旧蓝；拖放区 / 导出文件夹 / 最近打开（含网格封面卡与列表）
   只用 `--canvas / --well / --fill / --rule / --text* / --accent*`，保持新版居中与发丝线节奏。
4. **按钮去掉尾部省略号**：`导入原文…` → `导入原文`；`换片…` 随卡片一起消失。即使是打开对话框的次级入口也不再带 `…`。

### 二、改了什么

| 文件 | 改动 |
| --- | --- |
| `desktop/renderer/src/views/ImportView.svelte` | 删 `.resume` 卡、`.drop-hint` 与 `setView` 依赖（标记 + 样式一起删，不留死样式）；拖放区无条件渲染并回到首屏主位；顺序改为 拖放区 → 代理说明 → 导出文件夹 → 最近打开；`导入原文…` → `导入原文`；扩展名 chip 从裸 `ui-monospace` 换成 `--font-mono` + `--rad-control` |
| `docs/contracts/review-console.md` | 新增 §3.4.28（现行口径）；§3.4.26 顶部标出被撤销的范围 |
| 本文 | 本节 + §1 状态表 + §2.5 脚注 + §10 决策日志 + §11 交接清单 |

### 三、测试 / 台账核查

- **没有断言依赖这张卡**：全仓检索 `继续核对` / `继续当前工程` / `.resume` / `换片…`，
  `tools/shots/verify_*.mjs`、`desktop/test/`、`tests/` 均无命中；唯一引用是本文与
  `docs/contracts/review-console.md` 的叙述，已同步到新口径。**不需要向用户申请改断言**。
- **新增守卫**：`tools/shots/verify_import_page.mjs`（15 条断言）把「大拖放区是唯一主视觉」
  冻住，下次谁再按「有片 / 无片」分叉出第二套骨架就会直接红。
- **像素基线**：`capture_matrix.sh --compare` 的 `import` 一张必然为红（PSNR 21.3 dB）——那是本次
  刻意改版，待用户确认截图后与 §8.10 一起重拍（其余 9 张不受影响）。

### 四、验证

| 项 | 结果 |
| --- | --- |
| `npm run check`（tsc） | ✅ 0 错 |
| `npm run check:svelte` | ✅ 4/4 与基线持平（版本 4.7.8） |
| `npm run build` | ✅ 通过 |
| `npm run test:main` | ✅ 402/402 |
| `pytest -q tests/test_docs_health.py` | ✅ 6/6 通过（本次新增链接全部可解析） |
| `node tools/shots/verify_import_page.mjs` | ✅ 15/15（**新增**结构回归：有片时拖放区仍 760 宽、`.resume`/`.drop-hint` 不存在、三块顺序、五个 chip、按钮无尾 `…`、列表/网格可切） |
| `capture_matrix.sh --states "import" --compare` | ⚠️ PSNR **21.3 dB**（基线是旧版三块灰砖）——本次刻意改版的预期差，基线待确认后重拍 |

### 五、取证截图（无窗口 `--screenshot`，全部 `read_image` 自检）

| 看什么 | 图 |
| --- | --- |
| 亮色列表：拖放区回到主视觉、导出文件夹在最近打开之前、按钮无 `…` | [p2-import-light-list.png](images/refactor-2026-11/p2-import-light-list.png) |
| 亮色网格：封面画廊三列，封面仍是 `--fill` 底 + 秒数徽标 | [p2-import-light-grid.png](images/refactor-2026-11/p2-import-light-grid.png) |
| 暗色列表：纯中性炭灰台面，虚线仍走 `--accent-line` | [p2-import-dark-list.png](images/refactor-2026-11/p2-import-dark-list.png) |
| 暗色网格：同上 | [p2-import-dark-grid.png](images/refactor-2026-11/p2-import-dark-grid.png) |
| 空态（无片）：与有片时**同一块**拖放区，只少了「最近打开」一节（没有历史） | [p2-import-empty-light.png](images/refactor-2026-11/p2-import-empty-light.png) |

> 截图用的是本机真实的演示短视频（8s / 14s / 22s 三段渐变素材，放在 `/private/tmp`），
> 「最近打开」的时长与体积就是文件本身的值——不编造 GB 级读数。与既有基线
> `import-1360x838.png` 同视口（1360×838 @2x）。

## 8.11 第二阶段 Batch 2：令牌治本 + AI 三页（2026-11-26）

> 分支 **`feat/ui-redesign-p2`** 继续。`feat/ui-redesign` 冻结不动、`main` 不动、现役
> `build/pack/KikuSub.app` 与 `~/Library/Application Support/KikuSub` 零触碰。
> 本批次仍**不重打 1.4G 的 `.app`**（用户要求几批页面调完再统一打包）。

用户把老版《翻译》（图 1）与本版《锁轴润色》（图 2）并排看后，定位到「不管怎么改，界面总有
灰底白框按钮、甚至下拉框只看得见一个三角」不是组件问题，而是**设计系统令牌层的三处缺陷**。
Batch 2 先治本、再精修 AI 三页，不改大布局。

### 一、治本：三处设计系统缺陷

| 缺陷 | 根因 | 修正 |
| --- | --- | --- |
| 下拉框 / 数字框隐身，只剩一枚三角 | 亮色 `--well-line: transparent`；`--well #F2F2F7` 与工具栏 `--paper #F5F5F7` 只差 2 个色阶 | 亮色 `--well-line: rgba(0,0,0,0.14)`；暗色 `rgba(255,255,255,0.13)`（原 `0.07`）。所有 `<select>` / `<input>` / `<textarea>` / `.field` / `.ai-input` 都走这一条线；`transparent` 被写进 DESIGN.md 的禁令 |
| 满屏「灰底白框按钮」 | 页内命令栏铺 `--paper` / `--bg-inspector` 灰底，`.btn` 却读 `--raise` 白底；DESIGN.md YAML 的 `button-secondary` 写 `{colors.panel}`，正文写 `--raise` | **严格区分窗口外壳与页内工具栏**：`--paper` 只给侧栏 / 标题栏 / 底栏 / 时间轴坞；AI 三页的标题行、命令栏、粘贴区、应用条全部回到 `--canvas`，只用 1px 发丝线分隔。`.btn` 改用 `--btn-bg / --btn-bg-hover / --btn-line / --btn-line-hover` 四个令牌：亮色纸白 + 0.14 黑细边、悬停微浅中性底，暗色抬升层 + 0.13 白细边。DESIGN.md YAML 与正文同步 |
| 日语汉字与假名呈中文字形 | `--font-cue` 继承 `--font-sans`，`PingFang SC` 排在 `Hiragino Sans` 前面 | sans 态的 `--font-cue` 固定为 `'Hiragino Sans', 'Hiragino Kaku Gothic ProN', 'SF Pro Text', 'PingFang SC', sans-serif`；mincho 态不动。中文仍由后置的 PingFang 兜底，不需要按语种切字体 |

DESIGN.md 同时新增 **The Chrome Is Not a Page Toolbar Rule**，并把「well line 不许透明」写进
Named Rules 与 Option blocks 的例外段；控制项边线、按钮边线与字体栈的说明都改成代码现值。

**顺带修好的验证基建**：截图模式此前仍受生产最小窗宽 1080px 约束，`verify_phase2_shell`
的 880px「紧凑模式」用例实际一直量到 1080px，「侧栏 52px」必红。现在只在 `--screenshot`
（透明窗口 / `show:false`）路径把最小尺寸放宽到请求尺寸；人类窗口与打包版仍是 1080×680。

### 二、AI 三页（锁轴 / 重排 / 双语翻译）

| 区域 | 改动 |
| --- | --- |
| 顶部工具栏 | `.aiw-page / .aiw-head / .aiw-cmd-row` 全部改为 `--canvas`，命令栏去掉 `--bg-inspector` 灰底；标题行 / 说明行 / 命令栏 / 表格 / 底栏统一 **24px 页边**；下拉框与按钮统一 **28px** 高；`模板` / `处理范围` / `译为` / `1 ~ 246` / `每批 150 条` 全部有 1px 可见边线 |
| 次要入口 | 动作按钮去掉尾部 `…`（`导入建议文件` / `粘贴结果` / `导入建议` / `另存` / `导入 B`）；页内指路 `断句本身错了？去重排润色 →` 改为 `--ink-2` 常态、悬停才上蓝的次级链接，和说明同排 |
| 外部手动粘贴区 | 背景回台面；输入框用 `--well-focus` + 1px `--well-line`，留白 10/12；底部 `解析成建议` 主键 + `取消` 纸白键 + 右侧校验提示；`将替换当前建议` 仍是 warn 胶囊 |
| 表格 | 表头 500 字重、24px 页边、更松的行距；空态 `—` 去掉虚线框，退成 46% 透明度的极轻占位；有提案时终稿改为「极淡蓝 + `accent-line` 1px 勾边」的文本卡片，采纳勾统一成 20px 方形小键（未选中是空格子，选中才是蓝底白勾） |
| 重排页 | `body / side / preview` 三层灰带全部改为 `--canvas` + 1px 分栏线；步骤卡仍是 well，卡头不再另铺灰；粘贴 / 拖入区从虚线圈改成 1px 实线输入框，聚焦才上蓝环 |
| 双语翻译 | 时间码从「每行都是蓝字」退回 `--ink-2`，hover 才上强调；译文列与润色页共用同一套终稿卡片语法；底部应用条与表格同台面 |

### 三、新增守卫

**`tools/shots/verify_ai_toolbar_controls.mjs`（新，22 条断言）** 不靠截图，在渲染进程里读计算样式：

- `--well-line` 亮 / 暗 alpha ≥ 0.10；`--font-cue` 以 Hiragino Sans 起头；
- `.aiw-page` / `.aiw-head` 与 `--canvas` 同色，`.aiw-cmd-row` 背景透明、只留 1px 发丝线；
- `.aiw-head` 内 5 个 `<select>` / `<input>` 每一个都有 ≥1px 且 alpha ≥0.10 的边线（或与真实台面
  ≥0.025 明度差）；纸白键同样必须有边线；
- 下拉框与按钮同为 28px；工具栏动作按钮无尾部 `…`。

`tests/style-drift.test.cjs` 的「间距必须用 `--sp-N`」一并被触发，新增的 24 / 12 / 8 / 4px
全部改为令牌；`npm run test:main` 402/402。

### 四、验证

| 项 | 结果 |
| --- | --- |
| `npm run check`（tsc） | ✅ 0 错 |
| `npm run check:svelte` | ✅ 4/4 与基线持平（4.7.8） |
| `npm run build` | ✅ 通过 |
| `npm run test:main` | ✅ 402/402（含 style-drift 三条） |
| `node tools/shots/verify_ai_toolbar_controls.mjs` | ✅ 22/22（**新增**；亮 / 暗各 11 条） |
| `node tools/shots/verify_phase2_shell.mjs` | ✅ |
| `node tools/shots/verify_import_page.mjs` | ✅ 15/15（全局 `.btn` / `--well-line` 改动未回退 Batch 1） |
| `node tools/shots/capture_ai_workbench.mjs --themes light,dark --states polish-dual,polish-paste,reshape-draft,reshape-paste,translate-proposal,translate-paste` | ✅ 12/12（新增 4 个状态：锁轴粘贴 / 重排粘贴 / 翻译提案 / 翻译粘贴） |
| 关联回归（无窗口） | ✅ `verify_gap_fill` / `verify_clip_scope` / `verify_translation_flow` / `verify_batch_and_align` 全绿 |
| `pytest -q tests/test_docs_health.py` | ✅ 6/6 |
| 重打 `.app` | — 本轮**不做**，按用户要求等后续页面批次一起打包 |

> 沙箱环境跑 Electron 需 `KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox`；这是既有约定，
> 不是本次新增的窗口路径。全程 `--screenshot` 透明窗口取帧，未开任何可见窗口。

### 五、取证截图（2608×1607 @2x，全部 `read_image` 自检）

| 状态 | 日间 | 夜间 |
| --- | --- | --- |
| 锁轴 · 已有提案 | [p2-ai-polish-proposal-light.png](images/refactor-2026-11/p2-ai-polish-proposal-light.png) | [p2-ai-polish-proposal-dark.png](images/refactor-2026-11/p2-ai-polish-proposal-dark.png) |
| 锁轴 · 展开粘贴框 | [p2-ai-polish-paste-light.png](images/refactor-2026-11/p2-ai-polish-paste-light.png) | [p2-ai-polish-paste-dark.png](images/refactor-2026-11/p2-ai-polish-paste-dark.png) |
| 重排 · 已预检 | [p2-ai-reshape-draft-light.png](images/refactor-2026-11/p2-ai-reshape-draft-light.png) | [p2-ai-reshape-draft-dark.png](images/refactor-2026-11/p2-ai-reshape-draft-dark.png) |
| 重排 · 展开粘贴框 | [p2-ai-reshape-paste-light.png](images/refactor-2026-11/p2-ai-reshape-paste-light.png) | [p2-ai-reshape-paste-dark.png](images/refactor-2026-11/p2-ai-reshape-paste-dark.png) |
| 双语翻译 · 已有译文 | [p2-ai-translate-proposal-light.png](images/refactor-2026-11/p2-ai-translate-proposal-light.png) | [p2-ai-translate-proposal-dark.png](images/refactor-2026-11/p2-ai-translate-proposal-dark.png) |
| 双语翻译 · 展开粘贴框 | [p2-ai-translate-paste-light.png](images/refactor-2026-11/p2-ai-translate-paste-light.png) | [p2-ai-translate-paste-dark.png](images/refactor-2026-11/p2-ai-translate-paste-dark.png) |

## 8.12 第二阶段 Batch 3：六套双模色板 + 可扩展配色架构（2026-11-26）

> 分支 **`feat/ui-redesign-p2`**。`feat/ui-redesign` 冻结不动、`main` 不动、现役
> `build/pack/KikuSub.app` 与 `~/Library/Application Support/KikuSub` 零触碰。
> 本批次把配色从「一套蓝灰」升级为**可扩展的多色板正交体系**，一次性内置 6 套双模主题，
> 重打试用版，并把第二阶段全部未推送提交推到 GitHub。

### 一、架构：色板只换基色，派生令牌全部动态计算

配色现在是 **两个正交轴**：

| 轴 | 属性 | 取值 | 回答 |
| --- | --- | --- | --- |
| 明暗 | `html[data-theme]` | `light` / `dark`（由 `auto` / `light` / `dark` 解析） | 现在是日间还是夜间 |
| 色板 | `html[data-palette]` | `cobalt`（默认）/ `nord` / `rose-pine` / `everforest` / `catppuccin` / `cinema-amber` | 这一面用哪套基色 |

`cobalt` 不在 CSS 里另开覆写块：它就是 `:root`（浅色）与 `html[data-theme='dark']`（深色），
数值与第一阶段封板逐字一致；其余 5 套各写两个
`html[data-palette='<id>'][data-theme='light'|'dark']` 基色块。**加一套色板 = 两块 CSS +
`themes.ts` 注册表一条**，组件不写任何主题分支。

派生令牌统一改成 `color-mix(in srgb, var(…))`，不再有第二份写死的蓝灰：

| 令牌组 | 来源 |
| --- | --- |
| `--bg-toolbar / --bg-status / --bg-sidebar` | 当前 `--paper` × 明暗 alpha（90/94/74% 亮、92/96/90% 暗） |
| `--line / --line-2 / --fill / --fill-strong / --row-hover / --well-line / --scroll-thumb / --cue-lane / --cue-wash / --cue-block / --cue-block-hover` | 明暗方向的中性墨（亮黑 / 暗白）按 alpha 派生 |
| `--accent-soft / --accent-ring / --accent-line / --cue-block-active / --cue-edge / --meter-a` | 当前 `--accent` 或 `--accent-text` 按 alpha 派生 |
| `--btn-bg / --btn-bg-hover / --well-focus / --raise-hover` | 当前 `--raise` / `--well`；暗色抬升层再上一阶 |
| `--stage-bg / --stage-line / --stage-frame` | 亮色 = `canvas × ink` 的房间色；暗色 = 色板的 `--stage` |
| `--danger-soft / --warn-soft / --success-soft` | 当前状态色按 10%/14% 派生 |

顺带修掉两个真实缺陷：

1. **Canvas 2d 不认 `color-mix()`**：波形画布原来直接把令牌字符串塞给 `fillStyle`，
   派生令牌一换就会静默保留上一笔颜色。新增 `resolveCssColor()`：隐藏探测元素把
   `color-mix` / `var()` 解析成 `rgb()/rgba()`，`color(srgb …)` 再归一化，画布才拿到真颜色。
2. **QaPanel 两处写死色**：暗色分段胶囊的 `rgba(236,241,250,.14)` 改成从当前
   `--raise` 抬 7% 墨；危险悬停的 `rgba(179,38,30,.08)` 改走 `--danger-soft`。

### 二、六套色板

| id | 名称 | 浅色气质 | 深色气质 | 强调色（亮 / 暗） |
| --- | --- | --- | --- | --- |
| `cobalt` | 皇家钴蓝 | 纸白 + 中性浅灰铬件 | 纯中性炭黑 + 下沉暗槽 | `#295CE6` / `#3467EB` |
| `nord` | 北欧极夜 | Snow Storm 冷调纸面 | Polar Night 极夜蓝灰 | `#456E9E` / `#4772A6` |
| `rose-pine` | 玫瑰松木 | Dawn 暖手稿纸 | Main 黑胶紫墨 | `#286983` / `#31748F` |
| `everforest` | 暮森护眼 | 暖纸米色 | 深林绿灰 | `#277355` / `#2B7E5E` |
| `catppuccin` | 拿铁与摩卡 | Latte 清凉拿铁 | Mocha 紫调摩卡 | `#1E66F5` / `#3B6CE2` |
| `cinema-amber` | 暗房琥珀 | 暖白暗房纸 | 放映间近黑 | `#B45309` / `#B8590C` |

全量基色（canvas / paper / surface / raise / well / ink / rule / accent / accent-text /
danger / stage）在 `app.css`；`themes.ts` 的 `PALETTES` 只保留缩略图要用的子集，
`desktop/test/theme-preview.test.mjs` 逐项对账，任何一边漂移都会红。

**校准偏差（实测后 1–3 个色阶，全部为对比度，不改变色相气质）：**

| 位置 | 指定值 | 落地值 | 原因 |
| --- | --- | --- | --- |
| catppuccin 浅色 `--accent-text` | `#1E66F5` | `#1B61E8` | paper 上 4.34:1 → 4.74:1（11px 标签必须过线） |
| catppuccin 深色 `--accent-hover` | `#4273EB` | `#3D6DE4` | 白字 4.30:1 → 4.66:1 |
| rose-pine 深色 `--accent-hover` | `#3982A0` | `#357C99` | 白字 4.31:1 → 4.67:1 |
| everforest 深色 `--accent-hover` | `#318A68` | `#2F8163` | 白字 4.23:1 → 4.73:1 |
| cinema-amber 深色 `--accent-hover` | `#C66310` | `#B95D0E` | 白字 4.04:1 → 4.53:1 |
| nord / everforest 深色 `--danger` | 默认 `#E5776A` | `#ED8F84` | surface 上 4.27 / 4.15:1 → 4.66 / 4.76:1 |

rose-pine 浅色正文 6.66:1：高于 4.5:1 要求、低于 cobalt 的 7:1 AAA 档。这里保留用户给的
`--ink #575279`，没有为凑 7:1 去压深主文字；cobalt 的 7:1 断言仍然单独保留。浅色色板
**不强行要求 `raise > surface`**（用户给的值大多相等，rose-pine 甚至 surface 高一档）：
日间是纸台面，真正必须守住的是 **well 沉在 canvas 以下**；暗色才守
**raise > surface > canvas**。

### 三、设置页「界面配色」

「设置 → 外观与朗读」新增「界面配色」区：6 张统一缩略卡，**实时跟随当前明暗**显示该色板的
浅色或深色版本（`paletteShot(id, resolvedTheme)`），点一下立即生效。卡片本身仍是台面上一块
`--well` 凹陷填充，选中才加 `--accent-line` 细须；缩略图只画 canvas / paper / surface / ink +
一个强调色，没有第二组彩色提示。偏好写 `localStorage['kikusub.palette']`，每个
`--user-data-dir` 天然隔离，不进共享 `settings.json`。

### 四、验证

| 项 | 结果 |
| --- | --- |
| `npm run check`（tsc） | ✅ 0 错 |
| `npm run check:svelte` | ✅ 4/4 与基线持平（4.7.8） |
| `npm run build` | ✅ 通过 |
| `npm run test:main` | ✅ **405/405**（新增 3 条：色板默认 / 落盘 / 三 data 属性 + 色板对账 4 条） |
| `python -m core.smoke` | ✅ 通过 |
| `pytest -q` | ✅ **1096 passed / 2 skipped**（1 个 OmniVoice 权重 skip、1 个既有 skip） |
| `node tools/shots/verify_phase2_shell.mjs` | ✅ **64/64**（新增 12 组合矩阵 8 组断言 + 逐套实算表） |
| 全量 `tools/shots/verify_*.mjs` | ✅ 见 §8.12 五（汇总） |
| `node tools/shots/capture_palettes.mjs` | ✅ 8/8 张（设置页 2 + 代表色板核对台 6） |

`verify_phase2_shell` 现在在**同一个渲染进程里**依次改 `data-palette` / `data-theme`，
遍历 6 × 2 = 12 种组合，读真实计算样式而不是 CSS 文本：

- 正文墨对纸面 ≥4.5:1（cobalt 的亮 / 暗两条另按 ≥7:1 守）；
- 11px 标签对纸 / well / surface ≥4.5:1；
- 强调文字对纸 / canvas / surface ≥4.5:1；
- 主按钮白字 **常态 + 悬停** ≥4.5:1；
- 朱 / 警示 / 通过文字 ≥4.5:1；
- 输入框 / 下拉框边线可见：`--well-line` alpha ≥0.10、对纸 ≥1.15、按钮边线 ≥1.15；
- 明度方向：well < canvas（两种模式都成立）；暗色 raise > surface > canvas；
- 舞台明度方向 + 1px 发丝线 / `--rule` 可见。

实算表（正文 / 11px 标签 / 强调 / 主按钮常态+悬停 / 输入边线 / well−canvas）：

| 色板 | 明暗 | 正文 | 标签 | 强调 | 主按钮 | 输入边线 | well−canvas |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cobalt | 日 / 夜 | 16.24 / 14.39 | 6.79 / 6.47 | 5.91 / 5.96 | 5.57/6.70 · 4.90/4.56 | 1.37 / 1.48 | −0.109 / −0.002 |
| nord | 日 / 夜 | 10.84 / 10.84 | 6.40 / 6.79 | 5.45 / 6.24 | 5.28/6.67 · 4.97/5.83 | 1.37 / 1.50 | −0.133 / −0.006 |
| rose-pine | 日 / 夜 | 6.66 / 12.50 | 5.64 / 6.43 | 5.59 / 9.68 | 6.11/8.05 · 5.22/4.67 | 1.38 / 1.49 | −0.135 / −0.003 |
| everforest | 日 / 夜 | 7.15 / 8.15 | 5.18 / 5.84 | 5.33 / 6.51 | 5.72/7.45 · 4.94/4.73 | 1.38 / 1.51 | −0.191 / −0.006 |
| catppuccin | 日 / 夜 | 7.06 / 11.34 | 4.98 / 7.37 | 4.74 / 7.79 | 4.91/6.39 · 4.74/4.66 | 1.38 / 1.49 | −0.126 / −0.003 |
| cinema-amber | 日 / 夜 | 14.91 / 14.45 | 6.35 / 6.21 | 5.77 / 8.03 | 5.02/6.48 · 4.70/4.53 | 1.38 / 1.49 | −0.162 / −0.002 |

### 五、全量 `verify_*.mjs`

`tools/shots/` 下 **29 个**回归脚本全部跑过（`KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox`
以适配本机沙箱），最终 **29/29 绿**：

| 组 | 脚本 |
| --- | --- |
| 外壳 / 导入 / AI 工具栏 | `verify_phase2_shell`（64 项）、`verify_import_page`（15）、`verify_ai_toolbar_controls`（22） |
| 核对台 | `verify_review_defaults`、`verify_review_transport`、`verify_review_overlays`、`verify_review_viewport`、`verify_scrub_pan`、`verify_cue_selection`、`verify_cue_clipboard`、`verify_gap_fill`、`verify_clip_scope`、`verify_punct_clean`、`verify_tts_panel_fit` |
| 双引擎 / 提案 / 翻译 / 重排 | `verify_arbitration`、`verify_arbitration_dialog`、`verify_batch_and_align`、`verify_dual_lowdiff`、`verify_external_proposals`、`verify_reshape_flow`、`verify_translation_flow` |
| 章节 / 设置 / 转写 / 其他 | `verify_chapters`、`verify_chapter_panel`、`verify_chapter_edge`、`verify_chapter_draft`、`verify_settings_ai_fold`、`verify_settings_layout`、`verify_cli_settings`、`verify_transcribe_flow` |

> `verify_ai_toolbar_controls` 第一轮在「读 `--well-line` 原始串」这一步红了两条：
> 它把 `getComputedStyle` 里的 `color-mix(...)` 当成空颜色（alpha 0）。这不是界面回归，
> 而是验证脚本也需要 Batch 3 的解析器。补上 `color(srgb …)` / 探测元素解析后 22/22 通过。
>
> `capture_matrix.sh --compare docs/images/shots/baseline` 也跑过（10 张）。基线仍是
> Batch 1/2 之前的旧图，导入 / AI 三页 / 设置页的差异是前两批**刻意改版**，本轮没有回退；
> 核对台与钴蓝外观的当前截图与基线逐项目视一致，PSNR 偏低主要来自字体抗锯齿与
> 前两批已存在的差异，不把这一项当作本批次的门禁。

### 六、取证截图（无窗口 `--screenshot`，全部 `read_image` 自检）

| 看什么 | 图 |
| --- | --- |
| 设置 → 外观与朗读：6 张浅色色板卡（皇家钴蓝选中） | [p2-palette-settings-light.png](images/refactor-2026-11/p2-palette-settings-light.png) |
| 同上，夜间：6 张卡一起翻到深色版本 | [p2-palette-settings-dark.png](images/refactor-2026-11/p2-palette-settings-dark.png) |
| 玫瑰松木 · 日间核对台：暖手稿纸 + 松木青 | [p2-palette-rose-pine-light.png](images/refactor-2026-11/p2-palette-rose-pine-light.png) |
| 玫瑰松木 · 夜间核对台：黑胶紫墨 + `#9CCFD8` 文字 | [p2-palette-rose-pine-dark.png](images/refactor-2026-11/p2-palette-rose-pine-dark.png) |
| 北欧极夜 · 日间核对台：Snow Storm 冷纸 | [p2-palette-nord-light.png](images/refactor-2026-11/p2-palette-nord-light.png) |
| 北欧极夜 · 夜间核对台：Polar Night 蓝灰阶梯 | [p2-palette-nord-dark.png](images/refactor-2026-11/p2-palette-nord-dark.png) |
| 暗房琥珀 · 日间核对台：暖白纸 + 琥珀强调 | [p2-palette-cinema-amber-light.png](images/refactor-2026-11/p2-palette-cinema-amber-light.png) |
| 暗房琥珀 · 夜间核对台：放映间近黑 + 琥珀 | [p2-palette-cinema-amber-dark.png](images/refactor-2026-11/p2-palette-cinema-amber-dark.png) |

> 截图脚本：`node tools/shots/capture_palettes.mjs`（8 张一次生成；换主题 / 色板走真实点击
> 设置页卡片，不是只改 DOM 属性，所以缩略图的 `resolved` 预览与页面配色一致）。
> 视口 1440×900 @2x，落在 `docs/images/refactor-2026-11/`。

### 七、打包与 GitHub 推送

**试用版重打（2026-11-26 14:03）：**

```bash
bash tools/pack/build_trial.sh
# 完成（未打开窗口）：build/pack-next/KikuSub-Next.app
# 身份：bundle id com.kikusub.desktop.next；数据根 ~/Library/Application Support/KikuSub-Next
# 1.4G
```

| 项 | 值 |
| --- | --- |
| 产物 | `build/pack-next/KikuSub-Next.app` |
| 大小 | **1.4 GB**（内置 sidecar 1.0G + ffmpeg 147M + CLI） |
| bundle id | `com.kikusub.desktop.next` |
| 隔离标记 | `Contents/Resources/app-isolation.json` = `{appName: KikuSub-Next, dataDirName: KikuSub-Next}` |
| Python 侧 | 本轮**未改** `core/` / `server/` / `tools/kikusub/`；`build_trial.sh` 自动判定 sidecar / CLI 仍是最新，跳过重打 |
| 无窗口冒烟 | `KIKUSUB_ISOLATION_ROOT=/tmp/… KIKUSUB_NO_WINDOW=1 … --screenshot=/tmp/…/shot.png` 退出码 0，首启向导正常 |
| 现役旧版 | `build/pack/KikuSub.app/Contents/Info.plist` sha256 仍为 `f0afca4a…4269e`（`git`/装配全程未写入）；`~/Library/Application Support/KikuSub/settings.json` / `presets.json` / `prompts.json` 三个哈希与 §8.9 记录一致。`preferences.json` 的 mtime 为 **12:58:50**（本轮开始前由用户自己的 `KikuSub.app` 正常写入），不是本次工具链改动 |

**GitHub 推送：**

```bash
git push -u origin feat/ui-redesign-p2   # 只推分支，不推 tag，不碰 main
```

- 远端：`https://github.com/Alansws/KikuSub.git`；目标分支 `feat/ui-redesign-p2`（此前远端只有
  `feat/ui-redesign` @ `91f9bbb`，所以这是 6 个提交的**新分支**，不是 force push）。
- 推送内容：第二阶段 Batch 1（导入页）、Batch 2（AI 三页 / 令牌治本）、Batch 3（本批色板）全部提交。
- 不推 tag：`ci.yml` 的 `release-tag` 要求 tag == `desktop/package.json` version 且在 `main` 上；
  本分支不满足，任何 `v*` tag 都会让闸门红。
- CI 触发面：`on.push.branches: [main, app/macos]`，推 `feat/ui-redesign-p2` 不触发任何 job；
  `--force` 未使用。最终 Commit SHA 以 `git log -1 --format=%H feat/ui-redesign-p2` 为准。

## 9. 已拍板（2026-11-25 用户正式确认）

> 本节此前是三个待问项；现已冻结为决定，后续会话不再重复询问。

1. **视觉方向：接受 Cue Script（录音台本）作为全新视觉世界。** 按本方案推进 Step 3，
   不再回头评估光学声轨 / 字幕校对本等候选。调整只在执行层面（密度、对比度、字号），
   不换世界。
2. **两页 vs 合并：保留「锁轴润色 / 重排润色」两页，不合并。** 放在 `03 原文` 同组下，
   配合编号与页内互相指路，避免用户误触动轴风险。理由见 §2.3；合并只在未来数据显示
   90% 用户只用其中一页时再评估。
3. **明暗与明朝字体：拆成两件事。**
   - **外观**默认 `auto`（跟随系统），设置里保留手动覆盖 `日间校样 / 夜间配音`；
   - **明朝字幕字体**从主题配色中剥离，成为独立的「字幕字体：黑体 / 明朝」偏好；
   - 「明朝墨」不再是一套配色，第三套主题块作废（见 §3.4）。

**核心底线（与以上三条同级）**：本机现役旧版必须能一直独立使用。覆盖 `.app`、污染
`settings.json` / `presets.json` / `userData` / `~/.agents/skills/` 一律视为事故，规则见 §0.1。

## 10. 决策日志

| 日期 | 决策 | 原因 |
| --- | --- | --- |
| 2026-11-25 | 停用 oil-ui 与 11-24 概念稿 A/B/C | 用户明确不喜欢；改用 impeccable + apple-design |
| 2026-11-25 | 新世界：Cue Script（录音台本） | 产品是校对本/台本；避免暗色 NLE + 琥珀的现成答案 |
| 2026-11-25 | 四段导航，⌘1–⌘8 不变 | 顺序已符合用户路径；只改名与分组，降低回归面 |
| 2026-11-25 | 锁轴 / 重排两页 | 数据契约、风险、工具、心智都不同；合并会把风险藏进模式开关 |
| 2026-11-25 | 原型用静态 HTML + headless Chrome | 不碰生产代码、不开窗；确认后再落 Svelte |
| 2026-11-25 | 底栏只读 | HIG：不要把关键动作放底栏；暂存进菜单/工具栏 |
| 2026-11-25 | **三问拍板：接受 Cue Script / 保留两页 / 外观跟随系统 + 独立字幕字体** | 用户正式确认（§9） |
| 2026-11-25 | **旧版双开共存铁律** | 现役旧版是主力生产工具；新版只能以独立产物名/独立 bundleId/独立数据根并行 |
| 2026-11-25 | 第三套「明朝墨」配色作废，明朝降为 `--font-cue` | 一套配色只服务一个明暗语义；字体偏好与明暗正交 |
| 2026-11-25 | 标题栏横跨整窗，侧栏从 y=44 开始 | 红绿灯永远落在标题栏里；消除「竖线穿过黄绿灯」这一整类几何补丁 |
| 2026-11-25 | 底栏只读 + 暂存/恢复进「文件」菜单（⌘S） | HIG：关键动作不放底栏；每个工具栏能力都要有菜单命令 |
| 2026-11-25 | 44px cue 页边只落 CSS 原语，核对台 Step 4 接线 | 本轮不动 `ReviewView.svelte`，但几何/语义先冻结，避免到时候各页各发明 |
| 2026-11-25 | 转写页三步各占 44px 页边写段号 | 段号不是装饰：三步有先后；同时让签名动作在样板间第一次出现 |
| 2026-11-25 | **日间蓝提纯 `#2D5FA6 → #0B63E5`；分段改白色凸起胶囊；选中卡改纸白 + 蓝边** | 用户验收：旧蓝脏暗；收回大面积半透明蓝底，蓝色只聚焦主操作 / 圆点 / 关键指示器 |
| 2026-11-25 | **Step 4.1：ReviewView 先抽纯逻辑，再拆浮层 / 查找会话** | 2583 → 1769；拆分前后 0.000000% 像素差；4.2 才做视觉精修 |
| 2026-11-25 | **Step 4.2：页边记号只认「质检队列 + 译文轨」，不新造状态** | 三种记号（待核 / 已核 / 有译文）都能被用户当场验证；优先级 warn > ok > ai |
| 2026-11-25 | **蓝铅笔只在原文模式画** | 双语模式下每行都盖章 = 噪音；原文模式里它是「哪几句译过」的唯一线索 |
| 2026-11-25 | **检查器删掉「生效参数 / 输出」两段只读信息** | 顶栏与底栏已经各说一遍；同一组读数出现三次正是这次的去噪目标 |
| 2026-11-25 | 检查器宽度保持 348px，未跟随 DESIGN.md 的 388px | 388 属于「舞台行」版布局；当前外壳下 1080 窗口的字幕列会被压到 124px |
| 2026-11-25 | **Step 4.2.1：整轨读数与三个裸链接并成一条 24px 状态条，维护动作收进 `⋯`** | 两个对齐方向 + 三个常驻链接 + 朱红压单句编辑器上方，是 Step 4.2 唯一被点出的凌乱 |
| 2026-11-25 | 危险动作只在菜单里，`删除译文` 与其它项隔一条发丝线 | DESIGN.md §Inspector：danger 隔离、不与主操作相邻；朱红不应常驻 |
| 2026-11-25 | `⋯` 用几何图标（三颗实心点）而非文本字形 `⋯` | 文本字形被字体基线顶到行顶，2× 截图里像一撮浮尘 |
| 2026-11-25 | 菜单内 `Esc` 只关菜单（`stopPropagation`），不清核对台选区 | 红线 6：`Esc` 只清选区；两个「Esc」叠在一起时必须先关浮层 |
| 2026-11-25 | **导入页：已有工程时先给「继续当前工程」，拖入降为 40px 带** | 用户回来问的是「我上次干到哪了」，不是「再选一个文件」 |
| 2026-11-25 | **锁轴 / 重排：①② 编号 + 页头一行「动不动时间轴」+ 互相指路** | §2.3 落地；比模式开关更符合「先锁轴、必要时才重排」的心智 |
| 2026-11-25 | 编号只落在侧栏可见标记，不进 label / aria-label | 快捷键、菜单、脚本都按名字匹配，改名字等于改动三处契约 |
| 2026-11-25 | **「暂无译文轨」全站一次**（导出页头 + 去双语翻译入口） | 同一件事说两遍、还用着改名前的导航名 |
| 2026-11-25 | 成片预览 = 监看器（10px + 近黑底 + 内描边 + `--shadow-video`） | 预览要能判断成片亮度，不能是「一张图」 |
| 2026-11-25 | 设置页类别不用彩色块，改用与侧栏同一套线图标 | Cue Script 里一屏唯一的饱和色是主操作；旧彩块是上一套皮肤的残留 |
| 2026-11-25 | 崩落后允许手动重启内核（`sidecar:restart`） | 自动重连 3 次用完后，桌面端不该只剩「重启应用」 |
| 2026-11-25 | 底栏读数 `.sb-item` → `.st-item` | 与侧栏导航同名，脚本按类名数导航项时会被底栏读数污染 |
| 2026-11-26 | 章节端点两条红的归因：测试前置回全景 + `visible` 筛掉拖动中的条目 | 前者是 67e8434 引入的测试回归；后者是 22eec77 起就有的真实缺陷，松手会丢拖动 |
| 2026-11-26 | `visible` 强制保留 `drag.id` 条目 | 边缘自动平移时视窗会越过已落库区间的半屏裁剪线，条目一被筛掉整块轨道就卸载 |
| 2026-11-26 | 试用版用包内 `app-isolation.json` 换 appName / userData / 数据根 | 正式包默认值不变，不靠临时改名脏配置；隔离根建不起来就拒绝启动 |
| 2026-11-26 | **跑片必须持 `EngineIdleReleaser.hold()` 租约** | 空闲卸载只认「最后一次 touch」，整片跑过 180s 就会把自己正在用的引擎卸掉 → `'NoneType' object is not callable` |
| 2026-11-26 | 去套娃：导出页取消所有分区白卡外壳，只剩标题 + 发丝线 | 用户真机反馈「灰底 → 大白框 → 小白框」三层；DESIGN 本来就禁止卡片套卡片 |
| 2026-11-26 | 选项块（导出形式 / 字幕样式 / 码率）只留一层描边 | 白卡叠白卡时选择项读成「一张张贴纸」；一层描边 + 悬停淡底即可表达可选 |
| 2026-11-26 | 转写页执行栏改成 pane 内最后一个 flex 子项（Docked），不再 sticky-in-scroll | sticky 在滚动容器内部 + 半透明模糊底色 = 贴在灰画布上的白条 |
| 2026-11-26 | 「质检待核」数字改朱红微胶囊，「章节」计数仍是等宽灰数字 | 前者是「要你动手」，与页边待核朱点同义；后者是纯读数。DESIGN 里「计数不是徽标」的规则据此加一个例外 |
| 2026-11-26 | **暗色改成 FCP 式四阶碳灰（stage→canvas→inspector→paper→raise）** | 原来的四阶只差 5–7 个色阶，截图里读成「一块近黑到底」；剪辑台的多阶灰让画面与波形自然跳出来 |
| 2026-11-26 | **亮色翻转：台面纸白、选项块/信息条/输入区改无边框凹陷填充** | 用户原话「灰底上贴白框」「白框套白框」；白底只留台本纸/浮层/输入框 |
| 2026-11-26 | 标题栏外观 = 两态直切，`auto` 只留设置页 | 旧三态循环让「跟随系统 + 系统浅色」的用户要点两下才变暗 |
| 2026-11-26 | 侧栏删除 `①` `②`（`ordinal` 字段一并删） | 带圈数字与线性图标挤在一列，读起来像两个图标叠在一起 |
| 2026-11-26 | 朗读面板只留一颗「收起」，`管理` 用铅笔 | 同一面板里出现两个关闭动作、两个齿轮，是「控件撞车」 |
| 2026-11-26 | 单栏页面统一 `--measure-page` 居中（1040 / 导入 760） | 大窗口下贴左 + 右侧空白读成没做完；共用同一 max-width 就不会再漂左缘 |
| 2026-11-26 | 孤立次级动作一律 `.btn.soft`（或整条提示条内嵌按钮） | 裸蓝字飘在行末既不像动作、又抢主按钮的蓝 |
| 2026-11-26 | `.tts-panel` 必须 `min-width: 0`，动作按钮拆两行 | `flex: 1 0 100%` + 自动最小尺寸（min-content）会把 363px 的面板顶出 348px 检查器 |
| 2026-11-26 | **导入页删掉「继续当前工程」卡，大拖放区无条件做主视觉** | 用户并排对比后拍板：导入页的心智是「拖入新片源」；继续编辑走「最近打开」或 ⌘3 |
| 2026-11-26 | 导入页顺序回到 拖放区 → 代理说明 → 导出文件夹 → 最近打开 | 老版结构更清楚；「上次的稿在哪」比「换哪一部」更贴本页 |
| 2026-11-26 | 本页按钮一律不带尾部 `…`（含打开对话框的次级入口） | 用户：三个点不好看也不规范；本页两个按钮都是立即执行 |

| 2026-11-26 | **`--well-line` 亮色改 `rgba(0,0,0,0.14)`、暗色 0.13；禁止 transparent** | 亮色 well 与 paper 只差 2 个色阶，透明边线让所有下拉 / 数字框只剩一枚三角 |
| 2026-11-26 | **页内命令栏落 `--canvas`，`--paper` 只给窗口外壳** | 灰底 + 白键 = 用户反复报的「灰底白框按钮」；三层灰带同时消失 |
| 2026-11-26 | **`--font-cue` sans 态把 Hiragino 排到 PingFang 前** | PingFang 的假名与部分汉字是中文骨架；日文台本必须用日文字形，中文由后置 fallback 覆盖 |
| 2026-11-26 | **AI 三页：24px 页边 + 28px 控件 + 纸白键细边** | 老版对照后，工具栏控件左缘与标题不齐、边线隐身是最明显的「没做完」 |
| 2026-11-26 | **待生成空态去掉虚线框；采纳勾未选只留空格子** | 虚线框套框读成没画完的表格；未选就画勾会让整列看起来已全选 |
| 2026-11-26 | **新增 `verify_ai_toolbar_controls.mjs`，用计算样式而不是截图守可见性** | 截图只能证明这一次；计算样式能把「边线透明 / 灰底白键」整类问题冻住 |

## 11. 交接清单（新会话）

1. `git status` 必须干净。第一阶段封板在 `feat/ui-redesign`（已冻结，只读）；
   **第二阶段在 `feat/ui-redesign-p2` 上做**；备份分支/tag 已存在且未动（§0.1）。
2. 读本文 §0.1、§1、§2、§7、§9；读 [DESIGN.md](../DESIGN.md) 的 Colors/Typography/Layout/Components。
3. Step 3、Step 4.1、Step 4.2、**Step 4.2.1、Step 4.3 四组、Step 5、Step 6、Step 7 均已完成**
   （§7.3 / §7.3.1 / §7.4 / §7.5 / §7.5.1 / §7.6 / §7.8 / §7.9 / §7.10）。
   不要再把逻辑塞回 ReviewView；每一步的视觉改动各自成 commit。
   **已知遗留：无**——`verify_chapter_edge` 已于 2026-11-26 修绿（§7.8）；
   紧凑模式四条死样式已于 Step 7 归位（§7.10 七）。
   双开试用版路径与试用注意事项见 §7.8。
4. 每次改 `.svelte`：`npm run check` + `check:svelte` + `build`；视觉走 `capture_matrix.sh`。
5. 每步结束：更新本文的 §1 状态表与 §7 状态列；截图放
   `docs/images/refactor-2026-11/`；停在你确认，不跨步。第二阶段按页面分批推进
   （**Batch 1 导入页 §8.10、Batch 2 AI 三页 §8.11、Batch 3 六套色板 §8.12 已完成**）；
   Batch 3 已按用户要求统一重打 `build/pack-next/KikuSub-Next.app`。
6. 任何打包/试用动作先读 §0.1：现役 `.app`、配置文件、`userData` 一律不能覆盖。
