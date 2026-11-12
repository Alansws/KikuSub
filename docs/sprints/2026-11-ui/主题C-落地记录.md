# C 方向主题「明朝墨」落地记录（2026-11-12）

> 目标：在默认主题「青空」之外增加一套此前已定稿的方向 C，切换器放设置页；
> 默认主题保留浅色 + 深色，新主题单色（固定浅色）。结构、间距、字号、行高一律不动。

## 1. 为什么不是纯 A，也不是全量 B

用户给的门槛是：**要么不破坏功能逻辑、并且对后续界面优化有复利，才走 B；否则走 A。**

- 全量 B（650 处原始 px 全部令牌化 + 密度令牌 + 布局常量动态化）**会碰到功能耦合**：
  `ROW_H=30` / `LANE_H=17` / `FOCUS_ZOOM=69` 同时被核对台的虚拟滚动、命中测试与画布绘制
  使用，把密度做成可主题覆盖的变量，等于把主题改动带进滚动与点击判定。这违反「不破坏功能逻辑」。
- 纯 A（只加一块配色覆盖）**没有复利**：状态色、`--on-accent`、字幕字体这些仍然散落在组件里，
  下一套主题还得重新扫一遍。

实际采用 **A + B 里真正有复利的那一小块**：

1. 主题注册表（`lib/themes.ts`）：id → 名称 / 所属主题 / scheme，加主题只改注册表 + 一块 CSS；
2. 令牌收口：状态色（danger/warn/success + soft）、`--on-accent`、`--control-on`、
   `--btn-primary-bg/--btn-primary-hover`、`--shadow-btn/--shadow-seg`、`--scroll-thumb`、
   `--hit/--hit-row`、`--font-cue`；
3. 不做：密度 / 字阶 / 布局常量的全量替换（等第二套「结构级」皮肤出现时再动，届时一次性做）。

## 2. 命名

方向卡里这套稿子叫「冷白编辑」，那是设计轮次的标签。落到产品里改名 **「明朝墨」**：
用户第一眼看到的是纸白 + 墨黑 + 明朝字幕，「冷白」既不是它的识别特征，也会让下一个读代码的人
以为这是一套「白到发冷」的配色。id 同步从 `cool` 改为 `mincho`，旧值 `cool` 在冷启动时
自动迁移（`localStorage` 与 `preferences.json` 都兼容）。

## 3. 定义

| 角色 | 值 | 说明 |
| --- | --- | --- |
| canvas | `#F1F3F0` | 冷白（带一点灰绿），侧栏叠在 vibrancy 上 |
| paper | `#FAFAF8` | 内容区 |
| raise | `#FFFFFF` | 卡片 / 输入 / 浮层 |
| ink / ink2 / ink3 | `#15181B` / `#5E6468` / `#666C70` | 墨黑结构 |
| accent（信号色） | `#C8412D` | 朱红：当前句、选中、播放头、进度 |
| 主操作实心色 `--btn-primary-bg` | `#C8412D`（= accent） | 按钮跟主题色统一 |
| 控件「开」色 `--control-on` | `#C8412D`（= accent） | 开关 / 勾选 / 滑杆也跟主题色统一 |
| danger / warn / success | `#9E2318` / `#8A5A00` / `#2E6B45` | 状态三色 |
| 字幕字体 `--font-cue` | Hiragino Mincho ProN → Yu Mincho → Noto Serif JP → Songti SC | 只有字幕换；UI 仍是苹方 |

对比度（WCAG，对着 `paper`）：ink 17.1:1、ink2 5.7:1、ink3 5.1:1、accent 4.7:1、
danger 7.4:1、warn 5.7:1、success 6.1:1；白字压朱红 4.9:1，白字压墨黑 17.8:1。

## 4. 逐文件改动

| 文件 | 改动 |
| --- | --- |
| `renderer/src/lib/themes.ts`（新增） | 主题注册表：`SKINS` / `SCHEMES` / `isThemeId` / `schemeOf` / `skinOf` |
| `renderer/src/app.css` | 新令牌（软状态色、on-accent、control-on、阴影、滚动条、查找命中、`--font-cue`、`--btn-primary-bg`）；`html[data-theme='mincho']` 主题块；`color-scheme`。两个 action 令牌在两套主题下都等于 accent |
| `renderer/src/lib/store.svelte.ts` | `theme: ThemeId`；`setTheme / setSkin / setMode / toggleTheme`；记住青空上次的明暗；`cool → mincho` 迁移 |
| `renderer/src/main.ts` | 冷启动接受 `mincho`（并迁移旧值），避免首帧闪默认主题 |
| `renderer/src/views/SettingsView.svelte` | 「主题 / 明暗」两行；实心色点；选中加墨边；单色主题下明暗行变描边态 |
| `main/main.cjs` | `window:set-theme` 把外观 id 写进 preferences（nativeTheme 仍只认 scheme） |
| `renderer/src/global.d.ts` | `setTheme` 类型放宽到 `'light' \| 'dark' \| 'mincho'` |
| `renderer/src/{App,components/*,views/*}.svelte` | 状态色与 `#fff` 收进令牌；删掉多余 dark 覆盖；Toolbar 的 `--line2` 改 `--line-2`；开关/勾选/滑杆改 `--control-on` |
| `renderer/src/views/ReviewView.svelte` / `components/Inspector.svelte` | 字幕单元格、画面叠加层、检查器当前句走 `--font-cue`；译文轨仍走 `--font-sans`；表头「字幕文本」留在黑体 |
| `AGENTS.md` / `README.md` / `README_EN.md` | 主题机制与用户可见行为的说明 |

## 5. 兼容与回归

- 旧值 `light` / `dark` 原样可用；`cool`（改名前）冷启动迁移为 `mincho`，`preferences.json` 同样兼容。
- 默认浅色主题观感不变：新令牌默认值与原硬编码逐一对应（`--shadow-btn` = 原
  `0 1px 2px rgba(27,39,64,.18)` 等）；深色只是把滚动条阴影从墨蓝换成纯黑，肉眼不可见。
- `npm run build` 通过；`npx tsc --noEmit` 无错误；`npm run test:main` 21/21。
- 运行时切换（真机、无刷新）：明朝墨 → 明暗置灰且不生效 → 切回青空恢复上次明暗；
  月亮按钮从明朝墨跳到深色，再按回浅色。
- 200% 页面缩放：紧凑侧栏、状态栏、设置页两行控件都不溢出。
- 计算样式核对：`--font-cue` 在 light/dark 解析为苹方、mincho 解析为明朝；
  `--btn-primary-bg` 依次为 `#4f6bff / #7d93ff / #15181b`。
- 结构没位移：右侧检查器分隔线 y 坐标、表头 bbox 与浅色主题逐像素一致（换字体没改行高）。

## 6. 独立评审（一轮，不打分）与处理

派了一个无历史上下文的评审子 Agent，按「存量已有界面润色评审」标准看 13 张当前截图。

**采纳**

1. 表头「字幕文本」跟着字幕用了衬线、字重掉档 —— 真 bug：`.c-text` 同时命中表头与单元格。
   先改成黑体 500，**用户看过之后要求表头也用衬线**（“不用衬线太丑”），已改回：
   表头与单元格同用 `--font-cue`（明朝墨下是明朝，青空下仍是苹方）。
2. 主题切换器：色环像单选点、选中态只有阴影（1.05:1）、禁用态 1.3:1 几乎看不见。
   改成实心色点 + 选中 1px 墨边 + 禁用行描边（常规字色）。
3. 设置页「换的是配色与字幕字体；工具栏、核对表、检查器的结构不动。」是写进界面的设计说明，
   改成「切换后立即生效，可随时改回。」

**先采纳后反转（产品决定）**

- 评审第 1 条主张「朱红只做信号，按钮/开关/滑杆改墨黑」；实现过一版（`--btn-primary-bg`
  与 `--control-on` 在明朝墨下都换 `--ink`），用户看到后明确否掉：**按钮、滑杆、开关要跟
  主题色统一，不要有的按钮是黑的**。已把两个令牌在两套主题下都固定回 `accent`，
  只保留令牌本身（以后真要做墨色主按钮的主题再用）。这条写进 AGENTS.md，避免下一轮又被改回去。

**不采纳（附理由）**

1. 「更新此行」读起来像禁用 —— 它当时确实是 `disabled`（草稿与原文相同，没有可提交内容），
   编辑后就是主题色实心。这是既有禁用语法（P1 定的「主按钮要么实心、要么明确退成灰」），不改。
2. 「新建模板 / 复制提示词是朱红按钮」—— 评审拿到的提示词库截图早于令牌调整；当前两者
   与主题色一致（证据 `shots/prompts-cool.png`）。
3. 「选中态两种红底」—— 同一个 alpha 落在 canvas 与 paper 两个底上的结果，属既有语义；
   统一成实色会同时牵动侧栏与表格两层结构，不在本轮。
4. 「补 warning 色」—— C 方向卡只定了 accent / danger / success，warn 继承默认主题的
   `#8A5A00`；新增色相要重新做方向判断，留到下次。

## 7. 未做 / 未覆盖

- 动效未取证：主题切换有没有闪白、切换后滚动位置与选中态是否保留，没有录屏或序列图。
- 质检浮层（QaPanel）没有截图：颜色已全部走令牌，但要展开面板需要一份与当前字幕对得上的
  质检 payload，本轮没有造。
- 200% 缩放下核对表与检查器没有全量截图（只覆盖视频、播放条、设置页）。
- 打包后的 `.app` 没有重打（本轮只改渲染层与主进程；发版前按 HANDOFF 走 rebuild）。
- 已知临界值：当前行行号（12px）在选中底色上 4.3:1，低于 AA 正常字号 0.2；要修就得把
  行号改成墨色或换更浅的 tint，两者都会动到「当前句」的既有强调。
