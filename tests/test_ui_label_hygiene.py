"""按钮文案不带尾部省略号（2026-11-26 全站口径）。

## 为什么变成用例

`导入原文…`、`导入译文…`、`管理引擎…`、`用 B 覆盖核对台…` 看着很不整齐；更要紧的是
`…` 在本产品里有**两个已经用掉的语义**：真的在处理（`正在转写…`）与内容被截断
（`…另有 3 条提示`）。当它同时被用来暗示「点开对话框」时，三种含义混成一种，
用户读到「覆盖中…」会分不清是「正在覆盖」还是「点一下覆盖」。

所以口径定死：**动作标签（按钮、菜单项、输入框占位）不带尾部省略号**；
只有「进行中」与「截断」可以带。这条能机械判，就不该靠人记得——
`tools/shots/verify_import_page.mjs` 与 `verify_ai_toolbar_controls.mjs` 只在各自
那一页断言，其余页面漏了没人发现（这次就是转写页与双引擎页）。

## 判据

扫 `desktop/renderer/src/**/*.svelte`，抓三类字符串字面量：

- `>文字…<`：开始标签与结束标签之间；
- `'文字…'` / `"文字…"` 且该行是 `placeholder=` / `title=` / `label=` 赋值；
- 菜单项 `<span class="mi-label">…</span>` 这类（被第一条覆盖）。

白名单是**正在进行**的文案：`正在…` / `…中…` / `等待…`。任何新例外都要写在这里并说明，
否则这条用例失败——这正是提醒。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "desktop" / "renderer" / "src"

#: 允许带 `…` 的语义：真正在做的事，不是「点开一个对话框」。
IN_PROGRESS = re.compile(
    "|".join(
        [
            r"正在",  # 正在准备… / 正在下载…
            r"中…",  # 读取中… / 覆盖中… / 保存中…
            r"等待",  # 等待另一句…
            r"按下新快捷键",  # 快捷键录制：等用户按键
            r"另有",  # 截断提示：…另有 3 条
            r"…另",  # 截断提示：…另 2 条原文
            r"句中的",  # 标点面板在说明「行尾 / 句中」两种省略号口径
            r"行尾的",
            r"一起清",  # 「连句中的 … 一起清掉」：这里的 … 是被清掉的对象
            r"sk-",  # API Key 占位符不是动作
            r"続",
            r"補",
        ]
    )
)

#: 抓「标签文本」：`>……<`（中间不含标签）。
LABEL_TEXT = re.compile(r">([^<>{}]{1,40}…[^<>{}]{0,40})<")
#: 抓 placeholder / aria-label 的字面量。
#:
#: **故意不含 `title=`**：title 是解释性长句（例如「这些行两边只有标点 / 空白不同
#: （、。…「」）」），里面的 `…` 是在**举出省略号这个字符**，不是在暗示「点开对话框」。
#: 把 title 也纳入会让这条用例变成「解释文案不许提到省略号」，那是误伤。
ATTR_TEXT = re.compile(
    r"""(?:placeholder|aria-label)\s*=\s*(?:"([^"]{1,60})"|'([^']{1,60})')"""
)
#: 抓 JS 里 return 的动作文案（`return '查找原文…';`）。
RETURN_TEXT = re.compile(r"""return\s+(?:"([^"]{1,40}…[^"]{0,40})"|'([^']{1,40}…[^']{0,40})')""")


def _svelte_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.svelte") if "dist" not in p.parts)


def _strip_script_comments(text: str) -> str:
    """去掉行注释与块注释：注释里写 `…` 是正常的（解释这条规则本身）。"""
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def _strip_style(text: str) -> str:
    return re.sub(r"<style>[\s\S]*?</style>", "", text)


def _offenders(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    text = _strip_style(_strip_script_comments(raw))
    hits: list[str] = []
    for pattern in (LABEL_TEXT, ATTR_TEXT, RETURN_TEXT):
        for match in pattern.finditer(text):
            value = next((group for group in match.groups() if group), "")
            if not value or "…" not in value and "..." not in value:
                continue
            if IN_PROGRESS.search(value):
                continue
            hits.append(f"{path.relative_to(SRC)}: {value.strip()}")
    return hits


def test_action_labels_have_no_trailing_ellipsis():
    files = _svelte_files()
    assert files, "没有找到任何 .svelte 文件：路径写错了？"
    offenders: list[str] = []
    for path in files:
        offenders.extend(_offenders(path))
    assert offenders == [], (
        "按钮 / 菜单项 / 占位文字里还带着省略号（只允许「正在进行」与「截断」两类）：\n  "
        + "\n  ".join(offenders)
    )


def test_no_ascii_ellipsis_in_labels():
    """ASCII 的 `...` 一律不许出现在动作标签里（中文排版统一用 `…`）。"""
    offenders: list[str] = []
    for path in _svelte_files():
        text = _strip_style(_strip_script_comments(path.read_text(encoding="utf-8")))
        for match in LABEL_TEXT.finditer(text):
            value = match.group(1)
            if "..." in value:
                offenders.append(f"{path.relative_to(SRC)}: {value.strip()}")
    assert offenders == [], "动作标签里出现 ASCII 省略号：\n  " + "\n  ".join(offenders)


def test_dual_replace_button_names_the_scope():
    """双引擎页的写回按钮必须说清范围：不能只写「覆盖」这种会误删别的章节的词。

    2026-11-26 报障：A 是 1–3 章 636 条、B 只有第 3 章 220 条，按钮上只有
    「用 B 覆盖核对台…」——按下去前两章就没了。文案由 `lib/dualScope.ts` 的
    `replaceLabel()` 决定，这里同时守「组件确实用了它」。
    """
    view = (SRC / "views" / "DualView.svelte").read_text(encoding="utf-8")
    assert "replaceLabel(" in view, "双引擎页应当用 replaceLabel() 生成写回按钮文案"
    assert "用 B 覆盖核对台…" not in view, "写回按钮不该再带省略号"
    helper = (SRC / "lib" / "dualScope.ts").read_text(encoding="utf-8")
    assert "用 B 替换当前范围" in helper, "范围对照必须是「用 B 替换当前范围」"
    assert "用 B 覆盖核对台" in helper, "整列覆盖仍然要有自己的名字"
