"""大文件预算（2026-11-13 起）。

背景：`lib/store.svelte.ts` 与 `views/ReviewView.svelte` 各约 3900 行。它们的风险不是"风格不好"，
而是**任何功能只要碰到它们，agent 都得先读完几千行才能动手**——读完之后，对早期规则的遵循度
就会下降。这正是方法论里"上下文变长之后 AI 对早期规则的遵循度会下降"的具体形态。

一次性拆开是高风险动作（会动正在跑的核对台），所以这里选的是**只许变短**：
新增功能若让这两个文件变长，就必须先把这次用到的那部分纯逻辑抽到 `lib/`——抽出来的东西
是"这次真的要用到的"，不是为拆而拆。这条和 `style-baseline.json`、`AGENTS.md` 体积上限
是同一个套路：基线冻结，数字只许往下走。

真的需要放宽时（例如确认没有可抽的纯逻辑）：调大这里的数字，并在提交信息里写清理由。
那一步本身就是提醒——"又在 4000 行文件里加东西了"。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "desktop" / "renderer" / "src"

# 2026-11-13 冻结值。只许下调；上调要在提交信息里说明为什么这次没法抽。
# 2026-11-14：新增「断句重排」视图，`View` 联合类型必须多一行（没有可抽的纯逻辑）。
# 2026-11-15：代理提示抽成 ProxyGate + videoFallback，导入不再自动压代理。
# 2026-11-16：开发种子注入（applyDevSeed）抽到 `lib/devSeed.ts`，store 降到 3287。
# 2026-11-17：波形绘制 / 时间轴视窗 / 切割校验抽到 lib，ReviewView 降到 3808；
#              同轮专业剪辑操作（逐帧/磁吸/倍速）完成后再降到 3802。
# 2026-11-20：工作现场持久化 + 章节标记落在新 lib / 新组件里，但接线仍需占行，
#              所以先把能抽的两块抽走：画布画法 → lib/waveformCanvas.ts、
#              查找命中计算 → lib/findMatches.ts、旧播放头持久化 → lib/reviewViewport.ts。
#              抽完并接线后的实测值就是新预算（只许再降）。
# 2026-11-20（片段范围）：局部处理 / 导出范围要给 store 加状态与请求字段，先把两块
#              纯逻辑抽走：导出文案标签 → lib/exportLabels.ts、导出样式持久化 →
#              lib/exportStorage.ts（store 先降到 3228），再用腾出的行数接线
#              `exporter.clip` + `setExportClip()`（接线后 3258）。净预算仍是从
#              3278 下调到 3258——这次没有为了加功能而放宽任何行数。
# 2026-11-21（界面重构 Step 3）：核对台的「查找高亮切分」整段搬进
#              `lib/findMatches.ts`（`highlightSegments` 本来就是纯函数），
#              ReviewView 3787 → 3748；再用腾出的行数接线「默认打开态」
#              （`lib/reviewStart.ts`：长片 50× 视野 + 第 1 条 + 有译文轨默认双语）
#              与字幕轨道 17 → 24px（连线后 3780）。净预算 3787 → 3780。
# 2026-11-24（界面原生化 Phase 0）：核对台按「纯搬运、视觉零变化」拆出三个组件——
#              走带 + 缩放行 → components/review/ReviewTransport.svelte，
#              视频监看 → ReviewStage.svelte，波形/字幕轨道 → ReviewWaveTrack.svelte；
#              同时删掉已被 SelectionBar 接管、在本文件里早已没有使用者的
#              .sel-bar / .sel-info / .spin 死样式。每一步都用无窗口截图做像素比对
#              （0.0000% 差异）后才继续。3780 → 3158。字幕表格与查找栏是 Phase 2
#              真正要改列的地方，等那时连同纯逻辑一起抽（红线 11 的「先抽再改」）。
# 2026-11-24（Phase 2）：先把表格的虚拟列表纯逻辑抽到 lib/reviewTable.ts（单独 commit，
#              含 16 条单测，顺手修了 NaN 输入会算出空窗口的 bug），再把整块表格
#              （表头 + 虚拟列表 + 查找栏）搬到 components/review/ReviewTable.svelte。
#              两步都逐像素比对过（0.0000% 差异）。3780 → 3158 → 2644。
# 2026-11-24（Phase 2 暗底舞台）：加「可拖高的监看区」时先抽 lib/stagePrefs.ts
#              （高度偏好 + 上限 + 状态条文案，三条纯函数），再接线的；净 +30 行
#              是舞台状态条与分隔条接线本身，预算按实测值 2645 记。
# 2026-11-24（当日收口）：撤销表格「状态」列与舞台状态条，ReviewView 2645 → 2619；
#              lib/reviewRowStatus.ts 与其 18 条单测一并删除（不留半套实现）。
# 2026-11-25（播放头边缘自动滚动）：擦洗状态机 + 边缘推进器整段搬进 lib/scrub.ts
#              （零运行时相对导入，`node --test` 直接加载），ReviewView 2619 → 2586；
#              接线只多出 scrub/scrubPan 两个构造块，净减 33 行，预算随实测值下调。
# 2026-11-25（章节端点拖动）：给 ChapterTrack 接 `onview` 要占一行，先把两处重复的
#              `xPlayhead()` 换成 `xOf(play.time)` 内联（删 3 行），2586 → 2583。
# 2026-11-25（译文轨三态 / 单句补译）：stale 判定搬进 `lib/translationStatus.ts`、
#              「只动句读」的本地对齐搬进 `lib/translationBase.ts`，store 只留两行接线；
#              3255 → 3252（下调，不是放宽）。
# 2026-11-25（Cue Script 外观模型）：外观偏好的读取 / 迁移搬进 `lib/appearance.ts`
#              （纯函数、可被 node --test 直接加载），响应式状态与落地搬进
#              `lib/appearanceState.svelte.ts`；store 只留解析后的 `app.theme`
#              （核对台波形只认它）。3252 → 3217，预算随实测值下调。
# 2026-11-25（Step 4.1 纯结构拆分）：先把 cue / 画面纯计算搬到 lib/reviewCues.ts
#              （单独 commit，截图 PSNR inf），再把查找 / 替换会话搬到
#              lib/reviewFind.svelte.ts、右键菜单与「新建音色」浮层搬到
#              components/review/；ReviewView 2583 → 1769。两次比对均逐像素一致。
BUDGET = {
    "lib/store.svelte.ts": 3217,
    "views/ReviewView.svelte": 1769,
}


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_big_files_do_not_grow():
    offenders: list[str] = []

    for rel, budget in BUDGET.items():
        path = SRC / rel
        assert path.exists(), f"预算表里的文件不见了：{rel}（改路径时同步更新 BUDGET）"
        now = _line_count(path)
        if now > budget:
            offenders.append(f"{rel}: {now} 行（预算 {budget}，超出 {now - budget}）")

    assert offenders == [], (
        "这两个文件已经太大，不允许继续变长：\n"
        + "\n".join(offenders)
        + "\n\n做法：先把**这次功能要用到的**纯逻辑抽到 `desktop/renderer/src/lib/` 下的新文件"
        "（单独一个 commit，行为不变、`npm run check` 与 `check:svelte` 数字不涨），再在原文件里接线。\n"
        "抽完把 tests/test_big_file_budget.py 里的 BUDGET 下调。\n"
        "确实没有可抽的纯逻辑时，才调大 BUDGET，并在提交信息里写清理由。"
    )


def test_budget_is_not_stale():
    """预算只该随文件变小而下调。比预算小很多说明忘了更新——否则预算会慢慢失去意义。"""
    stale: list[str] = []

    for rel, budget in BUDGET.items():
        now = _line_count(SRC / rel)
        if now < budget - 100:
            stale.append(f"{rel}: 现在 {now} 行，预算还写着 {budget}")

    assert stale == [], "文件明显小于预算了，把 BUDGET 调到实际值：\n" + "\n".join(stale)
