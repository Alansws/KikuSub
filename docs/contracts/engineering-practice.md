# 工程方法论：长期 AI 开发的护栏

> 提炼自 Oil《如何用 AI 长期开发一个复杂项目》（视频 + Oil Book 第 07 章），并**只保留在本仓库
> 真正落地了的那些**——没落地的写在最后一节，别当成现状。改动本文件前先读
> [AGENTS.md](../../AGENTS.md) 的红线；具体接口契约在 `docs/contracts/` 其它几份里。

长期项目不是"写得对不对"的问题，而是"**失控之后还能不能撑住**"的问题。原始总结把失控拆成五类，
这里逐条对照本仓库的现状与对应护栏。

## 1. 五类失控 → 本仓库的对应物

| 失控类型 | 在本仓库长什么样 | 现状与护栏 |
| --- | --- | --- |
| 样式各写一套 | 颜色早已收敛到 `app.css` 令牌，但**布局节奏**曾长期裸写：`.sec-head` 在导出/设置是 `flex-start`、在报告页是 `baseline`；间距散着 7/9/11/13/14 这类一次性值 | 2026-11-13 起：像素等值的间距声明机械替换为 `var(--sp-N)`（276 处，PSNR 验证像素不变）；`desktop/test/style-drift.test.cjs` 冻结基线，新增裸 px 或新共享块副本直接红 |
| 硬编码 | 代码里没有写死的绝对路径；但版本号曾在 `package.json` 与 `tools/pack/build_app.sh` 双写 | 改为单一来源（脚本读 `package.json`），`tests/test_pack_version.py` 看守 |
| 重复逻辑 | `proposal_from_srt` 在翻译/润色两条通道近乎逐行相同；`_settings_path` 在三个 router 里各一份 | 抽出 `core/proposal_srt.align_model_srt` 与 `server/deps.settings_path`，差异只留 kind/note/措辞 |
| 冗余代码 / 死测试 | 全仓 `TODO/FIXME/HACK` 为 0；但单测容易越攒越机械化（验证 `1+1==2` 那种） | 定期让 AI 扫一遍"删掉后没有断言价值"的用例；保留两类：基础可用性 + 复杂易错路径的端到端 |
| 文档累积且过期 | 曾经 `AGENTS.md` 单文件 65KB，其中 §4/§5 仍在描述已删除的 Gradio 面板 | 2026-11-13：拆成「索引（AGENTS.md）+ `docs/contracts/` 分域契约 + `docs/archive/`」；归档件首行标注「禁止照它改代码」 |

## 2. 五道护栏 → 落点

| 护栏 | 在本仓库落成什么 | 怎么用 |
| --- | --- | --- |
| ① 选型 | `docs/contracts/` 只记录已定的技术选择与理由（Electron + sidecar、原生而非跨端、令牌体系） | 要换技术栈时先看这里有没有反向约束 |
| ② 方案 | 改任何一域前先读对应契约（`review-console` / `desktop-lifecycle` / `ai-proposal` / `export-and-prompt`）；方案要"人能看懂"：界面怎么变、思路与改动范围、特殊情况与取舍、怎么验收 | 读契约 → 写 4 句话方案 → 再动手 |
| ③ 任务派发 | 主 Agent 定方向，执行方按契约做，不许自由发挥；提交按层拆（`core,server` / `desktop` / `docs`） | 见 [AGENTS.md](../../AGENTS.md) §5 |
| ④ 测试与取证 | `pytest`（412 例）、`python -m core.smoke`、`npm run test:main`（28 例）、`--screenshot` 静默取证、`KIKUSUB_DEV_SEED` 造状态 | 静默截图不抢焦点，可后台跑；像素比对用 PSNR |
| ⑤ 发版 | `tools/pack/rebuild.sh` 一条命令；`build_app.sh` 会因 sidecar 过期直接退出；连续 2 次启动失败进安全模式（`desktop/main/launchguard.cjs`） | 见 [AGENTS.md](../../AGENTS.md) §6 |

### 静默取证（最容易被忽略的一条）

`--screenshot` 走的是 `show:false` + `capturePage`，**不抢焦点**，所以可以在你干活的同时跑：
先 `KIKUSUB_DEV_SEED` 造出目标状态，再截图，最后用 PSNR 与基线比。改样式的验证标准不是
"编译通过"，而是"三屏截图 PSNR 不掉"。

## 3. 两条方法论级纪律

### 3.1 规则要么进红线，要么进测试

同一个位置在 review 里被反复指出，说明"写进文档"不够。分三级升级：

1. 一句话进 [AGENTS.md](../../AGENTS.md) 的红线（人/agent 每次都会读）；
2. 进 `docs/contracts/` 对应域（需要细读时看）；
3. **变成测试**——能变成测试的优先变：`desktop/test/svelte-imports.test.cjs`（Svelte 5 未 import 的标识符
   会在运行期炸整棵树）、`desktop/test/style-drift.test.cjs`（样式漂移）、`tests/test_pack_version.py`
   （版本双写）、`core/smoke.py`（core 不许依赖 UI）。

### 3.2 文档是路由，不是全文

AGENTS.md 的职责是"告诉你去读哪一页"，不是"装下所有细节"。判断标准很简单：**它的体积要在
一次会话的上下文预算里可忽略**。2026-11-13 之前是 65KB（约 1.7 万 token / 次），拆完 12.7KB。

## 4. 多模型协作（可选，成本很低）

契约写清楚之后，"让另一家模型审一遍"几乎零成本：

```bash
git diff main...HEAD > /tmp/d.patch
codex exec --cd . "读 AGENTS.md 与 docs/contracts/，按四个目标审 /tmp/d.patch：
① 业务是否真跑通（有无端到端、有无写没意义的测试）② 实现是否优雅、有无冗余与自造轮子
③ 有没有复用已有基建 ④ 有没有踩红线。逐条给证据与置信度（0-100）。"
```

排障时更管用：让**两个强模型各自定位同一个 Bug 并给置信度**。都打不到 60 分，说明这个功能
本身难做——考虑砍需求或绕路，而不是让 AI 继续硬修（硬修出来的东西上线后维护成本极高）。

## 5. 还没做的（别当成现状）

- **布局语义块仍有副本**：`.sec / .sec-head / .actions / .empty` 还在 3–6 个文件里各写一套，
  基线冻结但没合并成共享组件；7/9/11/13/14/18/22 这些非刻度值仍在用，需要视觉验收后再决定归并。
- **大文件拆分**：`store.svelte.ts`（≈3.9k 行）、`ReviewView.svelte`（≈3.9k 行）、`main.cjs`（≈1.5k 行）
  尚未按"纯计算出 Svelte、按面板拆组件"的路径拆开。
- **发版四步**（合入审查 → 本地实测 → 云端打包 → 官网日志）目前靠人执行，没有写成程序化闸门；
  CI 已覆盖测试，但"官网版本号没更新不许发"这类检查还没有。
