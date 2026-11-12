"""文档健康检查（2026-11-13 起）。

方法论里那句"**错误的文档比没有文档更可怕**"是这组用例的全部理由：AI 读到过期文档又不去核对
代码，会把错误当标准去实现新功能，而且人很难发现。2026-11-13 之前这件事只能靠人记得——当天的
排查就发现一份 1087 行的方案文档状态写着"待执行"、引用了已删除的 `static/`、行号也对不上。

这里把四件**机械可判**的事冻住：

1. **链接可解析**：所有 md 相对链接都指向存在的文件（排除构建产物与外部资产目录）；
2. **索引引用的路径存在**：`AGENTS.md` 与 `docs/README.md` 里用反引号写的仓库路径必须真实存在
   （这两个文件是入口，写错的代价最大）；
3. **索引完整**：`docs/` 下的文档都得能在 `docs/README.md` 里找到（否则等于不存在）；
4. **归档件有禁令标注**：`docs/archive/*.md` 必须写明「禁止照它改代码」。

不可机械判的部分（陈述是否还成立、数字是否过时）仍然要人/AI 定期巡检，写进 `docs/backlog.md`。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
README = DOCS / "README.md"
AGENTS = REPO_ROOT / "AGENTS.md"

# 构建产物、依赖、外部设计资产：里面的 md 与路径不归本仓库管
SKIP_DIRS = {"build", "node_modules", ".venv", ".oil-ui", ".git", "dist", ".pytest-tmp", "__pycache__"}

# 反引号路径的白名单顶层目录：只检查"像仓库内路径"的东西，避免把 `foo.md` 这类泛称误判
PATH_ROOTS = ("core/", "server/", "desktop/", "docs/", "tests/", "tools/", ".github/")
FILE_EXT = (".py", ".cjs", ".ts", ".svelte", ".md", ".sh", ".json", ".css", ".png", ".yml", ".yaml")


def _md_files() -> list[Path]:
    out = []
    for path in REPO_ROOT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
    return out


def _strip_frontmatter(text: str) -> str:
    """笔记工具会往 md 里写 created/updated，解析前先剥掉。"""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :]
    return text


def test_markdown_links_resolve():
    """所有 md 相对链接都指向存在的文件。"""
    broken: list[str] = []
    for path in _md_files():
        text = _strip_frontmatter(path.read_text(encoding="utf-8"))
        for match in re.finditer(r"\[[^\]]*\]\(([^)#\s]+)\)", text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if not (path.parent / target).exists():
                broken.append(f"{path.relative_to(REPO_ROOT)}: {target}")

    assert broken == [], "存在失效的 md 链接（改文件名/挪目录后忘了同步）：\n" + "\n".join(broken)


def _checked_docs() -> list[Path]:
    """参与路径对账的文档：入口文件 + 现行契约 + 流程文档。

    `archive/` 刻意排除——归档件允许过期，它只需要有「禁止照它改代码」的标注。
    """
    docs = [AGENTS, README]
    docs += sorted((DOCS / "contracts").glob("*.md"))
    docs += [DOCS / name for name in ("release.md", "review.md", "backlog.md")]
    docs += sorted((DOCS / "templates").glob("*.md"))
    return [p for p in docs if p.exists()]


def _strip_line_suffix(path: str) -> str:
    """`server/app.py:170-177` → `server/app.py`：文档里带行号引用是正常写法。"""
    return re.sub(r":\d+(?:-\d+)?$", "", path)


def test_docs_point_at_real_paths():
    """文档里反引号写的仓库路径必须真的存在。

    这条直接对应"错误的文档比没有文档更可怕"：2026-11-13 归档的那份方案文档里写着
    `server/app.py:170-177`（实际在 198-211）和 `static/reviewer.js`（目录早已删除）。
    AI 照它改代码就会落在不存在的位置上。

    只查"像仓库内路径"的反引号内容：以已知顶层目录开头、以已知扩展名结尾。
    带 glob、占位符、行号后缀的写法按规则处理，避免误判。
    """
    broken: list[str] = []
    for path in _checked_docs():
        text = _strip_frontmatter(path.read_text(encoding="utf-8"))
        for match in re.finditer(r"`([^`\n]+)`", text):
            raw = _strip_line_suffix(match.group(1).strip())
            if not raw.startswith(PATH_ROOTS):
                continue
            if not raw.endswith(FILE_EXT):
                continue
            # glob / 占位符 / 说明性写法不校验
            if any(ch in raw for ch in "*<>{}…（）： "):
                continue
            if not (REPO_ROOT / raw).exists():
                broken.append(f"{path.relative_to(REPO_ROOT)}: `{raw}`")

    assert broken == [], "文档引用了不存在的路径（文档是路由，路由写错比没有路由更致命）：\n" + "\n".join(
        sorted(set(broken))
    )


def test_every_doc_is_indexed():
    """`docs/` 下的文档都要能在 `docs/README.md` 里找到入口。

    不做这条，文档会一直长——包括已经没人看的。`archive/` 与 `sprints/` 例外：
    前者由历史记录表统一收录，后者是轮次记录（README 里按目录收录）。
    """
    readme = README.read_text(encoding="utf-8")
    missing: list[str] = []

    for path in sorted(DOCS.rglob("*.md")):
        rel = path.relative_to(DOCS)
        if rel.parts[0] in {"archive", "sprints"}:
            continue
        if path == README:
            continue
        # 命中文件名或相对 docs 的路径都算登记过
        if path.name in readme or str(rel).replace("\\", "/") in readme:
            continue
        missing.append(str(rel).replace("\\", "/"))

    assert missing == [], (
        "这些文档没有在 docs/README.md 里登记（没人找得到 = 不存在）：\n"
        + "\n".join(missing)
        + "\n\n登记到「现行文档」「审计与排查」或「历史记录」三张表的对应位置。"
    )


def test_archived_docs_are_marked_forbidden():
    """归档件必须有「禁止照它改代码」的标注，且文件名能被一眼认出是归档。"""
    offenders: list[str] = []
    for path in sorted((DOCS / "archive").glob("*.md")):
        text = _strip_frontmatter(path.read_text(encoding="utf-8"))
        if "禁止照它改代码" not in text:
            offenders.append(path.name)

    assert offenders == [], (
        "这些归档件没有标注「禁止照它改代码」——AI 会把它当成现行标准：\n" + "\n".join(offenders)
    )


def test_current_docs_section_does_not_point_into_archive():
    """`docs/README.md` 的「现行文档 / 审计」区不能指向 `archive/`。

    2026-11-13 的问题正是这个：一份已过期的方案文档被列在「现行文档」第一条。
    """
    text = README.read_text(encoding="utf-8")
    history_at = text.find("## 历史记录")
    assert history_at != -1, "docs/README.md 的「## 历史记录」章节被改名或删掉了"
    current_part = text[:history_at]

    leaks = [
        line.strip()
        for line in current_part.splitlines()
        if "archive/" in line
    ]
    assert leaks == [], "「现行文档」区里出现了归档路径：\n" + "\n".join(leaks)


def test_agents_md_stays_an_index():
    """`AGENTS.md` 必须保持"索引"体量：每会话都要读，胖了就是每次多烧一截上下文。

    2026-11-13 之前它是 65KB（≈1.7 万 token）。拆成索引 + 分域契约后约 15KB。
    上限刻意留有余量：涨到 20KB 说明又有细节被塞回来了，该拆到 `docs/contracts/`。
    """
    text = AGENTS.read_text(encoding="utf-8")
    size = len(text.encode("utf-8"))
    assert size < 20_000, (
        f"AGENTS.md 已经 {size} 字节（上限 20000）。细节搬去 docs/contracts/，这里只留红线与索引。"
    )
