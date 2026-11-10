#!/usr/bin/env python3
"""生成一份**用于界面验收的假 AI 提案**（不是真实模型输出）。

M1 的验收要求「手写一份提案 → 双栏对照 → 应用」。几百条手写不现实，这个脚本
按 `docs/AI优化与翻译-开发文档-2026-11.md` §3.1 造一份**合法**提案，改动几条，
并在 note 里写明「示例改动」，用来验证 AiView 的加载 / 采纳 / 应用 / ⌘Z 全链路。

改动内容是人为的，**不代表真实修正质量**；它只用来把界面点亮。

用法::

    python tools/make_fake_proposal.py "outputs/xxx.srt"
    python tools/make_fake_proposal.py "outputs/xxx.srt" --count 6
    python tools/make_fake_proposal.py "outputs/xxx.srt" --out-dir ~/Desktop

生成的文件名与软件约定一致：``{stem}.ai-polish.json``。
如果 SRT 在导出文件夹里，软件会去运行数据目录找提案——这时用「导入提案…」按钮
挑这个文件即可，导入会自动把它落到标准位置。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core import ai_proposal as proposals  # noqa: E402
from core.subtitles import srt_to_cues  # noqa: E402

NOTE = "示例改动（非真实建议）"


def fake_edit(text: str) -> str:
    """造一处"看起来像识别错误"的改动；找不到合适位置时返回空串。"""
    if "は" in text:
        return text.replace("は", "わ", 1)
    if "。" in text:
        return text.replace("。", "．", 1)
    if len(text) >= 2:
        return text[:-1] + "…"
    return ""


def pick_indices(total: int, want: int) -> list[int]:
    """在全文里均匀取几个序号（1 起），避免全挤在片头。"""
    if total <= 0:
        return []
    want = max(1, min(want, total))
    step = max(1, total // want)
    picked = list(range(1, total + 1, step))[:want]
    return picked or [1]


def build(srt_path: Path, count: int) -> dict:
    cues = srt_to_cues(srt_path.read_text(encoding="utf-8-sig", errors="replace"))
    if not cues:
        raise SystemExit(f"这个文件里没有解析到字幕：{srt_path}")
    texts = [c.text for c in cues]

    changed: dict[int, str] = {}
    for idx in pick_indices(len(texts), count):
        edited = fake_edit(texts[idx - 1])
        if edited and edited != texts[idx - 1]:
            changed[idx] = edited

    items = []
    for idx, text in enumerate(texts, start=1):
        items.append(
            {
                "i": idx,
                "before": text,
                "after": changed.get(idx, text),
                "note": NOTE if idx in changed else "",
            }
        )

    return proposals.build_proposal(
        kind="polish",
        src_lang="ja",
        texts=texts,
        items=items,
        model="fake-demo",
        entry="skill",
        chunks=1,
        source_path=str(srt_path),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成用于界面验收的假 AI 提案")
    parser.add_argument("srt", help="已导出的字幕文件（.srt）")
    parser.add_argument("--count", type=int, default=5, help="造几处改动（默认 5）")
    parser.add_argument("--out-dir", default="", help="输出目录（默认与 SRT 同目录）")
    args = parser.parse_args(argv)

    srt_path = Path(args.srt).expanduser()
    if not srt_path.is_file():
        raise SystemExit(f"找不到字幕文件：{srt_path}")

    data = build(srt_path, args.count)
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else srt_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = proposals.proposal_path(out_dir, srt_path.stem, "polish")

    check = proposals.validate_proposal(data, [c.text for c in srt_to_cues(
        srt_path.read_text(encoding="utf-8-sig", errors="replace"))])
    if not check.ok:
        raise SystemExit(f"生成的提案没通过自检：{check.errors}")

    out_path.write_text(proposals.dump_proposal(data), encoding="utf-8")

    changed = sum(1 for it in data["items"] if it["after"] != it["before"])
    print(f"已生成提案：{out_path}")
    print(f"  字幕 {len(data['items'])} 条，改动 {changed} 处（note 均标注为「{NOTE}」）")
    print(f"  digest {data['source']['digest'][:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
