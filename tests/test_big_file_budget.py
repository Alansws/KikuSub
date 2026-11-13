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
BUDGET = {
    "lib/store.svelte.ts": 3928,
    "views/ReviewView.svelte": 3927,
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
